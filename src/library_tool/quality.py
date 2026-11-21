"""원본 DataFrame을 변경하지 않는 공공도서관 데이터 품질 진단."""

from datetime import date, datetime
import math
import re

import pandas as pd


CORE_COLUMNS = ("도서관명", "시도명", "시군구명", "소재지도로명주소", "데이터기준일자")
COORDINATE_COLUMNS = ("위도", "경도")
TIME_COLUMNS = tuple(
    f"{day}운영{endpoint}시각"
    for day in ("평일", "토요일", "공휴일")
    for endpoint in ("시작", "종료")
)
REQUIRED_COLUMNS = CORE_COLUMNS + COORDINATE_COLUMNS + TIME_COLUMNS
TIME_PATTERN = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _missing_kind(value: object) -> str | None:
    """빈 문자열·공백 문자열·pandas 결측을 구분하고 문자 NA는 보존한다."""
    if isinstance(value, str):
        if value == "":
            return "empty_string"
        if not value.strip():
            return "whitespace_only"
        return None
    return "pandas_missing" if pd.isna(value) else None


def _snapshot(value: object) -> object:
    """JSON에 쓸 스칼라/인덱스 사본을 만든다. 표현 차이는 별도 repr로 남긴다."""
    if isinstance(value, dict):
        return {str(key): _snapshot(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_snapshot(item) for item in value]
    if isinstance(value, str) or value is None:
        return value
    if pd.isna(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _snapshot(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, (bool, int, float)):
        return value
    return repr(value)


def diagnose_quality(dataframe: pd.DataFrame, *, reference_date: date | None = None) -> dict:
    """합의된 규칙의 요약·상세·관측값을 JSON 저장 가능한 사전으로 반환한다.

    모든 행 번호는 입력 순서의 1부터 시작하며 헤더를 제외한다. 원본 인덱스는
    별도 보존한다. 비율은 0~100의 백분율이고 분모가 0이면 None이다.
    누락 컬럼은 검사 불가, 빈 표의 존재하는 컬럼은 검사 대상 없음으로 구분한다.
    reference_date를 주입하면 미래 날짜 판정을 테스트에서 재현할 수 있다.
    """
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("진단 데이터는 pandas DataFrame이어야 합니다.")
    if not dataframe.columns.is_unique:
        raise ValueError("동일한 컬럼명이 여러 개 있어 진단할 수 없습니다.")
    if reference_date is None:
        reference_date = date.today()
    if not isinstance(reference_date, date) or isinstance(reference_date, datetime):
        raise TypeError("기준일은 datetime.date이어야 합니다.")

    row_count = len(dataframe)
    summaries, details = [], []
    affected_positions = set()
    values = {column: dataframe[column].tolist() for column in dataframe.columns}
    missing = {
        column: [_missing_kind(value) for value in column_values]
        for column, column_values in values.items()
    }
    indexes = dataframe.index.tolist()

    def summarize(rule, columns, category, positions, denominator, reason, *,
                  available=True, informational=False, metrics=None):
        """각 집계의 분모를 명시하고 정보용 빈도는 문제 행 수에 더하지 않는다."""
        positions = list(positions)
        if not available:
            status, count, ratio = "검사 불가", None, None
        else:
            count = len(positions)
            ratio = count / denominator * 100 if denominator else None
            status = ("검사 대상 없음" if not denominator else
                      "관측" if informational else "발견" if count else "정상")
            if not informational:
                affected_positions.update(positions)
        summaries.append({
            "rule_id": rule, "columns": list(columns), "category": category,
            "status": status, "inspected_rows": denominator if available else 0,
            "count": count, "denominator": denominator if available else None,
            "ratio_percent": ratio, "reason": reason, "metrics": metrics or {},
        })

    def record(rule, position, columns, result, reason, group_id=None):
        """위치로 추적하여 중복된 DataFrame 인덱스도 구별한다."""
        raw = {column: values[column][position] for column in columns}
        details.append({
            "rule_id": rule, "data_row": position + 1,
            "dataframe_index": _snapshot(indexes[position]),
            "dataframe_index_repr": repr(indexes[position]),
            "columns": list(columns), "raw_values": _snapshot(raw),
            "raw_value_reprs": {column: repr(value) for column, value in raw.items()},
            "raw_value_types": {column: type(value).__name__ for column, value in raw.items()},
            "result": result, "reason": reason, "duplicate_group_id": group_id,
        })

    def unavailable(rule, columns, category):
        """필요 컬럼이 없으면 0건 대신 검사 불가를 반환한다."""
        absent = [column for column in columns if column not in values]
        if absent:
            summarize(rule, columns, category, [], 0,
                      "누락 컬럼: " + ", ".join(absent), available=False)
        return bool(absent)

    for column in REQUIRED_COLUMNS:
        exists = column in values
        summarize("SCHEMA-01", [column], "column_presence", [], row_count,
                  "컬럼 존재" if exists else f"누락 컬럼: {column}", available=exists)

    for column in values:
        for kind in ("empty_string", "whitespace_only", "pandas_missing"):
            positions = [pos for pos, actual in enumerate(missing[column]) if actual == kind]
            summarize("MISS-01", [column], kind, positions, row_count,
                      "분모: 전체 행. 문자 NA는 결측으로 취급하지 않음.")
            for pos in positions:
                record("MISS-01", pos, [column], "결측", kind)
        positions = [pos for pos, value in enumerate(values[column])
                     if isinstance(value, str) and value != value.strip()]
        summarize("TEXT-01", [column], "outer_whitespace", positions, row_count,
                  "분모: 전체 행. str.strip()이 인식하는 앞뒤 공백(전각 포함); 보정하지 않음.")
        for pos in positions:
            record("TEXT-01", pos, [column], "검토 후보", "문자열 앞뒤 공백")

    for column in CORE_COLUMNS:
        if unavailable("CORE-01", [column], "required_value_missing"):
            continue
        positions = [pos for pos, kind in enumerate(missing[column]) if kind is not None]
        summarize("CORE-01", [column], "required_value_missing", positions, row_count,
                  "분모: 전체 행. 핵심 필수값 결측; 원본 보정 없이 보고.")
        for pos in positions:
            record("CORE-01", pos, [column], "필수값 누락", missing[column][pos])

    def duplicates(rule, columns, frame, eligible, excluded):
        """참여 행 수·그룹 수·첫 행 이후 추가 행 수를 별도 집계한다."""
        groups = []
        if len(frame):
            # 입력 인덱스가 아닌 groupby의 위치를 사용한다. 결측끼리도 비교한다.
            groups = [list(positions) for positions in
                      frame.groupby(list(columns), sort=False, dropna=False).indices.values()
                      if len(positions) > 1]
            groups.sort(key=min)
        participating = [eligible[pos] for group in groups for pos in group]
        summarize(rule, columns, "duplicate_rows" if rule == "DUP-01" else "duplicate_candidates",
                  participating, len(eligible),
                  "분모: 비교 가능한 행. 참여 행 수이며 삭제 대상 수가 아님.",
                  metrics={"group_count": len(groups), "participating_rows": len(participating),
                           "extra_rows": sum(len(group) - 1 for group in groups),
                           "excluded_missing_key_rows": excluded})
        for number, group in enumerate(groups, start=1):
            for pos in group:
                record(rule, eligible[pos], columns, "검토 후보",
                       "전체 컬럼 동일" if rule == "DUP-01" else
                       "앞뒤 공백을 제거한 이름+주소 동일; 같은 시설로 확정하지 않음",
                       f"{rule}-{number:04d}")

    if len(dataframe.columns):
        duplicates("DUP-01", tuple(dataframe.columns), dataframe,
                   list(range(row_count)), 0)
    else:
        summarize("DUP-01", [], "duplicate_rows", [], 0,
                  "비교할 컬럼이 없음", available=False)
    keys = ("도서관명", "소재지도로명주소")
    if not unavailable("DUP-02", keys, "duplicate_candidates"):
        eligible = [pos for pos in range(row_count)
                    if all(missing[column][pos] is None for column in keys)]
        # 비교용 표만 정규화한다. 원본과 상세 기록의 문자열은 유지한다.
        key_frame = pd.DataFrame({
            column: [value.strip() if isinstance(value, str) else value
                     for value in (values[column][pos] for pos in eligible)]
            for column in keys
        })
        duplicates("DUP-02", keys, key_frame, eligible, row_count - len(eligible))

    for column, lower, upper in (("위도", -90, 90), ("경도", -180, 180)):
        if unavailable("GEO-01", [column], "invalid_number"):
            unavailable("GEO-02", [column], "outside_global_range")
            continue
        present = [pos for pos, kind in enumerate(missing[column]) if kind is None]
        invalid, nonfinite, finite = [], [], {}
        for pos in present:
            try:
                number = float(values[column][pos])
            except (ValueError, TypeError, OverflowError):
                invalid.append(pos)
                continue
            if math.isfinite(number):
                finite[pos] = number
            else:
                nonfinite.append(pos)
        for category, positions, reason in (
            ("invalid_number", invalid, "숫자 변환 실패"),
            ("nonfinite_number", nonfinite, "NaN/무한대 등 유한하지 않은 숫자"),
        ):
            summarize("GEO-01", [column], category, positions, len(present),
                      "분모: 비결측 값. " + reason)
            for pos in positions:
                record("GEO-01", pos, [column], "형식 오류", reason)
        outside = [pos for pos, number in finite.items() if not lower <= number <= upper]
        summarize("GEO-02", [column], "outside_global_range", outside, len(finite),
                  f"분모: 변환 성공한 유한한 값. 허용 범위 {lower}~{upper} (경계 포함).")
        for pos in outside:
            record("GEO-02", pos, [column], "범위 오류", f"{lower}~{upper} 밖의 값")
    if not unavailable("GEO-03", COORDINATE_COLUMNS, "coordinate_missing"):
        for category, missing_count in (("both_missing", 2), ("one_missing", 1)):
            positions = [pos for pos in range(row_count)
                         if sum(missing[column][pos] is not None
                                for column in COORDINATE_COLUMNS) == missing_count]
            summarize("GEO-03", COORDINATE_COLUMNS, category, positions, row_count,
                      "분모: 전체 행. 좌표 누락; 실제 위치/주소 일치는 판정하지 않음.")
            for pos in positions:
                record("GEO-03", pos, COORDINATE_COLUMNS, "좌표 누락", category)

    for column in TIME_COLUMNS:
        if unavailable("TIME-01", [column], "invalid_format"):
            unavailable("TIME-02", [column], "midnight_frequency")
            continue
        present = [pos for pos, kind in enumerate(missing[column]) if kind is None]
        review = [pos for pos in present if values[column][pos] == "24:00"]
        invalid = [pos for pos in present if not (
            isinstance(values[column][pos], str) and
            (TIME_PATTERN.fullmatch(values[column][pos]) or values[column][pos] == "24:00"))]
        for category, positions, result, reason in (
            ("invalid_format", invalid, "형식 오류", "00:00~23:59의 HH:MM이 아님"),
            ("end_of_day_review", review, "검토 후보", "24:00은 별도 검토; 오류/운영 여부로 단정하지 않음"),
        ):
            summarize("TIME-01", [column], category, positions, len(present),
                      "분모: 비결측 값. " + reason)
            for pos in positions:
                record("TIME-01", pos, [column], result, reason)
        midnight = [pos for pos in present if values[column][pos] == "00:00"]
        summarize("TIME-02", [column], "midnight_frequency", midnight, len(present),
                  "분모: 비결측 값. 00:00은 형식상 정상이며 빈도만 보고.", informational=True)

    date_column = "데이터기준일자"
    date_observations = {"status": "검사 불가", "oldest": None, "latest": None, "year_counts": {}}
    if unavailable("DATE-01", [date_column], "invalid_date"):
        unavailable("DATE-02", [date_column], "future_date")
    else:
        present = [pos for pos, kind in enumerate(missing[date_column]) if kind is None]
        invalid, parsed = [], {}
        for pos in present:
            value = values[date_column][pos]
            if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
                invalid.append(pos)
                record("DATE-01", pos, [date_column], "형식 오류", "YYYY-MM-DD 자릿수/구분자 불일치")
                continue
            try:
                parsed[pos] = date.fromisoformat(value)
            except ValueError:
                invalid.append(pos)
                record("DATE-01", pos, [date_column], "날짜 오류", "실제 달력에 없는 날짜")
        summarize("DATE-01", [date_column], "invalid_date", invalid, len(present),
                  "분모: 비결측 값. ASCII YYYY-MM-DD 형태 및 달력 유효성.")
        future = [pos for pos, value in parsed.items() if value > reference_date]
        summarize("DATE-02", [date_column], "future_date", future, len(parsed),
                  f"분모: 유효하게 파싱된 날짜. 기준일 {reference_date.isoformat()} 이후는 검토 후보.")
        for pos in future:
            record("DATE-02", pos, [date_column], "검토 후보", "실행 기준일 이후 날짜")
        years = {}
        for value in parsed.values():
            year = str(value.year)
            years[year] = years.get(year, 0) + 1
        oldest = min(parsed.values()) if parsed else None
        latest = max(parsed.values()) if parsed else None
        date_observations = {
            "status": "관측" if parsed else "검사 대상 없음",
            "oldest": oldest.isoformat() if oldest else None,
            "latest": latest.isoformat() if latest else None,
            "year_counts": dict(sorted(years.items())),
            "oldest_date_rows": sum(value == oldest for value in parsed.values()),
            "valid_date_rows": len(parsed),
        }

    missing_rows = {pos for column in missing for pos, kind in enumerate(missing[column])
                    if kind is not None}
    return {
        "report_version": 1,
        "reference_date": reference_date.isoformat(),
        "dataset": {"row_count": row_count, "column_count": len(dataframe.columns),
                    "columns": list(dataframe.columns)},
        "totals": {
            "rows_with_any_missing": len(missing_rows),
            "missing_cells": sum(kind is not None for kinds in missing.values() for kind in kinds),
            "unique_affected_rows": len(affected_positions),
            "detail_record_count": len(details),
        },
        "summaries": summaries, "details": details,
        "observations": {"dates": date_observations},
        "limitations": ["검출과 후보 보고만 수행; 자동 정제/삭제/보정 없음",
                        "중복 후보를 동일 시설로 확정하지 않음",
                        "주소와 실제 좌표 일치 및 실제 운영 여부는 판정하지 않음",
                        "오래된 날짜에 임의의 오류 기준을 적용하지 않음",
                        "문자 NA와 00:00을 결측값으로 취급하지 않음"],
    }
