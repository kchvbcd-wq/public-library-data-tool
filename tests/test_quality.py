"""실제 원본을 사용하지 않는 합성 데이터 품질 규칙 테스트."""

from datetime import date, datetime

import pandas as pd
import pytest

from src.library_tool.quality import CORE_COLUMNS, TIME_COLUMNS, diagnose_quality


REFERENCE_DATE = date(2026, 10, 12)


def synthetic_frame(rows=1):
    """모든 진단 컬럼이 유효한 합성 표를 만든다."""
    values = {
        "도서관명": [f"합성도서관{i}" for i in range(rows)],
        "시도명": ["가상시도"] * rows,
        "시군구명": ["가상구"] * rows,
        "소재지도로명주소": [f"합성주소{i}" for i in range(rows)],
        "위도": ["37.5"] * rows, "경도": ["127.0"] * rows,
        "데이터기준일자": ["2026-10-12"] * rows,
        **{column: ["09:00"] * rows for column in TIME_COLUMNS},
    }
    return pd.DataFrame(values)


def summary(report, rule, category, column=None):
    """규칙·분류·컬럼으로 요약 레코드 하나를 선택한다."""
    matches = [item for item in report["summaries"]
               if item["rule_id"] == rule and item["category"] == category
               and (column is None or item["columns"] == [column])]
    assert len(matches) == 1
    return matches[0]


def diagnose(frame):
    """실행 기준일을 고정하여 미래 날짜 검사를 재현한다."""
    return diagnose_quality(frame, reference_date=REFERENCE_DATE)


def test_missing_kinds_literal_na_and_unique_row_totals():
    frame = synthetic_frame(8)
    frame["검사용"] = pd.Series(["", " \t", "\u3000", None, pd.NA, float("nan"), "NA", "00:00"], dtype=object)
    report = diagnose(frame)
    for kind, count in (("empty_string", 1), ("whitespace_only", 2), ("pandas_missing", 3)):
        item = summary(report, "MISS-01", kind, "검사용")
        assert (item["count"], item["denominator"], item["ratio_percent"]) == (count, 8, count / 8 * 100)
    assert report["totals"]["rows_with_any_missing"] == 6
    assert report["totals"]["missing_cells"] == 6
    assert report["totals"]["unique_affected_rows"] == 6
    assert not any(item["data_row"] in (7, 8) for item in report["details"])
    pandas_details = [item for item in report["details"] if item["reason"] == "pandas_missing"]
    assert {item["raw_value_types"]["검사용"] for item in pandas_details} == {"NoneType", "NAType", "float"}


@pytest.mark.parametrize("column", CORE_COLUMNS)
def test_core_columns_detect_missing_values(column):
    frame = synthetic_frame(2)
    frame.loc[0, column] = ""
    report = diagnose(frame)
    assert summary(report, "CORE-01", "required_value_missing", column)["count"] == 1
    assert report["totals"]["unique_affected_rows"] == 1


def test_full_duplicate_groups_and_extra_rows_are_distinct():
    frame = pd.concat([synthetic_frame(), synthetic_frame(), synthetic_frame()], ignore_index=True)
    report = diagnose(frame)
    for rule, category in (("DUP-01", "duplicate_rows"), ("DUP-02", "duplicate_candidates")):
        item = summary(report, rule, category)
        assert item["count"] == 3
        assert item["metrics"] == {"group_count": 1, "participating_rows": 3,
                                   "extra_rows": 2, "excluded_missing_key_rows": 0}
    assert report["totals"]["unique_affected_rows"] == 3


