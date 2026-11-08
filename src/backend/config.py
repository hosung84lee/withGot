"""앱 설정. .env 파일 또는 환경변수에서 값을 읽습니다."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from schema.agent import ProviderName

SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "withGod"
    db_filename: str = "app.db"

    pdf_dir: Path = DATA_DIR / "pdf"
    image_dir: Path = DATA_DIR / "image"
    db_dir: Path = DATA_DIR / "db"

    # --- Agent / LLM ---
    default_provider: ProviderName = "anthropic"
    agent_max_turns: int = 10
    agent_max_tokens: int = 16000

    # 키가 비어 있으면 각 SDK가 환경변수(ANTHROPIC_API_KEY 등)에서 직접 찾습니다.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"  # low | medium | high | xhigh | max
    anthropic_fallbacks: bool = True  # 거절(refusal) 시 서버 측 대체 모델로 재시도
    # summarized: 추론 요약을 응답에 포함 (trace 에서 확인용) | omitted: 빈 문자열
    anthropic_thinking_display: Literal["summarized", "omitted"] = "summarized"

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"

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
