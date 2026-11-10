"""약관 분석 화면: 원문 입력 → 구조화 → 검증 → AI 분석."""

import time
from pathlib import Path

import streamlit as st

from app import terms_viewer
from backend.config import get_settings
from backend.storage import get_document, list_documents
from schema.document import DocumentKind
from schema.terms import UNFAIR_TYPES, TermsReport, ValidationIssue
from terms.extract import TextExtractionError, bytes_to_text, document_to_text
from terms.pipeline import STEPS, run_terms_pipeline

VIEWER_HEIGHT = 1400

st.title("약관 분석")
st.caption(
    "약관 원문을 조·항·호·목으로 구조화하고, 구조를 검증한 뒤 AI 로 조항별 위험을 검토합니다."
)

settings = get_settings()
SEVERITY_ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}
RISK_LABEL = {"none": "✅ 없음", "low": "🟡 낮음", "medium": "🟠 중간", "high": "🔴 높음"}

with st.sidebar:
    analyze = st.toggle(
        "AI 분석 실행", value=True, help="끄면 구조화와 구조 검증만 합니다 (API 키 불필요)."
    )
    model = st.text_input("OpenAI 모델", value=settings.openai_model, disabled=not analyze)

tab_file, tab_text, tab_doc, tab_sample = st.tabs(
    ["파일 올리기", "텍스트 붙여넣기", "문서 보관함", "샘플 약관 구조 뷰어"]
)
run_args: dict | None = None


with tab_sample:
    pdfs = terms_viewer.sample_pdfs()
    st.caption(
        f"삼성생명 약관 PDF {len(pdfs)}개를 구조화·검증한 결과입니다 (LLM 없음). "
        "원문 분류 지도, 조 트리, 인용, 검증 결과를 볼 수 있습니다."
    )
    have = terms_viewer.SAMPLE_HTML.exists()
    if st.button("다시 만들기" if have else "뷰어 만들기", disabled=not pdfs):
        with st.status("약관 PDF 구조화 중… (큰 약관 하나에 1분 안팎)", expanded=True) as s:
            terms_viewer.build_sample_html(lambda i, n, name: st.write(f"▶ {i + 1}/{n} {name}"))
            s.update(label="완료", state="complete", expanded=False)
        have = True
    if have:
        st.iframe(terms_viewer.SAMPLE_HTML, height=VIEWER_HEIGHT)
    elif not pdfs:
        st.info(f"약관 PDF 가 없습니다: {terms_viewer.PDF_DIR}")
    else:
        st.info("아직 만든 뷰어가 없습니다. '뷰어 만들기' 를 누르세요.")

with tab_text, st.form("terms_text"):
    text = st.text_area("약관 원문", height=300, placeholder="제1조(목적) ...")
    if st.form_submit_button("분석", type="primary"):
        if text.strip():
            run_args = {"text": text, "source": "직접 입력"}
        else:
            st.warning("약관 원문을 넣어 주세요.")

with tab_file:
    up = st.file_uploader(
        "약관 PDF 또는 TXT",
        type=["pdf", "txt"],
        help="올리면 바로 구조화합니다. 큰 약관 PDF 는 텍스트 추출에 1분 안팎 걸립니다.",
    )
    file_key = f"{up.name}:{up.size}" if up else None
    again = st.button("다시 분석", disabled=up is None)
    # 새 파일이 올라오면 버튼 없이 바로 처리
    if up is not None and (again or st.session_state.get("terms_file_key") != file_key):
        st.session_state.terms_file_key = file_key
        try:
            with st.spinner(f"{up.name} 텍스트 추출 중…"):
                t0 = time.time()
                run_args = {"text": bytes_to_text(up.name, up.getvalue()), "source": up.name}
                st.session_state.terms_viewer_extract_s = time.time() - t0
            st.session_state.terms_viewer_pages = terms_viewer.pdf_pages(up.getvalue())
        except TextExtractionError as e:
            st.error(str(e))

with tab_doc:
    pdfs = [d for d in list_documents() if d.kind == DocumentKind.PDF]
    if not pdfs:
        st.info("보관함에 PDF 가 없습니다. Agent 화면의 사이드바에서 올릴 수 있습니다.")
    else:
        with st.form("terms_doc"):
            doc = st.selectbox("문서", pdfs, format_func=lambda d: f"#{d.id} {d.filename}")
            if st.form_submit_button("분석", type="primary"):
                run_args = {"doc_id": doc.id}

if run_args:
    steps = STEPS if analyze else STEPS[:2]
    with st.status("약관 처리 중…", expanded=True) as status:
        progress = st.progress(0)

        def on_step(i: int, name: str) -> None:
            st.write(f"▶ {name}")
            progress.progress(i / len(steps))

        try:
            report = run_terms_pipeline(
                **run_args,
                analyze=analyze,
                model=model or None,
                on_step=on_step,
            )
        except (TextExtractionError, LookupError, ValueError) as e:
            status.update(label="실패", state="error")
            st.error(str(e))
            st.stop()
        progress.progress(1.0)
        if "text" in run_args:
            viewer_text, viewer_name = run_args["text"], run_args["source"]
        else:
            d = get_document(run_args["doc_id"])
            viewer_text, viewer_name = document_to_text(d), d.filename
        pages = st.session_state.pop("terms_viewer_pages", 0)
        if "doc_id" in run_args and Path(d.path).exists():
            pages = terms_viewer.pdf_pages(Path(d.path).read_bytes())
        st.session_state.terms_viewer_html = terms_viewer.html_for_text(
            viewer_name,
            viewer_text,
            pages=pages,
            extract_s=st.session_state.pop("terms_viewer_extract_s", 0),
        )
        status.update(
            label="완료" if not report.analysis_error else "완료 (AI 분석 실패)",
            state="complete" if not report.analysis_error else "error",
            expanded=False,
        )
    st.session_state.terms_report = report


