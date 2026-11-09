"""약관 구조화/검증 도구. agent 가 보관함의 약관 PDF 를 조 단위로 다룰 때 사용합니다."""

from functools import lru_cache

from backend.storage import get_document
from schema.terms import TermsDocument
from skills.registry import tool
from terms.extract import document_to_text
from terms.parser import parse_terms
from terms.validator import validate_structure


@lru_cache(maxsize=8)
def _parsed(path: str, doc_id: int) -> TermsDocument:
    return parse_terms(document_to_text(get_document(doc_id)))


def _load(doc_id: int) -> TermsDocument:
    return _parsed(get_document(doc_id).path, doc_id)


@tool
def get_terms_outline(doc_id: int) -> dict:
    """보관함의 약관 PDF 를 조(제N조) 단위로 구조화해서 목차와 구조 검증 결과를 반환합니다.
    약관의 구성을 파악하거나 특정 조항을 찾을 때 먼저 호출하세요.
    본문은 get_terms_article 로 조 하나씩 읽습니다."""
    doc = _load(doc_id)
    return {
        "title": doc.title,
        "headings": [h.label for h in doc.headings],
        "articles": [
            {"article": a.label, "title": a.title, "deleted": a.deleted, "path": a.path}
            for a in doc.articles
        ],
        "addenda": doc.addenda,
        "appendices": [x.label for x in doc.appendices],
        "issues": [
            i.model_dump(include={"severity", "code", "message", "article"})
            for i in validate_structure(doc)
        ],
    }


@tool
def get_terms_article(doc_id: int, article: str) -> str:
    """약관의 조 하나의 본문을 반환합니다. article 예: '제12조', '12', '제3조의2', '부칙 제1조'."""
    doc = _load(doc_id)
    a = doc.find(article)
    if a is None:
        raise LookupError(
            f"'{article}'를 찾지 못했습니다. get_terms_outline 으로 조 목록을 확인하세요."
        )
    head = a.label + (f"({a.title})" if a.title else "") + (" 삭제" if a.deleted else "")
    return f"{head}\n{a.full_text()}"
