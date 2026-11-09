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

    # --- Agent / LLM (OpenAI) ---
    agent_max_turns: int = 10
    agent_max_tokens: int = 16000

    openai_api_key: str | None = None
    openai_model: str = "gpt-6-luna"
    # none | minimal | low | medium | high | xhigh | max (비우면 모델 기본값)
    # gpt-6-luna 는 Chat Completions 에서 도구를 쓰려면 none 이어야 함. none 이 토큰도 가장 적게 씀
    openai_reasoning_effort: str | None = "none"

    attachment_max_mb: int = 30  # 첨부 파일 1개 최대 크기

    # --- Tracing ---
    tracing_enabled: bool = True
    trace_max_str: int = 20000  # 저장할 문자열 최대 길이 (넘으면 잘라서 저장)

    @property
    def db_path(self) -> Path:
        return self.db_dir / self.db_filename


@lru_cache
def get_settings() -> Settings:
    return Settings()
