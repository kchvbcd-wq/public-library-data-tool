"""콘솔/JSON 수치 일치와 진단 CLI 회귀 테스트. 합성 데이터만 사용한다."""

from copy import deepcopy
from datetime import date
import json

import pandas as pd
import pytest

import main
from src.library_tool.quality import diagnose_quality
from src.library_tool.report import format_quality_summary, write_json_report


def synthetic_report():
    """비표준 JSON 값과 한글을 포함하는 합성 표 및 결과를 반환한다."""
    frame = pd.DataFrame({"도서관명": ["합성한글", "합성한글"],
                          "소재지도로명주소": ["주소\u3000", "주소"],
                          "위도": pd.Series([float("inf"), pd.NA], dtype=object),
                          "경도": ["127", ""]}, index=[0, 1])
    return frame, diagnose_quality(frame, reference_date=date(2026, 10, 12))


def test_console_and_utf8_json_numbers_match_without_mutation(tmp_path):
    frame, report = synthetic_report()
    before_frame, before_report = frame.copy(deep=True), deepcopy(report)
    output = format_quality_summary(report)
    path = write_json_report(report, tmp_path / "nested" / "합성.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == report
    assert "합성한글" in path.read_text(encoding="utf-8")
    assert "Infinity" not in path.read_text(encoding="utf-8")
    for item in stored["summaries"]:
        columns = ", ".join(item["columns"]) or "(컬럼 없음)"
        line = next(line for line in output.splitlines()
                    if line.startswith(f"{item['rule_id']} | {columns} | {item['category']} |"))
        count = "-" if item["count"] is None else str(item["count"])
        denominator = "-" if item["denominator"] is None else str(item["denominator"])
        assert f"건수 {count} / 분모 {denominator}" in line
        assert ("-" if item["ratio_percent"] is None else f"{item['ratio_percent']:.4f}%") in line
    assert report == before_report
    pd.testing.assert_frame_equal(frame, before_frame)
    records = [item for item in stored["details"] if item["rule_id"] == "DUP-02"]
    assert [item["data_row"] for item in records] == [1, 2]
    assert records[0]["raw_values"]["소재지도로명주소"] == "주소\u3000"
    assert records[0]["duplicate_group_id"] == records[1]["duplicate_group_id"]


def test_unavailable_and_empty_denominators_render_as_dash():
    report = diagnose_quality(pd.DataFrame({"도서관명": []}))
    output = format_quality_summary(report)
    assert "검사 대상 없음" in output
    assert "검사 불가" in output
    assert "분모 -" in output
    assert "nan%" not in output


def test_json_serialization_failure_does_not_truncate_existing_report(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("previous", encoding="utf-8")
    with pytest.raises(ValueError):
        write_json_report({"invalid": float("nan")}, path)
    assert path.read_text(encoding="utf-8") == "previous"


def test_report_requires_json_suffix(tmp_path):
    with pytest.raises(ValueError, match=".json"):
        write_json_report({}, tmp_path / "report.csv")


def test_quality_cli_loads_cp949_and_saves_project_relative_json(tmp_path, monkeypatch, capsys):
    path = tmp_path / "합성.csv"
    pd.DataFrame({"도서관명": ["합성도서관"], "시군구명": ["가상구 "]}).to_csv(
        path, encoding="cp949", index=False)
    before = path.read_bytes()
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main, "CSV_PATH", path)
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)
    assert main.main(["--quality", "--report", "results/quality.json"]) == 0
    output = capsys.readouterr().out
    stored = json.loads((tmp_path / "results" / "quality.json").read_text(encoding="utf-8"))
    assert "데이터 품질 진단: 1행 / 2컬럼" in output
    assert stored["dataset"]["row_count"] == 1
    assert stored["totals"]["unique_affected_rows"] == 1
    assert stored["details"][0]["raw_values"]["시군구명"] == "가상구 "
    assert "JSON 리포트:" in output
    assert path.read_bytes() == before


