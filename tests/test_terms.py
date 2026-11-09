"""약관 구조화 / 검증 / 분석 테스트. LLM 은 가짜 OpenAIClient 로 바꿔서 API 키 없이 실행합니다."""

import json
from pathlib import Path

import pytest

from agent.llm import OpenAIClient
from schema.agent import LLMResponse
from schema.terms import ClauseAnalysis, ClauseIssue, TermsAnalysis
from terms import parse_terms, validate_analysis, validate_structure
from terms.analyzer import AnalysisError, analyze_terms, chunk_articles, extract_json
from terms.extract import TextExtractionError, bytes_to_text
from terms.parser import extract_references
from terms.pipeline import run_terms_pipeline

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_terms.txt").read_text(encoding="utf-8")


@pytest.fixture
def doc():
    return parse_terms(SAMPLE)


def codes(issues):
    return [i.code for i in issues]


# ---------------------------------------------------------------- 구조화


def test_parse_structure(doc):
    assert doc.title == "위드갓 서비스 이용약관"
    assert doc.preamble.startswith("이 약관은")
    assert [h.label for h in doc.headings] == ["제1장 총칙", "제2장 이용계약", "제3장 계약 해지"]
    assert [a.label for a in doc.articles] == [
        "제1조",
        "제2조",
        "제3조",
        "제3조의2",
        "제4조",
        "제5조",
        "제7조",
        "제8조",
        "부칙 제1조",
    ]
    assert doc.addenda == ["부 칙 <2024. 1. 1.>"]
    assert doc.appendices[0].label == "별표 1 이용요금표"
    assert "9,900원" in doc.appendices[0].text


def test_parse_article_details(doc):
    a1 = doc.find("제1조")
    assert a1.title == "목적" and a1.path == ["제1장 총칙"]
    # 줄바꿈으로 이어진 본문은 하나의 항으로 합쳐짐
    assert len(a1.paragraphs) == 1 and a1.paragraphs[0].number is None
    assert "회원의 권리·의무" in a1.paragraphs[0].text

    a2 = doc.find("2")
    assert [p.number for p in a2.paragraphs] == [1, 2]
    items = a2.paragraphs[0].items
    assert [(i.level, i.label) for i in items] == [("호", "1"), ("호", "2")]
    assert [(i.level, i.label) for i in items[1].children] == [("목", "가"), ("목", "나")]

    assert doc.find("제3조의2").title == "개인정보 보호"
    assert doc.find("제4조").deleted
    assert doc.find("부칙 제1조").addendum == 1
    assert doc.find("부칙 제1조").full_text() == "이 약관은 2024년 1월 1일부터 시행한다."
    assert doc.find("제6조") is None
    # 페이지 번호(- 1 -)는 본문에 섞이지 않음
    assert "- 1 -" not in a2.full_text()


def test_article_header_vs_inline_reference():
    doc = parse_terms("제1조(목적)\n본문\n제1조에 따라 처리한다.\n제2조 정의\n본문2")
    assert [a.label for a in doc.articles] == ["제1조", "제2조"]
    assert "제1조에 따라 처리한다." in doc.articles[0].full_text()
    assert doc.articles[1].title == "정의"


def test_paragraph_markers_and_subitems():
    doc = parse_terms("제1조(테스트) ① 첫째 항\n1. 호\n가. 목\n1) 세목\n(2) 세목2\n② 둘째 항")
    a = doc.articles[0]
    assert [p.number for p in a.paragraphs] == [1, 2]
    ho = a.paragraphs[0].items[0]
    mok = ho.children[0]
    assert mok.level == "목" and [c.label for c in mok.children] == ["1)", "(2)"]


def test_extract_references():
    refs = extract_references(
        "제5조제2항제3호 및 제3조의2에 따르고, 「상법」 제638조와 같은 법 제639조는 제외하며 제2항을 준용"
    )
    assert [(r.article, r.sub, r.paragraph, r.item) for r in refs] == [
        (5, None, 2, 3),
        (3, 2, None, None),
        (0, None, 2, None),  # 같은 조의 항
    ]


# ---------------------------------------------------------------- 구조 검증


def test_validate_structure(doc):
    issues = validate_structure(doc)
    by_code = {i.code: i for i in issues}
    assert by_code["ARTICLE_NUMBER_GAP"].message == "제6조가 없습니다."
    # 제7조에는 항 표시가 없으므로 '제7조제2항' 은 끊어진 인용
    broken = by_code["BROKEN_REFERENCE"]
    assert broken.severity == "error" and broken.article == "제5조"
    # 존재하는 인용(제2조제1항제2호), 다른 법 조문(약관규제법 제3조)은 문제 아님
    assert all(i.article != "제3조의2" for i in issues)
    assert all(i.article != "제3조" for i in issues)
    assert "NO_ADDENDUM" not in by_code


