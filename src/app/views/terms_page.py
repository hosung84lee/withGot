"""약관 분석 화면: 원문 → 구조화 → 구조 검증 → AI 사고보장 추출(사고보장 테이블 데이터)."""

import time
from pathlib import Path

import streamlit as st

from app import coverage_view, terms_viewer
from backend.config import get_settings
from backend.storage import get_document, list_documents
from coverage_extract.extractor import failed_issues
from coverage_extract.grounding import GroundingReport
from coverage_map import policy
from schema.document import DocumentKind
from schema.terms import TermsReport, ValidationIssue
from terms.extract import TextExtractionError, bytes_to_text, document_to_text
from terms.pipeline import STEPS, run_terms_pipeline

VIEWER_HEIGHT = 1400

st.title("약관 분석")
st.caption(
    "약관 원문을 조·항·호·목으로 구조화하고 구조를 검증한 뒤, AI 로 보장 규칙·보상 제외를 뽑아 "
    "사고보장 테이블 데이터로 만듭니다. 뽑은 내용은 원문에 근거가 있는지 다시 확인합니다."
)

settings = get_settings()
SEVERITY_ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}

with st.sidebar:
    extract = st.toggle(
        "AI 사고보장 추출",
        value=True,
        help="보장 조를 보장종목 단위로 묶어 OpenAI 로 지급 규칙·보상 제외를 뽑습니다 "
        "(묶음 동시 처리, API 비용). 끄면 구조화와 구조 검증만 합니다. 결과는 캐시되어 보장맵에서도 씁니다.",
    )
    model = st.text_input("OpenAI 모델", value=settings.openai_model, disabled=not extract)

tab_file, tab_text, tab_doc, tab_sample = st.tabs(
    ["파일 올리기", "텍스트 붙여넣기", "문서 보관함", "샘플 약관 구조 뷰어"]
)
run_args: dict | None = None
cache_key: str | None = None


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
            cache_key = policy.file_hash(text.encode("utf-8"))
        else:
            st.warning("약관 원문을 넣어 주세요.")

with tab_file:
    up = st.file_uploader(
        "약관 PDF 또는 TXT",
        type=["pdf", "txt"],
        help="올리면 바로 처리합니다. 큰 약관 PDF 는 텍스트 추출에 1분 안팎 걸립니다 (같은 PDF 는 캐시).",
    )
    file_key = f"{up.name}:{up.size}" if up else None
    again = st.button("다시 분석", disabled=up is None)
    # 새 파일이 올라오면 버튼 없이 바로 처리
    if up is not None and (again or st.session_state.get("terms_file_key") != file_key):
        st.session_state.terms_pending_key = file_key  # 끝까지 성공하면 terms_file_key 로
        try:
            with st.spinner(f"{up.name} 텍스트 추출 중…"):
                t0 = time.time()
                raw = up.getvalue()
                text = (  # PDF 는 파일 해시로 텍스트 캐시 (같은 PDF 다시 올리면 바로)
                    policy.policy_text(raw)
                    if up.name.lower().endswith(".pdf")
                    else bytes_to_text(up.name, raw)
                )
                run_args = {"text": text, "source": up.name}
                cache_key = policy.file_hash(raw)
                st.session_state.terms_viewer_extract_s = time.time() - t0
            st.session_state.terms_viewer_pages = terms_viewer.pdf_pages(raw)
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
    n_steps = len(STEPS[:2]) + (1 if extract else 0)
    with st.status("약관 처리 중…", expanded=True) as status:
        progress = st.progress(0)

        def on_step(i: int, name: str) -> None:
            st.write(f"▶ {name}")
            progress.progress(i / n_steps)

        try:
            report = run_terms_pipeline(**run_args, analyze=False, on_step=on_step)
        except (TextExtractionError, LookupError, ValueError) as e:
            status.update(label="실패", state="error")
            st.error(str(e))
            st.stop()
        terms_doc = report.document

        if "text" in run_args:
            viewer_text, viewer_name = run_args["text"], run_args["source"]
        else:
            d = get_document(run_args["doc_id"])
            viewer_text, viewer_name = document_to_text(d), d.filename
            raw = Path(d.path).read_bytes() if Path(d.path).exists() else viewer_text.encode()
            cache_key = policy.file_hash(raw)
            st.session_state.terms_viewer_pages = terms_viewer.pdf_pages(raw)
        st.session_state.terms_viewer_html = terms_viewer.html_for_text(
            viewer_name,
            viewer_text,
            pages=st.session_state.pop("terms_viewer_pages", 0),
            extract_s=st.session_state.pop("terms_viewer_extract_s", 0),
        )

        coverage: GroundingReport | None = None
        note = ""
        failed = False
        if extract:
            on_step(2, "AI 사고보장 추출")
            keys = [b.key for b in policy.bundles(terms_doc)]
            if not keys:
                note = "보장 조(보상내용·보험금의 지급사유 등)를 찾지 못해 추출할 묶음이 없습니다."
            elif not settings.openai_api_key:
                note = ".env 에 OPENAI_API_KEY 가 없어 AI 사고보장 추출을 하지 못했습니다."
                failed = True
            else:
                errors = policy.extract_missing(
                    cache_key,
                    terms_doc,
                    keys,
                    model=model or None,
                    on_progress=lambda i, n, b: st.write(f"　· 묶음 {i}/{n} 끝: {b.key}"),
                )
                product = policy.build_product(terms_doc, cache_key, use_golden=False)
                if product:
                    coverage = policy.ground(product, terms_doc)
                    coverage.issues += failed_issues(errors)
                failed = bool(errors)
                if errors and not product:
                    note = "모든 묶음 추출에 실패했습니다: " + next(iter(errors.values()))[:300]
        progress.progress(1.0)
        status.update(
            label="완료" + (" (일부 실패)" if failed else ""),
            state="error" if failed else "complete",
            expanded=False,
        )
    st.session_state.terms_report = report
    st.session_state.terms_coverage = coverage
    st.session_state.terms_coverage_note = note
    if "terms_pending_key" in st.session_state:
        st.session_state.terms_file_key = st.session_state.pop("terms_pending_key")


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
coverage: GroundingReport | None = st.session_state.get("terms_coverage")
coverage_note: str = st.session_state.get("terms_coverage_note", "")

