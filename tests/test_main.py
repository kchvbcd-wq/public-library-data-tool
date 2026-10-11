"""실제 원본 대신 합성 표로 CLI 출력과 오류 흐름을 검증한다."""

from pathlib import Path

import pandas as pd
import pytest

import main


def test_no_options_preserves_structure_output(monkeypatch, capsys):
    """옵션 없이 실행하면 기존 구조 조회를 유지한다."""
    dataframe = pd.DataFrame({"도서관명": ["합성도서관"], "시도명": ["가상시도"]})
    monkeypatch.setattr(main, "load_library_csv", lambda path: dataframe)
    assert main.main([]) == 0
    output = capsys.readouterr().out
    assert "전체 데이터 행 수: 1" in output
    assert "전체 컬럼 수: 2" in output
    assert "첫 번째 5개 행" in output
    assert "합성도서관" in output


def test_cli_search_displays_only_existing_columns(monkeypatch, capsys):
    """없는 주소나 운영시간을 만들지 않고 AND 검색 결과를 출력한다."""
    dataframe = pd.DataFrame(
        {"도서관명": ["합성Alpha", "합성Beta"], "시도명": ["가상시도", "가상시도"], "시군구명": ["가상구", "가상구"]}
    )
    monkeypatch.setattr(main, "load_library_csv", lambda path: dataframe)
    assert main.main(["--name", "alpha", "--sido", "가상시도", "--sigungu", "가상구"]) == 0
    output = capsys.readouterr().out
    assert "검색 결과: 1건" in output
    assert "합성Alpha" in output
    assert "합성Beta" not in output
    assert "소재지도로명주소" not in output
    assert "평일운영시작시각" not in output
    assert "주소:" not in output
    assert "평일:" not in output
    assert "토요일:" not in output


def test_cli_zero_matches_is_success(monkeypatch, capsys):
    """검색 0건은 정상 종료이며 결과가 없음을 알린다."""
    monkeypatch.setattr(main, "load_library_csv", lambda path: pd.DataFrame({"도서관명": ["합성도서관"]}))
    assert main.main(["--name", "존재하지않는합성검색어"]) == 0
    output = capsys.readouterr().out
    assert "검색 결과: 0건" in output
    assert "조건에 일치하는 도서관이 없습니다" in output


def test_cli_blank_query_returns_error(monkeypatch, capsys):
    """공백만 입력하면 전체 검색 대신 오류로 종료한다."""
    monkeypatch.setattr(main, "load_library_csv", lambda path: pd.DataFrame({"도서관명": ["합성도서관"]}))
    assert main.main(["--name", "   "]) == 1
    assert "공백만" in capsys.readouterr().err


def test_cli_missing_search_column_returns_error(monkeypatch, capsys):
    """검색 필터 컬럼이 없으면 누락된 이름을 표준 오류에 출력한다."""
    monkeypatch.setattr(main, "load_library_csv", lambda path: pd.DataFrame({"도서관명": ["합성도서관"]}))
    assert main.main(["--sido", "가상시도"]) == 1
    assert "시도명" in capsys.readouterr().err


def test_cli_uses_project_absolute_csv_path(monkeypatch, tmp_path):
    """작업 디렉터리를 바꿔도 로더에 프로젝트 기준 절대 경로를 전달한다."""
    paths = []

    def fake_loader(path):
        """로더에 전달된 경로를 기록하고 합성 표를 반환한다."""
        paths.append(path)
        return pd.DataFrame({"도서관명": ["합성도서관"]})

    monkeypatch.setattr(main, "load_library_csv", fake_loader)
    monkeypatch.chdir(tmp_path)
    assert main.main(["--name", "합성"]) == 0
    expected = Path(main.__file__).resolve().parent / "data" / "raw" / "전국도서관표준데이터.csv"
    assert paths == [expected]
    assert paths[0].is_absolute()


@pytest.fixture
def operating_libraries():
    """지역·주소와 네 운영시간을 가진 합성 도서관 두 곳."""
    return pd.DataFrame(
        {
            "도서관명": ["합성운영도서관A", "합성운영도서관B"],
            "시도명": ["가상시도", "가상시도"],
            "시군구명": ["가상구", "가상구"],
            "소재지도로명주소": ["합성주소 1", "합성주소 2"],
            "평일운영시작시각": ["09:00", "10:00"],
            "평일운영종료시각": ["18:00", "20:00"],
            "토요일운영시작시각": ["09:00", "10:30"],
            "토요일운영종료시각": ["17:00", "18:30"],
        },
        index=[10, 30],
    )


