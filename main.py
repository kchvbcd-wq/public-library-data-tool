"""프로젝트 원본 CSV의 구조와 첫 5개 행을 터미널에 출력한다."""

from pathlib import Path
import sys

from src.library_tool.loader import load_library_csv


PROJECT_ROOT = Path(__file__).resolve().parent
CSV_PATH = PROJECT_ROOT / "data" / "raw" / "전국도서관표준데이터.csv"


def main() -> int:
    """CSV 구조를 출력하고 성공 시 0, 로딩 실패 시 1을 반환한다."""
    try:
        dataframe = load_library_csv(CSV_PATH)
    except (OSError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(f"CSV 파일: {CSV_PATH}")
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
