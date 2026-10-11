"""합성 CSV로 로더의 정상 동작과 실패 상황을 검증한다."""

from pathlib import Path

import pandas as pd
import pytest

from src.library_tool.loader import REQUIRED_COLUMNS, load_library_csv


def test_load_valid_cp949_csv(tmp_path: Path) -> None:
    """행 수, 컬럼 순서와 원본 문자열 표현을 모두 유지한다."""
    path = tmp_path / "합성도서관.csv"
    expected = pd.DataFrame(
        {
            "도서관명": ["합성테스트도서관A", "합성테스트도서관B"],
            "시도명": ["가상지역", ""],
            "제공기관코드": ["00123", "NA"],
        }
    )
    expected.to_csv(path, index=False, encoding="cp949")

    actual = load_library_csv(path)

    assert actual.shape == (2, 3)
    pd.testing.assert_frame_equal(actual, expected)


def test_missing_file(tmp_path: Path) -> None:
    """없는 경로에 대해 파일명과 이해하기 쉬운 오류를 제공한다."""
    path = tmp_path / "missing.csv"

    with pytest.raises(FileNotFoundError, match="CSV 파일을 찾을 수 없습니다") as error:
        load_library_csv(path)

    assert str(path) in str(error.value)


def test_missing_required_column(tmp_path: Path) -> None:
    """누락된 필수 컬럼명을 오류 메시지에 표시한다."""
    path = tmp_path / "missing_column.csv"
    missing_column = REQUIRED_COLUMNS[0]
    row = {name: "합성값" for name in REQUIRED_COLUMNS if name != missing_column}
    row["합성추가컬럼"] = "합성값"
    pd.DataFrame([row]).to_csv(path, index=False, encoding="cp949")

    with pytest.raises(ValueError, match="필수 컬럼이 누락되었습니다") as error:
        load_library_csv(path)

    assert missing_column in str(error.value)


def test_completely_empty_csv(tmp_path: Path) -> None:
    """0바이트 파일을 헤더만 있는 CSV와 구별한다."""
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")

    with pytest.raises(ValueError, match="비어 있거나 읽을 수 있는 헤더가 없습니다"):
        load_library_csv(path)


def test_header_only_csv(tmp_path: Path) -> None:
    """정상 헤더는 있지만 데이터 행이 없으면 별도 오류를 제공한다."""
    path = tmp_path / "header_only.csv"
    pd.DataFrame(columns=REQUIRED_COLUMNS).to_csv(path, index=False, encoding="cp949")

    with pytest.raises(ValueError, match="헤더는 있지만 데이터 행이 없습니다"):
        load_library_csv(path)


def test_invalid_encoding(tmp_path: Path) -> None:
    """CP949로 해독할 수 없는 바이트를 대체하지 않고 오류를 낸다."""
    path = tmp_path / "invalid_encoding.csv"
    path.write_bytes("도서관명\n".encode("cp949") + b"\xff\n")

    with pytest.raises(ValueError, match="CP949 인코딩") as error:
        load_library_csv(path)

    assert isinstance(error.value.__cause__, UnicodeDecodeError)


def test_malformed_csv(tmp_path: Path) -> None:
    """깨진 따옴표가 있는 CSV의 파싱 오류를 명확히 보고한다."""
    path = tmp_path / "malformed.csv"
    path.write_text('도서관명\n"합성테스트도서관\n', encoding="cp949")

    with pytest.raises(ValueError, match="CSV 형식이 올바르지 않습니다"):
        load_library_csv(path)


def test_string_file_path(tmp_path: Path) -> None:
    """Path 객체뿐 아니라 문자열 경로도 받는다."""
    path = tmp_path / "string_path.csv"
    path.write_text("도서관명\n합성테스트도서관\n", encoding="cp949")

    actual = load_library_csv(str(path))

    assert actual.loc[0, "도서관명"] == "합성테스트도서관"


def test_directory_instead_of_file(tmp_path: Path) -> None:
    """파일 대신 디렉터리를 지정하면 읽기 오류를 제공한다."""
    with pytest.raises(OSError, match="CSV 파일을 읽을 수 없습니다"):
        load_library_csv(tmp_path)