def test_quality_cli_without_report_does_not_create_results(tmp_path, monkeypatch, capsys):
    frame = pd.DataFrame({"도서관명": ["합성"]})
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main, "load_library_csv", lambda path: frame)
    assert main.main(["--quality"]) == 0
    assert "데이터 품질 진단" in capsys.readouterr().out
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("args", [["--report", "results/x.json"],
                                  ["--quality", "--name", "합성"],
                                  ["--quality", "--sido", "가상시도"],
                                  ["--quality", "--sigungu", "가상구"]])
def test_conflicting_cli_options_fail_before_loading(args, monkeypatch, capsys):
    def fail_if_loaded(path):
        """옵션 오류 뒤 로더에 진입하지 않는 것을 확인한다."""
        pytest.fail("옵션 오류 시 CSV를 읽으면 안 됩니다.")
    monkeypatch.setattr(main, "load_library_csv", fail_if_loaded)
    with pytest.raises(SystemExit) as exc:
        main.main(args)
    assert exc.value.code == 2
    assert "--quality" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["README.md", "data/raw/original.json", "results/../main.json",
                                  "../outside.json", "results/output.csv", "results"])
def test_cli_rejects_reports_outside_results_or_wrong_suffix(path, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc:
        main.main(["--quality", "--report", path])
    assert exc.value.code == 2
    assert "results/" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_loader_required_name_error_remains_and_is_explained(tmp_path, monkeypatch, capsys):
    path = tmp_path / "missing_name.csv"
    pd.DataFrame({"시도명": ["가상시도"]}).to_csv(path, encoding="cp949", index=False)
    monkeypatch.setattr(main, "CSV_PATH", path)
    assert main.main(["--quality"]) == 1
    error = capsys.readouterr().err
    assert "필수 컬럼" in error and "도서관명" in error and "기존 로더" in error


def test_report_write_failure_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(main, "load_library_csv", lambda path: pd.DataFrame({"도서관명": ["합성"]}))
    def fail_write(report, path):
        """저장 권한 오류를 합성한다."""
        raise PermissionError("합성 저장 권한 오류")
    monkeypatch.setattr(main, "write_json_report", fail_write)
    assert main.main(["--quality", "--report", "results/quality.json"]) == 1
    assert "저장 권한 오류" in capsys.readouterr().err


def test_existing_structure_and_search_modes_remain(monkeypatch, capsys):
    frame = pd.DataFrame({"도서관명": ["합성Alpha", "합성Beta"],
                          "시도명": ["가상시도"] * 2, "시군구명": ["가상구"] * 2})
    before = frame.copy(deep=True)
    monkeypatch.setattr(main, "load_library_csv", lambda path: frame)
    assert main.main([]) == 0
    assert "전체 데이터 행 수: 2" in capsys.readouterr().out
    assert main.main(["--name", "alpha", "--sido", "가상시도", "--sigungu", "가상구"]) == 0
    assert "검색 결과: 1건" in capsys.readouterr().out
    assert main.main(["--name", "없는합성"]) == 0
    assert "검색 결과: 0건" in capsys.readouterr().out
    pd.testing.assert_frame_equal(frame, before)


def complete_console_frame():
    """모든 규칙을 검사할 수 있고 중복·공백·결측 후보가 있는 합성 표."""
    from src.library_tool.quality import TIME_COLUMNS

    return pd.DataFrame({
        "도서관명": ["합성한글", "합성한글"], "시도명": ["가상시도"] * 2,
        "시군구명": ["가상구\u3000", "가상구"], "소재지도로명주소": ["주소"] * 2,
        "위도": ["", "37"], "경도": ["", "127"],
        "데이터기준일자": ["2026-10-12"] * 2,
        **{column: ["00:00", "09:00"] for column in TIME_COLUMNS},
    })


def test_default_quality_cli_is_compact_and_shows_key_results(monkeypatch, capsys):
    frame = complete_console_frame()
    monkeypatch.setattr(main, "load_library_csv", lambda path: frame)
    assert main.main(["--quality"]) == 0
    output = capsys.readouterr().out
    assert 20 <= len(output.splitlines()) <= 40
    assert "위도: 1건 (50.0000%)" in output
    assert "좌표 양쪽 누락: 1행" in output
    assert "완전 중복: 0그룹 / 참여 0행" in output
    assert "이름+주소 중복 후보: 1그룹 / 참여 2행 / 추가 1행" in output
    assert "앞뒤 공백: 시군구명 1건" in output
    assert "좌표 값 오류 - 숫자 변환: 0건, 비유한 값: 0건, 범위 이탈: 0건" in output
    assert "--verbose" in output and "results/quality.json" in output
    assert "MISS-01 |" not in output


def test_verbose_quality_cli_exactly_reuses_existing_full_output(monkeypatch, capsys):
    frame = complete_console_frame()
    report = diagnose_quality(frame, reference_date=date(2026, 10, 12))
    monkeypatch.setattr(main, "load_library_csv", lambda path: frame)
    monkeypatch.setattr(main, "diagnose_quality", lambda dataframe: report)
    assert main.main(["--quality", "--verbose"]) == 0
    output = capsys.readouterr().out
    assert output == f"CSV 파일: {main.CSV_PATH}\n" + format_quality_summary(report) + "\n"
    rule_lines = [line for line in output.splitlines() if " | " in line]
    assert len(rule_lines) == len(report["summaries"])


@pytest.mark.parametrize("args", [
    ["--verbose"], ["--verbose", "--name", "합성"],
    ["--verbose", "--sido", "가상시도"], ["--verbose", "--sigungu", "가상구"],
    ["--quality", "--verbose", "--name", "합성"],
    ["--quality", "--verbose", "--sido", "가상시도"],
    ["--quality", "--verbose", "--sigungu", "가상구"],
])
def test_verbose_requires_quality_and_rejects_search(args, monkeypatch, capsys):
    def fail_if_loaded(path):
        """사용법 오류에서는 CSV 로딩이 실행되지 않아야 한다."""
        pytest.fail("옵션 충돌 시 진단/로딩 금지")

    monkeypatch.setattr(main, "load_library_csv", fail_if_loaded)
    with pytest.raises(SystemExit) as exc:
        main.main(args)
    assert exc.value.code == 2
    assert "--quality" in capsys.readouterr().err


def test_modes_preserve_report_dataframe_and_identical_json(tmp_path, monkeypatch, capsys):
    from src.library_tool.report import format_compact_quality_summary

    frame = complete_console_frame()
    before_frame = frame.copy(deep=True)
    report = diagnose_quality(frame, reference_date=date(2026, 10, 12))
    before_report = deepcopy(report)
    calls = []

    def unchanged_analysis(dataframe):
        """모드와 관계없이 같은 분석 결과를 표시·저장에 전달한다."""
        calls.append(dataframe)
        return report

    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main, "load_library_csv", lambda path: frame)
    monkeypatch.setattr(main, "diagnose_quality", unchanged_analysis)
    assert main.main(["--quality", "--report", "results/basic.json"]) == 0
    basic_output = capsys.readouterr().out
    assert main.main(["--quality", "--verbose", "--report", "results/verbose.json"]) == 0
    verbose_output = capsys.readouterr().out
    basic = (tmp_path / "results/basic.json").read_bytes()
    verbose = (tmp_path / "results/verbose.json").read_bytes()
    assert basic == verbose
    assert json.loads(basic) == before_report
    assert "하나 이상 결측인 행: 1" in basic_output
    assert "하나 이상 결측인 행: 1" in verbose_output
    assert "문제/검토 후보 고유 행 수: 2" in basic_output
    assert "문제/검토 후보 고유 행 수: 2" in verbose_output
    assert "JSON 리포트:" in verbose_output
    assert len(calls) == 2 and all(value is frame for value in calls)
    format_compact_quality_summary(report)
    assert report == before_report
    pd.testing.assert_frame_equal(frame, before_frame)


