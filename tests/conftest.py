import pytest

from backend.config import get_settings
from backend.db import init_db


def pytest_addoption(parser):
    parser.addoption(
        "--pdf",
        action="store_true",
        help="실제 약관 PDF 를 읽는 느린 테스트(@pytest.mark.pdf)도 실행합니다.",
    )


def pytest_collection_modifyitems(config, items):
    """기본 실행에서는 실제 PDF 테스트를 건너뜀 (PDF 텍스트 추출에 수십 초 걸림)."""
    if config.getoption("--pdf"):
        return
    skip = pytest.mark.skip(reason="실제 약관 PDF 테스트: `pytest --pdf` 로 실행")
    for item in items:
        if "pdf" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def temp_data(tmp_path, monkeypatch):
    """테스트마다 임시 DB/파일 폴더 사용 (앱 데이터에 섞이지 않게)."""
    s = get_settings()
    monkeypatch.setattr(s, "db_dir", tmp_path / "db")
    monkeypatch.setattr(s, "pdf_dir", tmp_path / "pdf")
    monkeypatch.setattr(s, "image_dir", tmp_path / "image")
    init_db()