def test_composite_key_strips_whitespace_excludes_missing_and_keeps_raw_indexes():
    frame = synthetic_frame(7)
    frame["도서관명"] = [" 합성A", "합성A\u3000", "합성B", "합성B", "", "\u3000", "NA"]
    frame["소재지도로명주소"] = ["주소A", " 주소A ", "주소B", "주소B", "같은주소", "같은주소", "주소C"]
    frame["위도"] = ["30", "31", "32", "33", "34", "35", "36"]
    frame.index = [90, 90, 30, 40, 50, 60, 70]
    report = diagnose(frame)
    item = summary(report, "DUP-02", "duplicate_candidates")
    assert (item["count"], item["denominator"], item["ratio_percent"]) == (4, 5, 80)
    assert item["metrics"] == {"group_count": 2, "participating_rows": 4,
                               "extra_rows": 2, "excluded_missing_key_rows": 2}
    assert summary(report, "DUP-01", "duplicate_rows")["count"] == 0
    records = [item for item in report["details"] if item["rule_id"] == "DUP-02"]
    assert [item["data_row"] for item in records] == [1, 2, 3, 4]
    assert [item["dataframe_index"] for item in records] == [90, 90, 30, 40]
    assert records[0]["raw_values"]["도서관명"] == " 합성A"
    assert records[0]["duplicate_group_id"] == records[1]["duplicate_group_id"]
    assert records[1]["duplicate_group_id"] != records[2]["duplicate_group_id"]


def test_full_duplicates_include_missing_values():
    frame = pd.DataFrame({"도서관명": ["합성", "합성"], "기타": [None, None]})
    assert summary(diagnose(frame), "DUP-01", "duplicate_rows")["count"] == 2


def test_unicode_and_regular_outer_whitespace():
    frame = synthetic_frame(3)
    frame["시군구명"] = ["노원구\u3000", " 가상구\t", "내부 공백"]
    report = diagnose(frame)
    assert summary(report, "TEXT-01", "outer_whitespace", "시군구명")["count"] == 2
    detail = next(item for item in report["details"] if item["rule_id"] == "TEXT-01")
    assert detail["raw_value_reprs"]["시군구명"] == repr("노원구\u3000")


def test_coordinate_missing_numbers_finiteness_and_denominators():
    frame = synthetic_frame(9)
    frame["위도"] = ["", "", "37", "bad", "inf", "NaN", "91", "-90", "90"]
    frame["경도"] = ["", "127", "", "181", "-181", "180", "-180", "0", "0"]
    report = diagnose(frame)
    assert summary(report, "GEO-03", "both_missing")["count"] == 1
    assert summary(report, "GEO-03", "one_missing")["count"] == 2
    invalid = summary(report, "GEO-01", "invalid_number", "위도")
    assert (invalid["count"], invalid["denominator"]) == (1, 7)
    assert summary(report, "GEO-01", "nonfinite_number", "위도")["count"] == 2
    outside = summary(report, "GEO-02", "outside_global_range", "위도")
    assert (outside["count"], outside["denominator"], outside["ratio_percent"]) == (1, 4, 25)
    assert summary(report, "GEO-02", "outside_global_range", "경도")["count"] == 2


@pytest.mark.parametrize("value,category", [(float("inf"), "nonfinite_number"),
                                          (float("-inf"), "nonfinite_number"),
                                          ("NA", "invalid_number")])
def test_nonmissing_coordinate_errors(value, category):
    frame = synthetic_frame()
    frame["위도"] = pd.Series([value], dtype=object)
    assert summary(diagnose(frame), "GEO-01", category, "위도")["count"] == 1


@pytest.mark.parametrize("value,invalid,review,midnight", [
    ("00:00", 0, 0, 1), ("23:59", 0, 0, 0), ("24:00", 0, 1, 0),
    ("25:00", 1, 0, 0), ("09:60", 1, 0, 0), ("9:00", 1, 0, 0),
    ("09:0", 1, 0, 0), (" 09:00", 1, 0, 0), ("０９:００", 1, 0, 0),
])
def test_time_format_review_and_midnight(value, invalid, review, midnight):
    frame = synthetic_frame()
    for column in TIME_COLUMNS:
        frame[column] = value
    report = diagnose(frame)
    for column in TIME_COLUMNS:
        assert summary(report, "TIME-01", "invalid_format", column)["count"] == invalid
        assert summary(report, "TIME-01", "end_of_day_review", column)["count"] == review
        assert summary(report, "TIME-02", "midnight_frequency", column)["count"] == midnight
    if value == "00:00":
        assert report["totals"]["unique_affected_rows"] == 0
        assert report["details"] == []