def _issue_table(issues: list[ValidationIssue]) -> None:
    order = {"error": 0, "warning": 1, "info": 2}
    rows = [
        {
            "": SEVERITY_ICON[i.severity],
            "위치": i.article or "",
            "코드": i.code,
            "내용": i.message,
            "줄": i.line,
        }
        for i in sorted(issues, key=lambda i: order[i.severity])
    ]
    st.dataframe(rows, hide_index=True, width="stretch")


report: TermsReport | None = st.session_state.get("terms_report")
if not report:
    st.stop()

doc = report.document
st.divider()
st.subheader(doc.title or report.source)
issues = report.issues
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("조", len(doc.body_articles))
c2.metric("부칙 조", len(doc.articles) - len(doc.body_articles))
c3.metric("오류", sum(i.severity == "error" for i in issues))
c4.metric("경고", sum(i.severity == "warning" for i in issues))
high = sum(c.risk == "high" for c in report.analysis.clauses) if report.analysis else "-"
c5.metric("고위험 조항", high)
st.page_link(
    "views/trace_page.py", label="Trace 보기", icon="🔍", query_params={"trace_id": report.trace_id}
)
if report.analysis_error:
    st.error(f"AI 분석 실패: {report.analysis_error}")

t_viewer, t_struct, t_valid, t_analysis, t_raw = st.tabs(
    ["구조 뷰어", "조 목록", "검증", "AI 분석", "JSON"]
)

with t_viewer:
    viewer_html = st.session_state.get("terms_viewer_html")
    if viewer_html:
        st.iframe(viewer_html, height=VIEWER_HEIGHT)  # 우리 템플릿 + JSON 데이터 (원문은 esc 처리)
    else:
        st.info("다시 분석하면 구조 뷰어가 나옵니다.")

with t_struct:
    if doc.preamble:
        st.caption(doc.preamble)
    current_path: list[str] = []
    for a in doc.articles:
        if a.path != current_path and a.path:
            st.markdown(f"#### {' › '.join(a.path)}")
        current_path = a.path
        issue_count = sum(1 for i in issues if i.article == a.label)
        label = (
            f"{a.label}" + (f" ({a.title})" if a.title else "") + (" — 삭제" if a.deleted else "")
        )
        if issue_count:
            label += f"  ⚠️ {issue_count}"
        with st.expander(label):
            st.text(a.full_text() or "(본문 없음)")
            if a.references:
                st.caption("인용: " + ", ".join(r.text for r in a.references))
    for t in doc.addendum_text:
        with st.expander("부칙"):
            st.text(t)
    for x in doc.appendices:
        with st.expander(x.label):
            st.text(x.text)

with t_valid:
    st.markdown("**구조 검증** — 번호 누락·중복, 끊어진 조항 인용 등")
    if report.structure_issues:
        _issue_table(report.structure_issues)
    else:
        st.success("문제 없음")
    if report.analysis:
        st.markdown("**분석 검증** — AI 분석이 원문에 근거하는지 (없는 조, 원문에 없는 인용구 등)")
        if report.analysis_issues:
            _issue_table(report.analysis_issues)
        else:
            st.success("문제 없음")

with t_analysis:
    an = report.analysis
    if not an:
        st.info("AI 분석 결과가 없습니다.")
    else:
        ov = an.overview
        st.markdown(
            f"**유형:** {ov.document_type}  ·  **당사자:** {', '.join(ov.parties)}  ·  "
            f"**모델:** `{an.model}`"
        )
        st.info(ov.summary)
        for p in ov.key_points:
            st.markdown(f"- {p}")
        risks = st.multiselect(
            "위험도",
            list(RISK_LABEL),
            default=["high", "medium", "low"],
            format_func=RISK_LABEL.get,
        )
        flagged = {i.article for i in report.analysis_issues if i.severity == "error"}
        for c in an.clauses:
            if c.risk not in risks:
                continue
            mark = " ❗검증 실패" if c.article in flagged else ""
            with st.expander(f"{RISK_LABEL[c.risk]}  {c.article} · {c.category}{mark}"):
                st.write(c.summary)
                for i in c.issues:
                    st.markdown(f"**{UNFAIR_TYPES.get(i.type, i.type)}** — {i.description}")
                    st.markdown(f"> {i.quote}")
                    if i.legal_basis:
                        st.caption(i.legal_basis)

with t_raw:
    st.json(report.model_dump(mode="json"), expanded=False)
    st.download_button(
        "JSON 다운로드",
        report.model_dump_json(indent=2),
        file_name=f"terms_{report.trace_id}.json",
        mime="application/json",
    )
