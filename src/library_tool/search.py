"""원본 DataFrame을 변경하지 않는 도서관명·지역 검색."""

import pandas as pd


def search_libraries(
    dataframe: pd.DataFrame,
    *,
    name: str | None = None,
    sido: str | None = None,
    sigungu: str | None = None,
) -> pd.DataFrame:
    """지정한 조건을 AND로 적용하고 검색 결과의 복사본을 반환한다.

    도서관명은 정규식이 아닌 문자열 부분 일치, 지역은 전체 일치로
    검색한다. 입력과 비교용 값의 앞뒤 공백·대소문자를 무시한다.
    None인 조건은 적용하지 않으며 조건이 없으면 전체 복사본을 반환한다.
    원본 값, 컬럼 순서, 행 순서와 인덱스는 그대로 유지한다.

    Raises:
        TypeError: DataFrame이 아닌 데이터나 문자열이 아닌 조건 입력.
        ValueError: 빈 검색 조건 또는 검색에 필요한 컬럼 누락.
    """
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("검색 데이터는 pandas DataFrame이어야 합니다.")

    conditions = {"도서관명": name, "시도명": sido, "시군구명": sigungu}
    normalized = {}
    for column, value in conditions.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"{column} 검색 조건은 문자열이어야 합니다.")
        value = value.strip()
        if not value:
            raise ValueError(f"{column} 검색 조건은 비어 있거나 공백만 있을 수 없습니다.")
        normalized[column] = value.casefold()

    # 식별 컬럼과 실제 적용할 필터의 컬럼만 요구한다.
    required_columns = dict.fromkeys(["도서관명", *normalized])
    missing = [column for column in required_columns if column not in dataframe.columns]
    if missing:
        raise ValueError(f"검색에 필요한 필수 컬럼이 누락되었습니다: {', '.join(missing)}")

    mask = pd.Series(True, index=dataframe.index)
    for column, value in normalized.items():
        # 비교용 Series만 정규화하고 원본의 빈값과 문자열은 수정하지 않는다.
        values = dataframe[column].astype("string").str.strip().str.casefold()
        if column == "도서관명":
            matches = values.str.contains(value, regex=False, na=False)
        else:
            matches = values.eq(value).fillna(False)
        mask &= matches

    return dataframe.loc[mask].copy()
