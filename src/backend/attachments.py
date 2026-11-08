"""첨부 파일 처리: 경로 → Attachment, Attachment → base64."""

import base64
from pathlib import Path

from backend.config import get_settings
from schema.agent import Attachment
from schema.document import Document

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
SUPPORTED_EXTENSIONS = [ext.lstrip(".") for ext in MEDIA_TYPES]


def media_type_of(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in MEDIA_TYPES:
        raise ValueError(
            f"지원하지 않는 파일 형식: {ext or filename} (지원: {', '.join(MEDIA_TYPES)})"
        )
    return MEDIA_TYPES[ext]


def attachment_from_document(doc: Document) -> Attachment:
    return Attachment(
        path=doc.path, media_type=media_type_of(doc.filename), filename=doc.filename, doc_id=doc.id
    )


def read_base64(a: Attachment) -> str:
    path = Path(a.path)
    if not path.exists():
        raise FileNotFoundError(f"첨부 파일이 없습니다: {a.filename} ({a.path})")
    limit = get_settings().attachment_max_mb * 1024 * 1024
    size = path.stat().st_size
    if size > limit:
        raise ValueError(
            f"첨부 파일이 너무 큽니다: {a.filename} ({size / 1024 / 1024:.1f}MB, "
            f"최대 {get_settings().attachment_max_mb}MB)"
        )
    return base64.standard_b64encode(path.read_bytes()).decode()