def test_compact_valid_zero_is_distinct_from_unavailable_and_empty():
    from src.library_tool.report import format_compact_quality_summary

    frame = complete_console_frame()
    frame["위도"], frame["경도"] = "37", "127"
    valid = format_compact_quality_summary(diagnose_quality(frame))
    unavailable = format_compact_quality_summary(diagnose_quality(frame.drop(columns=["위도", "경도"])))
    empty = format_compact_quality_summary(diagnose_quality(frame.iloc[:0]))
    assert "좌표 양쪽 누락: 0행" in valid
    assert "좌표 양쪽 누락: 검사 불가" in unavailable
    assert "좌표 양쪽 누락: 검사 대상 없음 (분모 0)" in empty
    assert "숫자 변환: 검사 불가" in unavailable
    assert "숫자 변환: 검사 대상 없음 (분모 0)" in empty
    assert "좌표 양쪽 누락: 0행" not in unavailable + empty


def test_compact_partial_coordinate_inspection_is_explicit():
    from src.library_tool.report import format_compact_quality_summary

    frame = complete_console_frame().drop(columns=["경도"])
    output = format_compact_quality_summary(diagnose_quality(frame))
    assert "숫자 변환: 0건 (일부 검사 불가: 경도)" in output
    assert "비유한 값: 0건 (일부 검사 불가: 경도)" in output
    assert "좌표 양쪽 누락: 검사 불가" in output


