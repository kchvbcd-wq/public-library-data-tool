"""원본 내용을 정제하지 않고 CP949 도서관 CSV를 읽는다."""

from pathlib import Path

import pandas as pd


# 구조 확인 단계에서는 도서관 식별에 필요한 컬럼만 필수로 지정한다.
REQUIRED_COLUMNS = ("도서관명",)


def load_library_csv(file_path: str | Path) -> pd.DataFrame:
    """CP949 CSV를 읽고 최소 구조를 검사한 뒤 DataFrame을 반환한다.

    모든 값은 문자열로 읽어 코드의 앞자리 0, 전화번호, 빈 문자열과
    'NA' 같은 원본 값을 보존한다. 추가 컬럼과 컬럼 순서도 유지한다.
    상대 경로는 호출 시 작업 디렉터리를 기준으로 해석한다.

    Raises:
        FileNotFoundError: 지정한 파일이 없는 경우.
        OSError: 접근 권한 등으로 파일을 읽을 수 없는 경우.
        ValueError: CP949 해독 실패, 잘못된 CSV 구조, 빈 파일,
            필수 컬럼 누락 또는 데이터 행이 없는 경우.
    """
    path = Path(file_path)

    try:
        # 자동 숫자 변환과 기본 결측치 변환을 막아 원본 표현을 유지한다.
        dataframe = pd.read_csv(path, encoding="cp949", dtype=str, keep_default_na=False)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"CSV 파일을 CP949 인코딩으로 읽을 수 없습니다: {path}. "
            "실제 파일 인코딩을 확인하세요."
        ) from exc
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"CSV 파일이 비어 있거나 읽을 수 있는 헤더가 없습니다: {path}") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"CSV 형식이 올바르지 않습니다: {path}. {exc}") from exc
    except OSError as exc:
        raise OSError(f"CSV 파일을 읽을 수 없습니다: {path}. {exc}") from exc

    missing_columns = [name for name in REQUIRED_COLUMNS if name not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"필수 컬럼이 누락되었습니다: {', '.join(missing_columns)} ({path})")

    if dataframe.empty:
        raise ValueError(f"CSV 파일에 헤더는 있지만 데이터 행이 없습니다: {path}")

    return dataframe
