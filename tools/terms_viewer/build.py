"""약관 구조화 뷰어 만들기: 약관 PDF 들을 지금 코드로 구조화·검증해서 HTML 한 장으로 묶습니다.

    uv run python tools/terms_viewer/build.py
    uv run python tools/terms_viewer/build.py --out viewer.html --pdf-dir 다른/약관/폴더

결과는 브라우저로 바로 열 수 있는 HTML 한 파일입니다 (데이터·원문이 안에 들어 있어 3MB 안팎).
'수정 전과 비교' 칸은 baseline_16a4211.json (파서 수정 전 커밋으로 돌린 수치)을 씁니다.
기준 수치가 없는 약관은 그 칸에 지금 값만 나옵니다.
"""

import argparse
import base64
import datetime as dt
import gzip
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pypdf import PdfReader

from terms import parse_terms, validate_structure
from terms.extract import pdf_to_text

HERE = Path(__file__).resolve().parent
DEFAULT_PDF_DIR = ROOT / "insurance-workbench" / "data" / "reference" / "policies"


def _items(lst):
    return [{"lv": i.level, "lb": i.label, "t": i.text, "c": _items(i.children)} for i in lst]


def _segments(nlines, parts, heads, arts, apps):
    """원문 줄마다 어느 구조 요소가 차지하는지 (원문 분류 지도)."""
    marks = [(p["line"], "part", i) for i, p in enumerate(parts)]
    marks += [(h["line"], "heading", i) for i, h in enumerate(heads)]
    marks += [(a["line"], "article", i) for i, a in enumerate(arts)]
    marks += [(x["line"], "annex" if x["annex"] else "appendix", i) for i, x in enumerate(apps)]
    marks.sort()
    segs = []
    first = marks[0][0] if marks else nlines + 1
    if first > 1:
        segs.append({"s": 1, "e": first - 1, "k": "preamble", "i": -1})
    for j, (ln, k, i) in enumerate(marks):
        end = marks[j + 1][0] - 1 if j + 1 < len(marks) else nlines
        segs.append({"s": ln, "e": max(ln, end), "k": k, "i": i})
    return segs


def policy_data(pdf: Path, baseline: dict) -> dict:
    t0 = time.time()
    text = pdf_to_text(pdf)
    data = text_data(pdf.stem, text, baseline, pages=len(PdfReader(pdf).pages))
    data["t"]["extract"] = round(time.time() - t0, 2)
    return data


def text_data(
    name: str, text: str, baseline: dict | None = None, pages: int = 0, extract_s: float = 0
) -> dict:
    """이미 뽑은 약관 텍스트로 뷰어 데이터 하나를 만듭니다 (앱의 약관 분석 화면에서도 씀)."""
    baseline = baseline or {}
    t1 = time.time()
    doc = parse_terms(text)
    t2 = time.time()
    issues = validate_structure(doc)
    t3 = time.time()
    arts = [
        {
            "label": a.label,
            "title": a.title,
            "line": a.line,
            "path": a.path,
            "deleted": a.deleted,
            "addendum": a.addendum,
            "part": a.part,
            "section": a.section,
            "len": len(a.full_text()),
            "paras": [{"n": p.number, "t": p.text, "items": _items(p.items)} for p in a.paragraphs],
            "refs": [
                {"text": r.text, "target": r.article_label, "p": r.paragraph, "i": r.item}
                for r in a.references
            ],
        }
        for a in doc.articles
    ]
    apps = [
        {"label": x.label, "line": x.line, "len": len(x.text), "annex": x.label.startswith("부록")}
        for x in doc.appendices
    ]
    heads = [
        {"label": h.label, "kind": h.kind, "line": h.line, "part": h.part} for h in doc.headings
    ]
    parts = [{"title": p.title, "line": p.line} for p in doc.parts]
    nlines = len(text.split("\n"))
    before = baseline.get(name)
    if before is None:  # 기준 수치가 없으면 지금 값과 같게 (비교 칸에 변화 없음으로 나옴)
        before = {"articles": len(arts), "artShare": 0, "errors": 0, "warnings": 0}
    return {
        "name": name,
        "pages": pages,
        "chars": len(text),
        "nlines": nlines,
        "t": {
            "extract": round(extract_s, 2),
            "parse": round(t2 - t1, 3),
            "validate": round(t3 - t2, 3),
        },
        "title": doc.title,
        "parts": parts,
        "headings": heads,
        "articles": arts,
        "appendices": apps,
        "issues": [i.model_dump() for i in issues],
        "segs": _segments(nlines, parts, heads, arts, apps),
        "before": before,
        "raw": base64.b64encode(gzip.compress(text.encode("utf-8"), 9)).decode(),
    }


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "작업 중"


def main() -> int:
    ap = argparse.ArgumentParser(description="약관 구조화 뷰어 HTML 만들기")
    ap.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR, help="약관 PDF 폴더")
    ap.add_argument("--out", type=Path, default=HERE / "out" / "terms-viewer.html")
    args = ap.parse_args()

    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"PDF 가 없습니다: {args.pdf_dir}", file=sys.stderr)
        return 1
    baseline = load_baseline()
    data = []
    for pdf in pdfs:
        print(f"구조화 중: {pdf.name}", file=sys.stderr)
        data.append(policy_data(pdf, baseline))

    html = render_html(data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"저장: {args.out} ({args.out.stat().st_size / 1e6:.1f}MB)", file=sys.stderr)
    return 0


def load_baseline() -> dict:
    return json.loads((HERE / "baseline_16a4211.json").read_text(encoding="utf-8"))["policies"]


SAMPLE_INTRO = "저장소의 약관 7개를 파서 수정 후 코드"
UPLOAD_INTRO = (
    '<p>올린 약관을 <span class="mono">src/terms</span>가 약관·관·조·항·호로 나누고 '
    "검증한 결과입니다 (LLM 없음).</p>"
)


def render_html(data: list[dict], uploaded: bool = False) -> str:
    """뷰어 데이터 목록 → 브라우저에서 바로 열 수 있는 HTML 한 장.

    uploaded=True: 앱에서 올린 약관용. 소개 문구를 바꾸고, 기준 수치가 없는 '파서 수정 전과 비교' 를 숨김.
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (HERE / "template.html").read_text(encoding="utf-8")
    if uploaded:
        start = html.index("<p>약관 PDF를 올렸을 때")
        end = html.index("</p>", start) + len("</p>")
        assert SAMPLE_INTRO in html[start:end]
        html = html[:start] + UPLOAD_INTRO + html[end:]
        html = html.replace("</style>", "section:has(#compare) { display: none; }\n</style>", 1)
    html = (
        html.replace("/*__DATA__*/", f"window.TERMS_DATA = {payload};")
        .replace("__COMMIT__", _commit())
        .replace("__DATE__", dt.date.today().isoformat())
    )
    # 템플릿은 claude.ai Artifact 형식(본문만)이라 브라우저에서 바로 열 수 있게 머리를 붙임
    html = (
        '<!doctype html>\n<html lang="ko"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n' + html
    )
    return html


if __name__ == "__main__":
    raise SystemExit(main())
