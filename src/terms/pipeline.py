"""약관 처리 파이프라인: 텍스트 추출 → 구조화 → 구조 검증 → (AI 분석 → 분석 검증).

전체 실행이 workflow span 하나로 기록되어 Trace 화면에서 단계별로 볼 수 있습니다.
"""

from collections.abc import Callable

from agent.llm import OpenAIClient
from backend.storage import get_document
from backend.tracing import span
from schema.terms import TermsReport
from terms.analyzer import DEFAULT_CHUNK_CHARS, AnalysisError, analyze_terms
from terms.extract import document_to_text
from terms.parser import parse_terms
from terms.validator import validate_analysis, validate_structure

STEPS = ["구조화", "구조 검증", "AI 분석", "분석 검증"]


def _counts(issues) -> dict[str, int]:
    return {s: sum(i.severity == s for i in issues) for s in ("error", "warning", "info")}


def run_terms_pipeline(
    text: str | None = None,
    *,
    doc_id: int | None = None,
    source: str = "직접 입력",
    analyze: bool = True,
    llm: OpenAIClient | None = None,  # 테스트용 가짜 LLM 등. 없으면 model 로 생성
    model: str | None = None,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    on_step: Callable[[int, str], None] | None = None,
) -> TermsReport:
    """text 또는 doc_id(문서 보관함의 PDF) 중 하나를 받습니다.

    AI 분석이 실패해도(키 없음, 응답 형식 오류 등) 구조화·구조 검증 결과는 돌려주고,
    실패 사유를 report.analysis_error 에 남깁니다.
    """
    if (text is None) == (doc_id is None):
        raise ValueError("text 와 doc_id 중 하나만 주세요.")
    emit = on_step or (lambda *_: None)

    with span(
        "workflow",
        "terms_pipeline",
        input={"source": source, "doc_id": doc_id, "analyze": analyze, "text": text},
    ) as wf:
        if doc_id is not None:
            with span("step", "텍스트 추출", input={"doc_id": doc_id}) as s:
                doc = get_document(doc_id)
                source = doc.filename
                text = document_to_text(doc)
                s.set(output={"chars": len(text)})
        assert text is not None

        emit(0, STEPS[0])
        with span("step", "구조화", input={"chars": len(text)}) as s:
            terms = parse_terms(text)
            s.set(
                output={
                    "title": terms.title,
                    "headings": len(terms.headings),
                    "articles": len(terms.articles),
                    "addenda": len(terms.addenda),
                    "appendices": len(terms.appendices),
                }
            )

        emit(1, STEPS[1])
        with span("step", "구조 검증") as s:
            structure_issues = validate_structure(terms)
            counts = _counts(structure_issues)
            s.set(output=counts, status="warning" if counts["error"] else None)

        report = TermsReport(
            trace_id=wf.trace_id, source=source, document=terms, structure_issues=structure_issues
        )

        if analyze and terms.articles:
            emit(2, STEPS[2])
            try:
                with span("step", "AI 분석") as s:
                    report.analysis = analyze_terms(
                        terms,
                        llm=llm,
                        model=model,
                        chunk_chars=chunk_chars,
                        on_progress=lambda i, n: emit(2, f"AI 분석 {i}/{n} (마지막은 전체 개요)"),
                    )
                    s.set(output={"clauses": len(report.analysis.clauses)})
            except AnalysisError as e:
                report.analysis_error = str(e)
            except Exception as e:  # noqa: BLE001  API 키 없음, 네트워크 등. trace 에는 기록됨
                report.analysis_error = f"{type(e).__name__}: {e}"

            if report.analysis:
                emit(3, STEPS[3])
                with span("step", "분석 검증") as s:
                    report.analysis_issues = validate_analysis(terms, report.analysis)
                    counts = _counts(report.analysis_issues)
                    s.set(output=counts, status="warning" if counts["error"] else None)

        wf.set(
            output={
                "articles": len(terms.articles),
                **_counts(report.issues),
                "analysis_error": report.analysis_error,
            },
            status="warning" if report.analysis_error else None,
        )
    return report