doc = report.document
st.divider()
st.subheader(doc.title or report.source)
issues = report.structure_issues
product = coverage.product if coverage else None
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("조", len(doc.body_articles))
c2.metric("구조 오류·경고", sum(i.severity in ("error", "warning") for i in issues))
c3.metric("지급 규칙", len(product.rules()) if product else "-")
c4.metric("보상 제외", len(product.exclusions()) if product else "-")
c5.metric(
    "원문 근거 확인",
    f"{coverage.confirmed}/{coverage.confirmed + coverage.needs_review}" if coverage else "-",
)
st.page_link(
    "views/trace_page.py", label="Trace 보기", icon="🔍", query_params={"trace_id": report.trace_id}
)
failed_bundles = [i for i in coverage.issues if i.code == "EXTRACTION_FAILED"] if coverage else []
if failed_bundles:
    st.warning(
        f"보장 묶음 {len(failed_bundles)}개 추출에 실패해 빠졌습니다: "
        + ", ".join(i.target for i in failed_bundles)
        + f" — {failed_bundles[0].message[:200]}"
    )
if coverage_note:
    st.info(coverage_note)

t_viewer, t_cov, t_tables, t_struct, t_valid, t_raw = st.tabs(
    ["구조 뷰어", "사고보장 (AI 추출)", "사고보장 테이블", "조 목록", "검증", "JSON"]
)

with t_viewer:
    viewer_html = st.session_state.get("terms_viewer_html")
    if viewer_html:
        st.iframe(viewer_html, height=VIEWER_HEIGHT)  # 우리 템플릿 + JSON 데이터 (원문은 esc 처리)
    else:
        st.info("다시 분석하면 구조 뷰어가 나옵니다.")

with t_cov:
    if not product:
        st.info(coverage_note or "사이드바에서 'AI 사고보장 추출' 을 켜고 다시 분석하세요.")
    else:
        st.caption(
            "✅ = 인용문·숫자가 약관 원문에서 확인됨 · 🟡 = 검토 필요. "
            "확인됨은 '원문에 근거 있음' 이지 업무 검토 완료가 아닙니다."
        )
        st.markdown(f"**지급 규칙 {len(product.rules())}개**")
        st.dataframe(coverage_view.rule_rows(product), hide_index=True, width="stretch")
        st.markdown(f"**보상하지 않는 사항 {len(product.exclusions())}개**")
        st.dataframe(coverage_view.exclusion_rows(product), hide_index=True, width="stretch")
        st.page_link("views/coverage_map_page.py", label="이 결과로 보장맵 보기", icon="🗺️")

with t_tables:
    if not product:
        st.info("사고보장 데이터가 없습니다.")
    else:
        st.caption(
            "사고보장 데이터를 관계형 테이블(coverage_store)에 넣은 모양입니다 "
            "(보장 → 위험률 → 위험유형 → 참조조건·급부·공제, 담보코드 → KCD, 근거)."
        )
        tables = coverage_view.store_tables(product)
        st.caption(" · ".join(f"{n} {len(rows)}" for n, rows in tables.items()))
        for name, rows in tables.items():
            if rows:
                with st.expander(f"{name} ({len(rows)}행)", expanded=name == "benefit_rule"):
                    st.dataframe(rows, hide_index=True, width="stretch")

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
    if coverage:
        st.markdown("**근거 검증** — AI 가 뽑은 규칙의 조·항·인용문·숫자가 원문에 있는지")
        rows = [
            {"": SEVERITY_ICON[i.severity], "대상": i.target, "코드": i.code, "내용": i.message}
            for i in coverage.issues
        ]
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.success("문제 없음")

with t_raw:
    if product:
        st.markdown(
            "**사고보장 데이터** (`schema.coverage.Product`, 사고보장 테이블에 그대로 저장 가능)"
        )
        st.json(product.model_dump(mode="json"), expanded=False)
        d1, d2 = st.columns(2)
        d1.download_button(
            "사고보장 JSON 다운로드",
            product.model_dump_json(indent=2),
            file_name=f"coverage_{report.trace_id}.json",
            mime="application/json",
        )
        d2.download_button(
            "사고보장 테이블 SQLite 다운로드",
            coverage_view.sqlite_bytes(product),
            file_name=f"coverage_{report.trace_id}.db",
            mime="application/vnd.sqlite3",
        )
    else:
        st.info("사고보장 데이터가 없습니다 (AI 사고보장 추출을 켜고 다시 분석하세요).")
    with st.expander("구조화 결과 JSON (약관 조·항·호 구조)"):
        st.json(report.model_dump(mode="json"), expanded=False)
        st.download_button(
            "구조화 JSON 다운로드",
            report.model_dump_json(indent=2),
            file_name=f"terms_{report.trace_id}.json",
            mime="application/json",
        )