def test_cli_single_library_prints_four_times_by_day(monkeypatch, tmp_path, capsys, operating_libraries):
    """합성 CP949 CSV를 실제 로더로 읽고 단일 결과의 전체 표시를 검증한다."""
    path = tmp_path / "합성운영시간.csv"
    operating_libraries.to_csv(path, index=False, encoding="cp949")
    before = path.read_bytes()
    monkeypatch.setattr(main, "CSV_PATH", path)

    assert main.main(["--name", "도서관A", "--sido", "가상시도", "--sigungu", "가상구"]) == 0
    output = capsys.readouterr().out
    details = output.split("검색 결과: 1건\n", maxsplit=1)[1]
    assert details == (
        "\n[1] 합성운영도서관A\n"
        "지역: 가상시도 가상구\n"
        "주소: 합성주소 1\n"
        "평일: 09:00 ~ 18:00\n"
        "토요일: 09:00 ~ 17:00\n"
    )
    assert path.read_bytes() == before


def test_cli_multiple_libraries_are_numbered_and_separated(monkeypatch, capsys, operating_libraries):
    """원본 인덱스 대신 1부터 번호를 붙이고 각 도서관 사이에 빈 줄을 둔다."""
    monkeypatch.setattr(main, "load_library_csv", lambda path: operating_libraries)
    assert main.main(["--name", "합성운영"]) == 0
    output = capsys.readouterr().out
    assert "검색 결과: 2건" in output
    assert "\n[1] 합성운영도서관A\n" in output
    assert "토요일: 09:00 ~ 17:00\n\n[2] 합성운영도서관B\n" in output
    assert "평일: 10:00 ~ 20:00\n토요일: 10:30 ~ 18:30\n" in output
    assert "[3]" not in output


@pytest.mark.parametrize("missing_value", ["", None, pd.NA, float("nan")])
def test_cli_missing_times_are_displayed_without_mutation(monkeypatch, capsys, operating_libraries, missing_value):
    """빈 문자열과 결측값은 화면에서만 안내 문구로 표시한다."""
    dataframe = operating_libraries.iloc[:1].copy()
    dataframe["평일운영종료시각"] = missing_value
    dataframe["토요일운영시작시각"] = missing_value
    before = dataframe.copy(deep=True)
    monkeypatch.setattr(main, "load_library_csv", lambda path: dataframe)

    assert main.main(["--name", "합성운영"]) == 0
    output = capsys.readouterr().out
    assert "평일: 09:00 ~ 정보 없음" in output
    assert "토요일: 정보 없음 ~ 17:00" in output
    pd.testing.assert_frame_equal(dataframe, before)


@pytest.mark.parametrize(
    "missing_columns",
    [
        ["평일운영종료시각"],
        ["평일운영시작시각", "평일운영종료시각"],
        ["평일운영시작시각", "평일운영종료시각", "토요일운영시작시각", "토요일운영종료시각"],
    ],
)
def test_cli_missing_time_columns_are_handled(monkeypatch, capsys, operating_libraries, missing_columns):
    """한쪽 시간만 없으면 안내하고 요일의 두 컬럼이 모두 없으면 생략한다."""
    dataframe = operating_libraries.iloc[:1].drop(columns=missing_columns)
    before = dataframe.copy(deep=True)
    monkeypatch.setattr(main, "load_library_csv", lambda path: dataframe)

    assert main.main(["--name", "합성운영"]) == 0
    output = capsys.readouterr().out
    if "평일운영시작시각" in dataframe:
        assert "평일: 09:00 ~ 정보 없음" in output
    else:
        assert "평일:" not in output
    if "토요일운영시작시각" in dataframe:
        assert "토요일: 09:00 ~ 17:00" in output
    else:
        assert "토요일:" not in output
    pd.testing.assert_frame_equal(dataframe, before)


def test_cli_midnight_times_are_not_interpreted(monkeypatch, capsys, operating_libraries):
    """00:00은 휴관·24시간 여부를 판단하지 않고 그대로 출력한다."""
    dataframe = operating_libraries.iloc[:1].copy()
    for column in ["평일운영시작시각", "평일운영종료시각", "토요일운영시작시각", "토요일운영종료시각"]:
        dataframe[column] = "00:00"
    before = dataframe.copy(deep=True)
    monkeypatch.setattr(main, "load_library_csv", lambda path: dataframe)

    assert main.main(["--name", "합성운영"]) == 0
    output = capsys.readouterr().out
    assert "평일: 00:00 ~ 00:00" in output
    assert "토요일: 00:00 ~ 00:00" in output
    assert "휴관" not in output
    assert "24시간" not in output
    pd.testing.assert_frame_equal(dataframe, before)


def test_vertical_printer_preserves_result_dataframe(capsys, operating_libraries):
    """출력 함수 자체도 입력받은 검색 결과 표를 변경하지 않는다."""
    before = operating_libraries.copy(deep=True)
    main.print_search_results(operating_libraries)
    assert "[2] 합성운영도서관B" in capsys.readouterr().out
    pd.testing.assert_frame_equal(operating_libraries, before)
