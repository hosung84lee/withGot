"""약관 구조화 뷰어(tools/terms_viewer)를 Streamlit 화면에 붙이기 위한 도우미."""

import importlib.util
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEWER_DIR = ROOT / "tools" / "terms_viewer"
SAMPLE_HTML = VIEWER_DIR / "out" / "terms-viewer.html"
PDF_DIR = ROOT / "insurance-workbench" / "data" / "reference" / "policies"


@cache
def _build():
    """tools/terms_viewer/build.py 를 모듈로 읽음 (tools 는 패키지가 아니라서)."""
    spec = importlib.util.spec_from_file_location("terms_viewer_build", VIEWER_DIR / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def html_for_text(name: str, text: str, pages: int = 0, extract_s: float = 0) -> str:
    """약관 텍스트 하나로 뷰어 HTML 을 만듭니다 (구조화·검증만, LLM 없음)."""
    b = _build()
    data = b.text_data(name, text, pages=pages, extract_s=extract_s)
    return b.render_html([data], uploaded=True)


def pdf_pages(data: bytes) -> int:
    """PDF 쪽 수 (PDF 가 아니거나 못 읽으면 0)."""
    if not data.startswith(b"%PDF"):
        return 0
    try:
        from io import BytesIO

        from pypdf import PdfReader

        return len(PdfReader(BytesIO(data)).pages)
    except Exception:  # noqa: BLE001 — 쪽 수는 표시용이라 실패해도 0
        return 0


def sample_pdfs() -> list[Path]:
    return sorted(PDF_DIR.glob("*.pdf"))


def build_sample_html(on_pdf=None) -> str:
    """샘플 약관 PDF 전부로 뷰어 HTML 을 만들어 out/ 에 저장합니다 (큰 약관 하나에 1분 안팎)."""
    b = _build()
    baseline = b.load_baseline()
    data = []
    pdfs = sample_pdfs()
    for i, pdf in enumerate(pdfs):
        if on_pdf:
            on_pdf(i, len(pdfs), pdf.name)
        data.append(b.policy_data(pdf, baseline))
    html = b.render_html(data)
    SAMPLE_HTML.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE_HTML.write_text(html, encoding="utf-8")
    return html
