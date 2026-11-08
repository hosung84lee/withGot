"""업로드 파일 저장 및 문서 메타데이터 관리."""

import uuid
from pathlib import Path

from backend.config import get_settings
from backend.db import get_connection
from schema.document import Document, DocumentKind


def _target_dir(kind: DocumentKind) -> Path:
    settings = get_settings()
    return settings.pdf_dir if kind == DocumentKind.PDF else settings.image_dir


def save_upload(filename: str, data: bytes, kind: DocumentKind) -> Document:
    target_dir = _target_dir(kind)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = Path(filename).name
    # 같은 이름으로 다시 올려도 덮어쓰지 않도록 앞에 고유 ID 를 붙여 저장
    path = target_dir / f"{uuid.uuid4().hex[:8]}_{name}"
    path.write_bytes(data)

    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO documents (filename, kind, path) VALUES (?, ?, ?)",
            (name, kind.value, str(path)),
        )
        doc_id = cur.lastrowid
    return get_document(doc_id)


def get_document(doc_id: int) -> Document:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise LookupError(
            f"문서 {doc_id}번이 없습니다. list_uploaded_documents 로 id 를 확인하세요."
        )
    return Document(**dict(row))


def list_documents() -> list[Document]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
    return [Document(**dict(r)) for r in rows]