def test_validate_structure_detects_problems():
    lines = [
        "제1장 총칙",
        "제1조(목적) 목적",
        "제3장 기타",
        "제2조(정의)",
        "③ 셋째 항",
        "① 첫째 항",
        "제2조(중복) 중복된 조",
        "제3조(삭제된 조 인용) 제4조를 따르고 제1조제2항을 따른다.",
        "제4조 삭제",
        "제5조(호) 다음과 같다.",
        "1. 하나",
        "3. 셋",
        "가. 목",
        "다. 목",
        "제6조",
    ]
    text = "\n".join(lines)
    issues = validate_structure(parse_terms(text))
    found = set(codes(issues))
    assert {
        "HEADING_NUMBER_GAP",
        "ARTICLE_DUPLICATE",
        "PARAGRAPH_NUMBER_GAP",
        "REFERENCE_TO_DELETED",
        "BROKEN_REFERENCE",
        "ITEM_NUMBER_GAP",
        "EMPTY_ARTICLE",
        "MISSING_TITLE",
        "NO_ADDENDUM",
    } <= found


def test_validate_no_articles():
    issues = validate_structure(parse_terms("그냥 아무 글"))
    assert codes(issues) == ["NO_ARTICLES"] and issues[0].severity == "error"


def test_heading_numbering_continued_across_parents():
    text = "제1편 총칙\n제1장 a\n제1조(a) a\n제2편 각칙\n제2장 b\n제2조(b) b\n부칙\n제1조 시행"
    assert "HEADING_NUMBER_GAP" not in codes(validate_structure(parse_terms(text)))


# ---------------------------------------------------------------- 분석 검증


def _analysis(*clauses):
    return TermsAnalysis(clauses=list(clauses))


def test_validate_analysis_grounding(doc):
    good = ClauseAnalysis(
        article="제5조",
        category="면책·책임 제한",
        summary="서비스 중단 면책",
        risk="high",
        issues=[
            ClauseIssue(
                type="liability_exemption",
                description="전면 면책",
                # 줄바꿈·공백이 달라도 같은 문구로 인정
                quote="이로 인한 손해에 대해 어떠한 책임도 지지 않는다",
            )
        ],
    )
    issues = validate_analysis(doc, _analysis(good))
    assert not [i for i in issues if i.severity == "error"]
    assert all(i.source == "analysis" for i in issues)
    assert "NOT_ANALYZED" in codes(issues)  # 나머지 조는 분석되지 않음
    assert "제4조" not in [i.article for i in issues]  # 삭제된 조는 분석 대상 아님


def test_validate_analysis_detects_hallucination(doc):
    clauses = [
        ClauseAnalysis(article="제99조", category="기타", summary="없는 조"),
        ClauseAnalysis(
            article="제7조",
            category="해지·해제·종료",
            summary="환불 불가",
            risk="high",
            issues=[
                ClauseIssue(type="termination", description="", quote="어떠한 책임도 지지 않는다")
            ],  # 제5조의 문구
        ),
        ClauseAnalysis(article="제8조", category="분쟁 해결", summary="관할", risk="medium"),
        ClauseAnalysis(
            article="제8조",
            category="엉뚱한 분류",
            summary="중복",
            issues=[ClauseIssue(type="what", description="", quote="")],
        ),
    ]
    issues = validate_analysis(doc, _analysis(*clauses))
    by_code = {i.code: i for i in issues}
    assert by_code["UNKNOWN_ARTICLE"].article == "제99조"
    assert "제5조에 있는 문구" in by_code["QUOTE_NOT_FOUND"].message
    assert {
        "RISK_WITHOUT_ISSUE",
        "DUPLICATE_ANALYSIS",
        "UNKNOWN_CATEGORY",
        "UNKNOWN_ISSUE_TYPE",
        "MISSING_QUOTE",
        "ISSUE_WITHOUT_RISK",
    } <= set(by_code)


# ---------------------------------------------------------------- AI 분석 (가짜 LLM)


class FakeLLM(OpenAIClient):
    def __init__(self, replies):
        super().__init__("fake-model", 1000, api_key="test")
        self.replies = iter(replies)
        self.requests = []

    def build_request(self, system, messages, tools):
        return {"system": system, "messages": [m.content for m in messages], "tools": tools}

    def send(self, request):
        self.requests.append(request)
        reply = next(self.replies)
        stop = "end"
        if isinstance(reply, tuple):
            reply, stop = reply
        return LLMResponse(text=reply, tool_calls=[], stop_reason=stop, model="fake-model")


def _clauses_json(doc, labels=None):
    return json.dumps(
        {
            "clauses": [
                {
                    "article": a.label,
                    "category": "기타",
                    "summary": f"{a.label} 요약",
                    "risk": "none",
                    "issues": [],
                }
                for a in doc.articles
                if not a.deleted and (labels is None or a.label in labels)
            ]
        },
        ensure_ascii=False,
    )