def test_missing_times_are_separate_from_format_errors():
    frame = synthetic_frame(3)
    frame[TIME_COLUMNS[0]] = ["", "24:00", "09:00"]
    report = diagnose(frame)
    item = summary(report, "TIME-01", "end_of_day_review", TIME_COLUMNS[0])
    assert (item["count"], item["denominator"], item["ratio_percent"]) == (1, 2, 50)
    assert summary(report, "TIME-01", "invalid_format", TIME_COLUMNS[0])["count"] == 0


def test_date_shape_leap_day_future_range_and_year_counts():
    frame = synthetic_frame(10)
    frame["데이터기준일자"] = ["2024-02-29", "2023-02-29", "2026-2-01", "2026/10/12", "2026-10-13",
                            "2026-10-12", "2018-05-01", "", "2026-04-31", "0000-01-01"]
    report = diagnose(frame)
    assert summary(report, "DATE-01", "invalid_date")["count"] == 5
    future = summary(report, "DATE-02", "future_date")
    assert (future["count"], future["denominator"], future["ratio_percent"]) == (1, 4, 25)
    observations = report["observations"]["dates"]
    assert observations["oldest"] == "2018-05-01"
    assert observations["latest"] == "2026-10-13"
    assert observations["year_counts"] == {"2018": 1, "2024": 1, "2026": 2}
    assert observations["oldest_date_rows"] == 1
    assert not any(item["data_row"] in (1, 6, 7) for item in report["details"])


def test_reference_date_changes_only_future_classification():
    frame = synthetic_frame()
    first = diagnose_quality(frame, reference_date=date(2026, 10, 11))
    second = diagnose_quality(frame, reference_date=date(2026, 10, 12))
    assert summary(first, "DATE-02", "future_date")["count"] == 1
    assert summary(second, "DATE-02", "future_date")["count"] == 0


def test_missing_columns_are_unavailable_not_successful_zero():
    report = diagnose(pd.DataFrame({"도서관명": ["합성"]}))
    for rule, category in (("DUP-02", "duplicate_candidates"), ("GEO-03", "coordinate_missing"),
                           ("DATE-01", "invalid_date")):
        item = summary(report, rule, category)
        assert (item["status"], item["count"], item["denominator"], item["ratio_percent"]) == (
            "검사 불가", None, None, None)
        assert item["inspected_rows"] == 0
    assert summary(report, "SCHEMA-01", "column_presence", "도서관명")["status"] == "정상"
    assert summary(report, "SCHEMA-01", "column_presence", "위도")["status"] == "검사 불가"


def test_empty_dataframe_with_schema_has_no_division_by_zero():
    report = diagnose(synthetic_frame(0))
    assert report["dataset"]["row_count"] == 0
    assert all(item["status"] == "검사 대상 없음" for item in report["summaries"])
    assert all(item["count"] == 0 and item["ratio_percent"] is None for item in report["summaries"])
    assert report["details"] == []


def test_empty_dataframe_without_columns_is_unavailable():
    report = diagnose(pd.DataFrame())
    assert summary(report, "DUP-01", "duplicate_rows")["status"] == "검사 불가"
    assert report["totals"]["unique_affected_rows"] == 0


def test_diagnosis_preserves_frame_dtypes_order_and_multiindex():
    frame = synthetic_frame(2)
    frame["시군구명"] = ["가상구\u3000", ""]
    frame.index = pd.MultiIndex.from_tuples([("a", 9), ("a", 9)], names=["key", "n"])
    before = frame.copy(deep=True)
    report = diagnose(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert report["details"][0]["dataframe_index"] == ["a", 9]


@pytest.mark.parametrize("reference", ["2026-10-12", datetime(2026, 10, 12)])
def test_invalid_reference_date_type(reference):
    with pytest.raises(TypeError, match="datetime.date"):
        diagnose_quality(synthetic_frame(), reference_date=reference)


def test_invalid_dataframe_and_ambiguous_column_names():
    with pytest.raises(TypeError, match="DataFrame"):
        diagnose_quality([])
    with pytest.raises(ValueError, match="컬럼명"):
        diagnose_quality(pd.DataFrame([[1, 2]], columns=["위도", "위도"]))
