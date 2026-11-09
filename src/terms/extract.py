"""약관 원문 텍스트 얻기 (PDF / 텍스트 파일)."""

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from schema.document import Document, DocumentKind

TEXT_EXTENSIONS = {".txt", ".md"}


class TextExtractionError(ValueError):
    pass


def pdf_to_text(data: bytes | str | Path) -> str:
    """PDF 의 텍스트 레이어를 페이지 순서대로 이어 붙입니다.

    스캔본(이미지로만 된 PDF)은 텍스트가 없어서 에러를 냅니다.
    """
    reader = PdfReader(BytesIO(data) if isinstance(data, bytes) else str(data))
    pages = [(p.extract_text() or "") for p in reader.pages]
    text = "\n".join(pages).strip()
    if len(text) < 20:
        raise TextExtractionError(
            f"PDF 에서 텍스트를 찾지 못했습니다 ({len(reader.pages)}쪽). "
            "스캔본(이미지) PDF 는 지원하지 않습니다. 텍스트를 직접 붙여 넣어 주세요."
        )
    return text


def bytes_to_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return pdf_to_text(data)
    if ext in TEXT_EXTENSIONS:
        for enc in ("utf-8-sig", "cp949"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        raise TextExtractionError(f"{filename}: 인코딩을 알 수 없습니다 (UTF-8, CP949 지원).")
    raise TextExtractionError(f"지원하지 않는 형식입니다: {filename} (PDF, TXT 지원)")


def document_to_text(doc: Document) -> str:
    if doc.kind != DocumentKind.PDF:
        raise TextExtractionError(
            f"{doc.filename}: 이미지 문서는 약관 구조화를 지원하지 않습니다 (PDF, TXT 만 가능)."
        )
    return pdf_to_text(doc.path)
