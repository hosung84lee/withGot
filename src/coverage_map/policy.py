"""보장맵에 실제 약관 PDF 연결: 구조화(캐시) · 보장 규칙(정답 데이터/AI 추출, 캐시) · 근거 조항 원문.

- 텍스트 추출은 큰 약관 하나에 1분 안팎이라 파일 해시로 캐시 (src/data/cache/text, bytes 로 저장)
- 보장 규칙: 실손 2605 처럼 정답 데이터가 있는 약관은 그것을, 없으면 coverage_extract(AI) 로
  보장 묶음(약관 · 보장종목)마다 추출해 캐시 (src/data/cache/coverage/<해시>/)
- 어느 쪽이든 근거 검증(ground_product)으로 원문에 근거가 있는지 확인
"""

import hashlib
import html
import json
import re
from collections.abc import Callable
from pathlib import Path

from backend.config import DATA_DIR
from coverage_extract.bundles import Bundle, build_bundles
from coverage_extract.extractor import SectionExtraction
from coverage_extract.grounding import (
    GroundingReport,
    _part_index,
    find_article,
    ground_product,
    squash,
)
from schema.coverage import Coverage, Product, SourceRef
from schema.terms import Article, TermsDocument
from terms import parse_terms
from terms.extract import pdf_to_text

from .linker import DEFAULT_PRODUCT, load_product

ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = ROOT / "insurance-workbench" / "data" / "reference" / "policies"
CACHE_DIR = DATA_DIR / "cache"
GOLDEN = [DEFAULT_PRODUCT]  # 사람이 원문과 대조한 보장 데이터


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def sample_policies() -> list[Path]:
    return sorted(POLICY_DIR.glob("*.pdf"))


def policy_text(data: bytes) -> str:
    """PDF → 텍스트 (해시 캐시). Windows 에서 줄바꿈이 바뀌지 않게 bytes 로 저장."""
    path = CACHE_DIR / "text" / f"{file_hash(data)}.txt"
    if path.exists():
        return path.read_bytes().decode("utf-8")
    text = pdf_to_text(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return text


def load_terms(data: bytes) -> TermsDocument:
    return parse_terms(policy_text(data))


def golden_for(doc: TermsDocument) -> Product | None:
    """이 약관과 이름이 같은 정답 데이터 (약관 제목 줄로 비교)."""
    for path in GOLDEN:
        product = load_product(path)
        if doc.parts and _part_index(doc, product.name) is not False:
            return product
    return None


def bundles(doc: TermsDocument) -> list[Bundle]:
    return build_bundles(doc)


def _slug(key: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", key).strip("_")[:80]


def _cache_dir(key: str) -> Path:
    return CACHE_DIR / "coverage" / key


def cached_sections(key: str) -> dict[str, SectionExtraction]:
    """AI 로 추출해 둔 묶음별 결과 {묶음 key: SectionExtraction}. key = 원본 파일 해시."""
    out = {}
    folder = _cache_dir(key)
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        data = json.loads(f.read_text(encoding="utf-8"))
        out[data["bundle"]] = SectionExtraction.model_validate(data["result"])
    return out


def dropped_issues(key: str) -> list:
    """캐시된 묶음 중 형식이 틀려 뺀 항목 (PARTIAL_EXTRACTION 경고)."""
    from coverage_extract.grounding import GroundingIssue

    return [
        GroundingIssue(severity="warning", code="PARTIAL_EXTRACTION", target=k, message=m)
        for k, r in cached_sections(key).items()
        for m in r.dropped
    ]


def golden_keys(doc: TermsDocument, golden: Product | None) -> set[str]:
    """정답 데이터가 이미 담고 있는 묶음 (약관 이름 + 보장종목이 같은 묶음)."""
    if not golden:
        return set()
    sections = {k.section for c in golden.coverages for k in c.risks}
    sections |= {e.section for e in golden.exclusions()}
    return {
        b.key
        for b in bundles(doc)
        if squash(b.part_title) == squash(golden.name) and b.section in sections
    }


def extract_missing(
    key: str,
    doc: TermsDocument,
    bundle_keys: list[str],
    model: str | None = None,
    on_progress: Callable[[int, int, Bundle], None] | None = None,
) -> dict[str, str]:
    """캐시에 없는 묶음만 AI 로 추출해 캐시 (OpenAI API, 묶음 동시 추출). 실패한 묶음 {key: 오류}."""
    from coverage_extract.extractor import extract_sections

    have = cached_sections(key)
    todo = [b for b in bundles(doc) if b.key in bundle_keys and b.key not in have]
    if not todo:
        return {}
    results, errors = extract_sections(todo, model=model, on_progress=on_progress)
    folder = _cache_dir(key)
    folder.mkdir(parents=True, exist_ok=True)
    for bundle, result in results:
        payload = {"bundle": bundle.key, "result": result.model_dump(mode="json")}
        (folder / f"{_slug(bundle.key)}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return errors


def build_product(
    doc: TermsDocument, key: str, golden: Product | None = None, use_golden: bool = True
) -> Product | None:
    """정답 데이터 + AI 추출 캐시 → Product (같은 약관의 보장은 하나로 합침).

    use_golden=False 면 AI 추출 결과만 (약관 분석 화면).
    """
    from coverage_extract.extractor import assemble

    cached = cached_sections(key)
    skip = golden_keys(doc, golden) if (golden and use_golden) else set()
    results = [(b, cached[b.key]) for b in bundles(doc) if b.key in cached and b.key not in skip]
    parts = []
    if golden and use_golden:
        parts.append(golden)
    if results:
        parts.append(assemble(doc, results))
    if not parts:
        return None
    return merge(parts, doc.title or parts[0].name)


def merge(products: list[Product], name: str) -> Product:
    """여러 Product 를 하나로. 같은 id 의 보장(약관)은 위험·보상 제외를 이어 붙임."""
    coverages: dict[str, Coverage] = {}
    for p in products:
        for c in p.coverages:
            if c.id in coverages:
                cur = coverages[c.id]
                cur.risks = cur.risks + c.risks
                cur.exclusions = cur.exclusions + c.exclusions
            else:
                coverages[c.id] = c.model_copy(deep=True)
    return Product(
        name=name,
        insurer=next((p.insurer for p in products if p.insurer), ""),
        coverages=list(coverages.values()),
        coverage_codes=[c for p in products for c in p.coverage_codes],
    )


def ground(product: Product, doc: TermsDocument) -> GroundingReport:
    return ground_product(product.model_copy(deep=True), doc)


def article_for(doc: TermsDocument, src: SourceRef) -> Article | None:
    return find_article(doc, src)


def highlight(text: str, quote: str) -> str:
    """원문에서 인용문을 찾아 <mark> (공백 차이 무시). HTML 이스케이프한 결과."""
    esc = html.escape(text)
    q = re.sub(r"\s+", "", quote)
    if not q:
        return esc
    pattern = r"\s*".join(re.escape(html.escape(ch)) for ch in q)
    return re.sub(pattern, lambda m: f"<mark>{m.group(0)}</mark>", esc, count=1)
