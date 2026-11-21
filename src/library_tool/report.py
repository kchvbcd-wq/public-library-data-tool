"""진단 결과의 콘솔 요약과 UTF-8 JSON 저장. 데이터 재계산은 하지 않는다."""

import json
from pathlib import Path


def _count_summary(items: list[dict], unit: str = "건") -> str:
    """콘솔에서만 건수를 묶으며 검사 불가·분모 0을 정상 0건과 구분한다."""
    inspected = [item for item in items if item["denominator"]]
    unavailable = [item for item in items if item["status"] == "검사 불가"]
    empty = [item for item in items if item["status"] == "검사 대상 없음"]
    if inspected:
        text = f"{sum(item['count'] for item in inspected):,}{unit}"
    elif unavailable or not items:
        text = "검사 불가"
    else:
        text = "검사 대상 없음 (분모 0)"
    if inspected and unavailable:
        columns = dict.fromkeys(column for item in unavailable for column in item["columns"])
        text += f" (일부 검사 불가: {', '.join(columns)})"
    if inspected and empty:
        columns = dict.fromkeys(column for item in empty for column in item["columns"])
        text += f" (일부 검사 대상 없음: {', '.join(columns)})"
    return text


def format_compact_quality_summary(report: dict) -> str:
    """기존 진단 결과만 읽어 핵심 항목을 표시한다. JSON/규칙 수치를 바꾸지 않는다.

    여러 컬럼을 묶은 오류/결측 건수는 행 수가 아닌 값 수이다. 기본 화면에도
    누락 컬럼과 검사 대상 없음 상태를 남기며 원본 표나 보고서를 수정하지 않는다.
    """
    dataset, totals = report["dataset"], report["totals"]
    summaries = report["summaries"]

    def select(rule, category=None):
        """이미 계산된 요약을 규칙과 분류로 선택한다."""
        return [item for item in summaries if item["rule_id"] == rule
                and (category is None or item["category"] == category
                     or item["status"] == "검사 불가")]

    lines = [
        f"데이터 품질 진단: {dataset['row_count']:,}행 / {dataset['column_count']}컬럼",
        f"실행 기준일: {report['reference_date']}",
        f"하나 이상 결측인 행: {totals['rows_with_any_missing']:,}",
        f"결측 셀 수: {totals['missing_cells']:,}",
        f"문제/검토 후보 고유 행 수: {totals['unique_affected_rows']:,} (규칙 간 중복 제거, 00:00 빈도 제외)",
    ]
    missing_schema = [item["columns"][0] for item in select("SCHEMA-01")
                      if item["status"] == "검사 불가"]
    lines.append("필요 컬럼: " + ("검사 불가 - 누락 " + ", ".join(missing_schema)
                                  if missing_schema else "모두 존재"))
    lines.append("핵심 필수값 누락: " + _count_summary(select("CORE-01"), "개 값"))

    missing_columns = {}
    for item in select("MISS-01"):
        column = item["columns"][0]
        missing_columns[column] = missing_columns.get(column, 0) + item["count"]
    nonzero_missing = sorted(((column, count) for column, count in missing_columns.items() if count),
                             key=lambda pair: -pair[1])
    if nonzero_missing:
        lines.append("결측 컬럼 (빈 문자열·공백·pandas 결측 합계, 분모: 전체 행):")
        for column, count in nonzero_missing:
            ratio = count / dataset["row_count"] * 100
            lines.append(f"  {column}: {count:,}건 ({ratio:.4f}%)")
    else:
        lines.append("결측 컬럼: " + _count_summary(select("MISS-01")))

    for category, label in (("both_missing", "양쪽 누락"), ("one_missing", "한쪽 누락")):
        lines.append(f"좌표 {label}: " + _count_summary(select("GEO-03", category), "행"))
    for rule, label in (("DUP-01", "완전 중복"), ("DUP-02", "이름+주소 중복 후보")):
        items = select(rule)
        item = items[0]
        if item["status"] in ("검사 불가", "검사 대상 없음"):
            line = f"{label}: " + _count_summary(items)
            if rule == "DUP-02" and item["metrics"]:
                line += f" / 누락 키 제외 {item['metrics']['excluded_missing_key_rows']:,}행"
            lines.append(line)
        else:
            metrics = item["metrics"]
            line = (f"{label}: {metrics['group_count']:,}그룹 / "
                    f"참여 {metrics['participating_rows']:,}행")
            if rule == "DUP-02":
                line += (f" / 추가 {metrics['extra_rows']:,}행"
                         f" / 누락 키 제외 {metrics['excluded_missing_key_rows']:,}행")
            lines.append(line)
    whitespace = select("TEXT-01")
    found = [item for item in whitespace if item["count"]]
    lines.append("앞뒤 공백: " + (", ".join(
        f"{', '.join(item['columns'])} {item['count']:,}건" for item in found)
        if found else _count_summary(whitespace)))

    lines.extend([
        "좌표 값 오류 - 숫자 변환: " + _count_summary(select("GEO-01", "invalid_number"))
        + ", 비유한 값: " + _count_summary(select("GEO-01", "nonfinite_number"))
        + ", 범위 이탈: " + _count_summary(select("GEO-02")),
        "운영시간 값 - 형식 오류: " + _count_summary(select("TIME-01", "invalid_format"))
        + ", 24:00 검토 후보: " + _count_summary(select("TIME-01", "end_of_day_review")),
        "00:00 값 빈도: " + _count_summary(select("TIME-02"), "개 값")
        + " (정보용; 휴관·24시간 운영 판단 안 함)",
        "날짜 - 형식/달력 오류: " + _count_summary(select("DATE-01"))
        + ", 미래 날짜 검토 후보: " + _count_summary(select("DATE-02")),
    ])
    dates = report["observations"]["dates"]
    lines.append(f"기준일자 관측: {dates['oldest'] or '-'} ~ {dates['latest'] or '-'} ({dates['status']})")
    lines.append(f"규칙별 요약: {len(summaries):,}개 / 상세 기록: {totals['detail_record_count']:,}건")
    lines.append("주의: 후보는 실제 오류/동일 시설 확정이 아니며 원본을 자동 수정하지 않습니다.")
    lines.append("전체 규칙·분모·사유: python main.py --quality --verbose")
    lines.append("개별 행·원본 값: python main.py --quality --report results/quality.json")
    return "\n".join(lines)