def test_compact_errors_count_values_not_distinct_rows():
    from src.library_tool.report import format_compact_quality_summary

    frame = complete_console_frame().iloc[:1].copy()
    frame["위도"], frame["경도"] = "bad", "bad"
    frame["평일운영시작시각"], frame["토요일운영시작시각"] = "25:00", "24:00"
    frame["데이터기준일자"] = "2023-02-29"
    report = diagnose_quality(frame)
    output = format_compact_quality_summary(report)
    assert "좌표 값 오류 - 숫자 변환: 2건" in output
    assert "운영시간 값 - 형식 오류: 1건, 24:00 검토 후보: 1건" in output
    assert "날짜 - 형식/달력 오류: 1건" in output
    assert "문제/검토 후보 고유 행 수: 1" in output


def test_compact_duplicate_without_valid_keys_retains_excluded_count():
    from src.library_tool.report import format_compact_quality_summary

    frame = complete_console_frame()
    frame["도서관명"] = ""
    output = format_compact_quality_summary(diagnose_quality(frame))
    assert "이름+주소 중복 후보: 검사 대상 없음 (분모 0) / 누락 키 제외 2행" in output


def test_search_and_structure_remain_after_verbose_option_added(monkeypatch, capsys):
    frame = complete_console_frame()
    before = frame.copy(deep=True)
    monkeypatch.setattr(main, "load_library_csv", lambda path: frame)
    assert main.main(["--name", "합성", "--sido", "가상시도", "--sigungu", "가상구"]) == 0
    assert "검색 결과: 2건" in capsys.readouterr().out
    assert main.main([]) == 0
    assert "전체 데이터 행 수: 2" in capsys.readouterr().out
    pd.testing.assert_frame_equal(frame, before)


def test_compact_console_labels_are_cp949_encodable():
    """Windows CP949 파이프에서 새 구분자로 인한 인코딩 오류를 방지한다."""
    from src.library_tool.report import format_compact_quality_summary

    frame = complete_console_frame()
    for candidate in (frame, frame.drop(columns=["경도"]), frame.iloc[:0]):
        output = format_compact_quality_summary(diagnose_quality(candidate))
        assert output.encode("cp949").decode("cp949") == output