OVERVIEW = json.dumps(
    {
        "document_type": "서비스 이용약관",
        "parties": ["회사", "회원"],
        "summary": "요약",
        "key_points": ["제5조 면책"],
    },
    ensure_ascii=False,
)


def test_analyze_terms_with_retry(doc):
    llm = FakeLLM(
        [
            "이건 JSON 이 아닙니다",  # 형식 오류 → 다시 요청
            "```json\n" + _clauses_json(doc) + "\n```",  # 코드블록이 붙어도 처리
            OVERVIEW,
        ]
    )
    result = analyze_terms(doc, llm=llm)
    assert len(result.clauses) == 8 and result.overview.parties == ["회사", "회원"]
    assert result.model == "fake-model"
    # 재요청에는 에러 내용이 포함되고, 조문은 '### 조 표기' 로 전달됨
    assert "JSON 형식이 잘못되었습니다" in llm.requests[1]["messages"][-1]
    assert "### 제3조의2 (개인정보 보호)" in llm.requests[0]["messages"][0]
    assert llm.requests[0]["tools"] == []
    assert not [i for i in validate_analysis(doc, result) if i.severity != "info"]


def test_analyze_terms_chunks(doc):
    chunks = chunk_articles([a for a in doc.articles if not a.deleted], max_chars=300)
    assert len(chunks) > 1
    replies = [_clauses_json(doc, {a.label for a in c}) for c in chunks] + [OVERVIEW]
    result = analyze_terms(doc, llm=FakeLLM(replies), chunk_chars=300)
    assert [c.article for c in result.clauses] == [a.label for c in chunks for a in c]


def test_analyze_terms_truncated(doc):
    with pytest.raises(AnalysisError, match="max_tokens"):
        analyze_terms(doc, llm=FakeLLM([('{"clauses": [', "max_tokens")]))


def test_extract_json():
    assert extract_json('앞 설명 {"a": {"b": 1}} 뒤 설명') == '{"a": {"b": 1}}'
    with pytest.raises(ValueError):
        extract_json("없음")


# ---------------------------------------------------------------- 파이프라인


def test_pipeline_full(doc):
    llm = FakeLLM([_clauses_json(doc), OVERVIEW])
    report = run_terms_pipeline(SAMPLE, llm=llm)
    assert report.trace_id and report.analysis and not report.analysis_error
    assert "BROKEN_REFERENCE" in codes(report.structure_issues)
    assert all(i.source == "analysis" for i in report.analysis_issues)

    from backend.tracing import get_trace

    names = [s.name for s in get_trace(report.trace_id)]
    assert names[0] == "terms_pipeline"
    assert {"구조화", "구조 검증", "AI 분석", "분석 검증", "전체 개요"} <= set(names)


def test_pipeline_analysis_failure_keeps_structure():
    class Broken(FakeLLM):
        def send(self, request):
            raise RuntimeError("API 키 없음")

    report = run_terms_pipeline(SAMPLE, llm=Broken([]))
    assert report.analysis is None and "API 키 없음" in report.analysis_error
    assert report.document.articles and report.structure_issues


def test_pipeline_without_analysis():
    report = run_terms_pipeline(SAMPLE, analyze=False)
    assert report.analysis is None and report.analysis_error is None


def test_pipeline_requires_one_input():
    with pytest.raises(ValueError):
        run_terms_pipeline()


# ---------------------------------------------------------------- 텍스트 추출 / 도구


def test_bytes_to_text():
    assert bytes_to_text("a.txt", "제1조(목적)".encode("cp949")) == "제1조(목적)"
    with pytest.raises(TextExtractionError):
        bytes_to_text("a.hwp", b"")


def test_terms_tools(monkeypatch):
    from backend.storage import save_upload
    from schema.document import DocumentKind
    from skills import execute_tool, get_tools, terms_tools

    d = save_upload("약관.pdf", b"%PDF-fake", DocumentKind.PDF)
    monkeypatch.setattr(terms_tools, "document_to_text", lambda _doc: SAMPLE)
    terms_tools._parsed.cache_clear()
    tools = {t.name: t for t in get_tools(["get_terms_outline", "get_terms_article"])}

    outline = json.loads(execute_tool(tools, "get_terms_outline", {"doc_id": d.id}).result)
    assert outline["title"] == "위드갓 서비스 이용약관"
    assert any(i["code"] == "BROKEN_REFERENCE" for i in outline["issues"])

    art = execute_tool(tools, "get_terms_article", {"doc_id": d.id, "article": "제5조"})
    assert art.result.startswith("제5조(서비스 중단)")
    missing = execute_tool(tools, "get_terms_article", {"doc_id": d.id, "article": "제99조"})
    assert missing.is_error
