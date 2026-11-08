"""업로드 파일 저장 및 문서 메타데이터 관리."""

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
    path = target_dir / Path(filename).name
    path.write_bytes(data)

    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO documents (filename, kind, path) VALUES (?, ?, ?)",
            (path.name, kind.value, str(path)),
        )
        doc_id = cur.lastrowid
    return get_document(doc_id)


def get_document(doc_id: int) -> Document:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return Document(**dict(row))


def list_documents() -> list[Document]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
    return [Document(**dict(r)) for r in rows]
