import pytest

from backend.config import get_settings
from backend.db import init_db


@pytest.fixture(autouse=True)
def temp_data(tmp_path, monkeypatch):
    """테스트마다 임시 DB/파일 폴더 사용 (앱 데이터에 섞이지 않게)."""
    s = get_settings()
    monkeypatch.setattr(s, "db_dir", tmp_path / "db")
    monkeypatch.setattr(s, "pdf_dir", tmp_path / "pdf")
    monkeypatch.setattr(s, "image_dir", tmp_path / "image")
    init_db()
