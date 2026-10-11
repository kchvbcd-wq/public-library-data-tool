"""프로젝트 원본 CSV의 구조 조회와 도서관 검색 CLI."""

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

import pandas as pd

from src.library_tool.loader import load_library_csv
from src.library_tool.search import search_libraries


PROJECT_ROOT = Path(__file__).resolve().parent
CSV_PATH = PROJECT_ROOT / "data" / "raw" / "전국도서관표준데이터.csv"


def _display_value(value: object) -> str:
    """빈값을 화면에서만 안내 문구로 바꾸고 실제 값은 그대로 둔다."""
    return "정보 없음" if pd.isna(value) or value == "" else str(value)


def print_search_results(results: pd.DataFrame) -> None:
    """검색 결과를 원본 행 순서대로 번호를 붙여 세로로 출력한다."""
    for number, (_, library) in enumerate(results.iterrows(), start=1):
        print(f"\n[{number}] {_display_value(library['도서관명'])}")
        region_columns = [column for column in ("시도명", "시군구명") if column in library.index]
        if region_columns:
            print("지역: " + " ".join(_display_value(library[column]) for column in region_columns))
        if "소재지도로명주소" in library.index:
            print(f"주소: {_display_value(library['소재지도로명주소'])}")
        for label, start_column, end_column in (
            ("평일", "평일운영시작시각", "평일운영종료시각"),
            ("토요일", "토요일운영시작시각", "토요일운영종료시각"),
        ):
            # 두 컬럼 모두 없으면 생략하고, 한쪽만 없으면 화면에서만 안내한다.
            if start_column in library.index or end_column in library.index:
                start = _display_value(library.get(start_column, ""))
                end = _display_value(library.get(end_column, ""))
                print(f"{label}: {start} ~ {end}")


def main(argv: Sequence[str] | None = None) -> int:
    """옵션에 따라 구조 또는 검색 결과를 출력하고 종료 코드를 반환한다."""
    parser = argparse.ArgumentParser(description="전국 도서관 CSV 구조 조회 및 검색")
    parser.add_argument("--name", help="도서관명 부분 일치 검색 (대소문자 구분 없음)")
    parser.add_argument("--sido", help="시도명 전체 일치 검색 (예: 서울특별시)")
    parser.add_argument("--sigungu", help="시군구명 전체 일치 검색 (예: 강남구)")
    args = parser.parse_args(argv)
    is_search = any(value is not None for value in (args.name, args.sido, args.sigungu))

    try:
        dataframe = load_library_csv(CSV_PATH)
        if is_search:
            results = search_libraries(
                dataframe, name=args.name, sido=args.sido, sigungu=args.sigungu,
            )
    except (OSError, ValueError, TypeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(f"CSV 파일: {CSV_PATH}")
    if is_search:
        print(f"검색 결과: {len(results):,}건")
        if results.empty:
            print("조건에 일치하는 도서관이 없습니다.")
        else:
            print_search_results(results)
        return 0

    print(f"전체 데이터 행 수: {len(dataframe):,}")
    print(f"전체 컬럼 수: {len(dataframe.columns)}")
    print("\n모든 컬럼명:")
    for number, name in enumerate(dataframe.columns, start=1):
        print(f"{number}. {name}")
    print("\n첫 번째 5개 행 (모든 컬럼):")
    # 기본 화면 폭 때문에 컬럼이 생략되지 않도록 전체 문자열을 출력한다.
    print(dataframe.head(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
