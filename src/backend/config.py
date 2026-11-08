"""앱 설정. .env 파일 또는 환경변수에서 값을 읽습니다."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "withGod"
    db_filename: str = "app.db"

    pdf_dir: Path = DATA_DIR / "pdf"
    image_dir: Path = DATA_DIR / "image"
    db_dir: Path = DATA_DIR / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / self.db_filename


@lru_cache
def get_settings() -> Settings:
    return Settings()
