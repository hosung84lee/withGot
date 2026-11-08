"""기본 제공 도구. 새 도구는 이 파일이나 skills/ 아래 새 모듈에 @tool 로 추가하세요."""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.attachments import attachment_from_document
from backend.storage import get_document, list_documents
from schema.agent import Attachment
from skills.registry import tool


@tool
def get_current_time(timezone: str = "Asia/Seoul") -> str:
    """지정한 IANA 타임존(예: Asia/Seoul)의 현재 시각을 ISO 8601 형식으로 반환합니다."""
    return datetime.now(ZoneInfo(timezone)).isoformat(timespec="seconds")


@tool
def list_uploaded_documents() -> list[dict]:
    """업로드된 PDF/이미지 문서 목록(id, filename, kind, created_at)을 반환합니다."""
    return [
        d.model_dump(include={"id", "filename", "kind", "created_at"}) for d in list_documents()
    ]


@tool
def read_document(doc_id: int) -> Attachment:
    """업로드된 문서(PDF/이미지)의 원본을 열어 봅니다. 파일이 그대로 전달되니 직접 읽고 답하세요.
    doc_id 는 list_uploaded_documents 로 확인합니다."""
    return attachment_from_document(get_document(doc_id))