def format_quality_summary(report: dict) -> str:
    """보고서 수치를 그대로 출력하고 분모 0/검사 불가를 '-'로 표시한다."""
    dataset, totals = report["dataset"], report["totals"]
    lines = [
        f"데이터 품질 진단: {dataset['row_count']:,}행 / {dataset['column_count']}컬럼",
        f"실행 기준일: {report['reference_date']}",
        f"하나 이상 결측인 행: {totals['rows_with_any_missing']:,}",
        f"결측 셀 수: {totals['missing_cells']:,}",
        f"문제/검토 후보 고유 행 수: {totals['unique_affected_rows']:,} (규칙 간 중복 제거, 00:00 빈도 제외)",
    ]
    for summary in report["summaries"]:
        ratio = summary["ratio_percent"]
        ratio_text = "-" if ratio is None else f"{ratio:.4f}%"
        count = "-" if summary["count"] is None else str(summary["count"])
        denominator = "-" if summary["denominator"] is None else str(summary["denominator"])
        columns = ", ".join(summary["columns"]) or "(컬럼 없음)"
        lines.append(
            f"{summary['rule_id']} | {columns} | {summary['category']} | {summary['status']} | "
            f"검사 {summary['inspected_rows']}행 | 건수 {count} / 분모 {denominator} | {ratio_text}"
        )
        lines.append(f"  사유: {summary['reason']}")
        if summary["metrics"]:
            lines.append("  지표: " + json.dumps(summary["metrics"], ensure_ascii=False))
    dates = report["observations"]["dates"]
    lines.append(f"기준일자 관측: {dates['oldest'] or '-'} ~ {dates['latest'] or '-'} ({dates['status']})")
    lines.append("연도별 유효 날짜: " + json.dumps(dates["year_counts"], ensure_ascii=False))
    lines.append(f"상세 기록: {totals['detail_record_count']:,}건 (동일 행의 여러 규칙 기록 포함)")
    lines.extend(f"한계: {limitation}" for limitation in report["limitations"])
    return "\n".join(lines)


def write_json_report(report: dict, file_path: str | Path = "results/quality.json") -> Path:
    """보고서만 UTF-8 JSON으로 저장한다. CLI는 프로젝트 results/ 경로를 강제한다.

    allow_nan=False로 비표준 JSON의 NaN/Infinity 저장을 막는다. 직렬화를 먼저
    완료하여 변환 오류 때문에 기존 보고서를 비우는 일을 피한다.
    """
    path = Path(file_path)
    if path.suffix.lower() != ".json":
        raise ValueError("리포트 파일 확장자는 .json이어야 합니다.")
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")
    return path
