"""실제 공공데이터와 구별되는 합성 데이터로 검색 조건을 검증한다."""

import pandas as pd
import pytest

from src.library_tool.search import search_libraries


@pytest.fixture
def libraries() -> pd.DataFrame:
    """부분 일치, 지역 조합, 빈값과 문자열 보존을 확인할 합성 표."""
    return pd.DataFrame(
        {
            "도서관명": ["합성 Alpha도서관", "합성 ALPHA분관", "합성 별도서관", "합성 [별]도서관", None],
            "시도명": ["가상시도A", "가상시도A", "가상시도B", "가상시도A", None],
            "시군구명": ["가상구1", "가상구2", "가상구1", "가상구1", None],
            "소재지도로명주소": ["합성주소 01", "합성주소 02", "합성주소 03", "합성주소 04", ""],
            "평일운영시작시각": ["09:00", "10:00", "09:30", "08:00", ""],
            "평일운영종료시각": ["18:00", "20:00", "17:30", "19:00", ""],
            "토요일운영시작시각": ["09:00", "10:30", "00:00", "08:30", ""],
            "토요일운영종료시각": ["17:00", "18:30", "00:00", "16:00", ""],
        },
        index=[10, 20, 30, 40, 50],
    )


def test_name_partial_match_ignores_case_and_surrounding_whitespace(libraries):
    """이름 부분 일치에 대소문자와 입력 앞뒤 공백이 영향을 주지 않는다."""
    result = search_libraries(libraries, name="  alpha  ")
    assert result.index.tolist() == [10, 20]


def test_sido_only(libraries):
    """시도 조건만으로 검색한다."""
    assert search_libraries(libraries, sido="가상시도A").index.tolist() == [10, 20, 40]


def test_sigungu_only(libraries):
    """시군구 조건만으로 여러 시도의 동일 지역명을 검색한다."""
    assert search_libraries(libraries, sigungu="가상구1").index.tolist() == [10, 30, 40]


def test_sido_and_sigungu(libraries):
    """두 지역 조건의 교집합만 반환한다."""
    assert search_libraries(libraries, sido="가상시도A", sigungu="가상구1").index.tolist() == [10, 40]


def test_name_and_region_are_combined_with_and(libraries):
    """세 조건을 모두 만족하는 도서관만 반환한다."""
    result = search_libraries(libraries, name="alpha", sido="가상시도A", sigungu="가상구2")
    assert result.index.tolist() == [20]
    assert search_libraries(libraries, name="alpha", sido="가상시도B").empty


def test_no_matches_returns_empty_frame_with_original_columns(libraries):
    """0건은 예외가 아니며 결과 구조는 유지한다."""
    result = search_libraries(libraries, name="존재하지않는합성도서관")
    assert result.empty
    assert result.columns.tolist() == libraries.columns.tolist()


@pytest.mark.parametrize("condition", ["name", "sido", "sigungu"])
def test_blank_condition_is_rejected(libraries, condition):
    """명시적으로 입력한 빈 조건은 전체 검색으로 바꾸지 않는다."""
    with pytest.raises(ValueError, match="비어 있거나 공백만"):
        search_libraries(libraries, **{condition: "   "})


@pytest.mark.parametrize("column, condition", [("도서관명", "name"), ("시도명", "sido"), ("시군구명", "sigungu")])
def test_missing_search_column_is_reported(libraries, column, condition):
    """검색에 필요한 누락 컬럼 이름을 명확하게 알린다."""
    with pytest.raises(ValueError, match=column):
        search_libraries(libraries.drop(columns=column), **{condition: "합성조건"})


def test_search_preserves_input_values_and_returns_independent_copy(libraries):
    """검색과 결과 수정 모두 원본에 영향을 주지 않는다."""
    before = libraries.copy(deep=True)
    result = search_libraries(libraries, sido="가상시도A")
    pd.testing.assert_frame_equal(result, before.loc[[10, 20, 40]])
    pd.testing.assert_frame_equal(libraries, before)
    result.loc[10, "도서관명"] = "합성결과변경"
    pd.testing.assert_frame_equal(libraries, before)


def test_name_query_is_literal_not_regex(libraries):
    """정규식 기호도 문자 그대로 검색한다."""
    assert search_libraries(libraries, name="[별]").index.tolist() == [40]


def test_region_requires_exact_match_and_trims_whitespace(libraries):
    """지역명은 부분 일치하지 않고 비교용 공백만 제거한다."""
    before = libraries.copy(deep=True)
    assert search_libraries(libraries, sido="가상시도").empty
    assert search_libraries(libraries, sido="  가상시도a  ").index.tolist() == [10, 20, 40]
    pd.testing.assert_frame_equal(libraries, before)


def test_unused_region_columns_are_not_required():
    """도서관명 검색에는 사용하지 않는 지역 컬럼을 요구하지 않는다."""
    dataframe = pd.DataFrame({"도서관명": ["합성도서관"]})
    pd.testing.assert_frame_equal(search_libraries(dataframe, name="합성"), dataframe)


def test_no_conditions_returns_all_rows(libraries):
    """함수 호출에서 모든 조건을 생략하면 전체 복사본을 반환한다."""
    pd.testing.assert_frame_equal(search_libraries(libraries), libraries)


@pytest.mark.parametrize("condition", ["name", "sido", "sigungu"])
def test_non_string_condition_is_rejected(libraries, condition):
    """문자열 이외의 검색 조건은 이해하기 쉬운 예외를 낸다."""
    with pytest.raises(TypeError, match="문자열이어야"):
        search_libraries(libraries, **{condition: 123})


def test_invalid_dataframe_is_rejected():
    """검색 함수에는 DataFrame만 전달할 수 있다."""
    with pytest.raises(TypeError, match="DataFrame이어야"):
        search_libraries(None, name="합성")


def test_empty_dataframe_is_searchable(libraries):
    """유효한 컬럼을 가진 빈 표는 빈 결과를 반환한다."""
    dataframe = libraries.iloc[:0]
    pd.testing.assert_frame_equal(search_libraries(dataframe, name="합성"), dataframe)


def test_all_four_operating_times_are_preserved(libraries):
    """네 운영시간과 원본 표를 이름·지역 검색 모두에서 보존한다."""
    columns = ["평일운영시작시각", "평일운영종료시각", "토요일운영시작시각", "토요일운영종료시각"]
    before = libraries.copy(deep=True)
    for options, indices in [({"name": "alpha"}, [10, 20]), ({"sido": "가상시도B"}, [30])]:
        result = search_libraries(libraries, **options)
        pd.testing.assert_frame_equal(result.loc[:, columns], before.loc[indices, columns])
        pd.testing.assert_frame_equal(libraries, before)
