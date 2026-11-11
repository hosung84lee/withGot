"""보장맵: 진료 서류를 올리면 치료 항목을 약관의 보장 규칙·조항과 연결해 그림으로 보여 줍니다."""

import json
from pathlib import Path

import streamlit as st

from backend.config import get_settings
from coverage_map import build_claim, link_claim, parse_document, policy, to_dot
from coverage_map.documents import KIND_LABEL, PRIVATE_FIELDS
from coverage_map.linker import STATUS_LABEL, article_label
from schema.coverage import Product, SourceRef
from schema.terms import TermsDocument
from terms.extract import TextExtractionError, bytes_to_text

settings = get_settings()
st.title("보장맵")
st.caption(
    "영수증·세부내역서·진단서를 올리면 치료 항목을 읽어 약관의 보장 규칙과 근거 조항에 연결합니다. "
    "LLM 없이 규칙 데이터로만 연결하며, 금액은 참고 계산입니다 (보험금 지급 판정 아님)."
)

SAMPLES = {
    "의원 외래 (급여 + 비급여)": [
        (
            "영수증.txt",
            (
                "진료비 계산서·영수증\nBOJANGIT SAMPLE V1 RECEIPT\n사례번호 | DEMO-001\n진료일 | 2026-11-02\n"
                "의료기관 | 가상한빛의원\n진료비 총액 | 605500\n공단 부담 | 42350\n환자 부담 합계 | 563150\n"
            ),
        ),
        (
            "세부내역서.txt",
            (
                "진료비 세부산정내역서\nBOJANGIT SAMPLE V1 DETAIL\n사례번호 | DEMO-001\n"
                "치료 | 외래 진찰료 | 급여 | 18500 | 5550\n치료 | 혈액 검사 | 급여 | 42000 | 12600\n"
                "치료 | 복부 MRI | 비급여 | 480000 | 480000\n치료 | 영양 주사 | 비급여 | 65000 | 65000\n"
                "환자 부담 합계 | 563150\n"
            ),
        ),
    ],
}
SAMPLES["종합병원 외래 + 약국"] = [
    (n, t.replace("가상한빛의원", "가상대학교종합병원"))
    for n, t in SAMPLES["의원 외래 (급여 + 비급여)"]
] + [
    (
        "약제비영수증.txt",
        (
            "약제비 계산서·영수증\nBOJANGIT SAMPLE V1 PHARMACY\n사례번호 | DEMO-001\n"
            "급여 본인부담 | 10000\n비급여 | 2400\n약국 환자 부담 합계 | 12400\n"
        ),
    )
]
SAMPLES["암 진단서 (C50.9 유방암) — 인터넷암 2404 와 함께"] = [
    (
        "진단서.txt",
        (
            "진단서\nBOJANGIT SAMPLE V1 DIAGNOSIS\n사례번호 | DEMO-005\n"
            "진단명 | 가상 유방의 악성신생물\n질병분류기호 | C50.9\n"
        ),
    )
]
SAMPLES["정신과 진단 (보상 제외)"] = SAMPLES["의원 외래 (급여 + 비급여)"] + [
    (
        "진단서.txt",
        (
            "진단서\nBOJANGIT SAMPLE V1 DIAGNOSIS\n사례번호 | DEMO-001\n진단명 | 가상 알코올 사용 장애\n"
            "질병분류기호 | F10.2\n"
        ),
    )
]


def _grounded(link) -> str:
    target = link.exclusion or link.rule
    if target is None:
        return ""
    return "✅ 확인" if target.status == "confirmed" else "검토 필요"


def _md(text: str) -> str:
    """마크다운에서 ~ 가 취소선이 되지 않게 (F04~F09)."""
    return text.replace("~", r"\~")


@st.cache_resource(show_spinner=False)
def _terms(key: str, _data: bytes) -> TermsDocument:  # key: 파일 해시 (bytes 해시 계산 생략)
    return policy.load_terms(_data)


@st.cache_data(show_spinner=False)
def _read(path: str) -> bytes:
    return Path(path).read_bytes()


# --- 약관 PDF 와 보장 데이터 ---
with st.sidebar:
    st.markdown("**연결할 약관**")
    samples = policy.sample_policies()
    names = [p.stem for p in samples] + ["PDF 직접 올리기"]
    default = next((i for i, p in enumerate(samples) if "2605갱신형" in p.stem), 0)
    choice = st.selectbox("약관 PDF", names, index=default)
    if choice == "PDF 직접 올리기":
        up_pdf = st.file_uploader("약관 PDF", type=["pdf"], label_visibility="collapsed")
        pdf_data, pdf_name = (up_pdf.getvalue(), up_pdf.name) if up_pdf else (None, None)
    else:
        path = samples[names.index(choice)]
        pdf_data, pdf_name = _read(str(path)), path.name

if pdf_data is None:
    st.info("사이드바에서 약관 PDF 를 올려 주세요.")
    st.stop()

with st.spinner(f"약관 구조화 중… {pdf_name} (처음 한 번은 1분 안팎)"):
    pdf_key = policy.file_hash(pdf_data)
    try:
        terms_doc = _terms(pdf_key, pdf_data)
    except TextExtractionError as e:  # 손상된 PDF·스캔본 등
        st.error(f"{pdf_name}: {e}")
        st.stop()
golden = policy.golden_for(terms_doc)
cached = policy.cached_sections(pdf_key)

with st.sidebar:
    st.caption(
        f"약관 {len(terms_doc.parts)}개 · 조 {len(terms_doc.body_articles)}개"
        + (
            (" · 정답 초안 있음 (진단보험금)" if policy.is_draft(golden) else " · 정답 데이터 있음")
            if golden
            else ""
        )
        + (f" · AI 추출 {len(cached)}묶음" if cached else "")
    )
    covered = set(cached) | policy.golden_keys(terms_doc, golden)
    todo = [b.key for b in policy.bundles(terms_doc) if b.key not in covered]
    with st.expander("AI 로 보장 규칙 추출", expanded=not (golden or cached)):
        st.caption(
            "정답 데이터가 없는 보장 묶음(약관 · 보장종목)을 OpenAI 로 추출합니다 (동시에 여러 묶음). "
            "API 비용이 듭니다. 결과는 캐시되어 약관 분석 화면과 함께 씁니다."
        )
        picked = st.multiselect("추출할 묶음", todo, default=todo)
        no_key = not settings.openai_api_key
        if st.button("추출", type="primary", disabled=not picked or no_key):
            with st.status("보장 규칙 추출 중…", expanded=True) as s:
                errors = policy.extract_missing(
                    pdf_key,
                    terms_doc,
                    picked,
                    model=settings.openai_model,
                    on_progress=lambda i, n, b: st.write(f"▶ {i}/{n} {b.key}"),
                )
                for key, msg in errors.items():
                    st.error(f"{key}: {msg[:300]}")
                s.update(label="완료", state="error" if errors else "complete")
            if not errors:
                st.rerun()
        if no_key:
            st.caption(".env 에 OPENAI_API_KEY 가 없어 추출할 수 없습니다.")
    with st.expander("보장 데이터 JSON 직접 올리기"):
        up_product = st.file_uploader(
            "보장 데이터 JSON", type=["json"], label_visibility="collapsed"
        )

product: Product | None = None
if up_product is not None:
    try:
        data = json.loads(up_product.getvalue().decode("utf-8"))
        product = Product.model_validate(data.get("product", data))
    except Exception as e:  # noqa: BLE001 — 사용자 파일 형식 오류를 화면에 표시
        st.error(f"보장 데이터를 읽지 못했습니다: {e}")
else:
    product = policy.build_product(terms_doc, pdf_key, golden)
if product is None:
    st.info(
        "이 약관은 아직 보장 규칙이 없습니다. 사이드바의 'AI 로 보장 규칙 추출' 에서 "
        "보장 묶음을 골라 추출하세요."
    )
    st.stop()

report = policy.ground(product, terms_doc)  # 원문 근거 확인 → status confirmed / needs_review
product = report.product
with st.sidebar:
    sections = sorted({r.section for c in product.coverages for r in c.risks if r.section})
    # 기본은 정답 데이터(사람 검토)가 있는 보장종목
    preferred = {k.section for c in golden.coverages for k in c.risks} if golden else set()
    default_sec = next((i for i, s in enumerate(sections) if s in preferred), 0)
    section = st.selectbox("보장종목", sections, index=default_sec) if sections else None
    st.caption(f"원문 근거 확인 {report.confirmed}건 · 검토 필요 {report.needs_review}건")


def _title(src: SourceRef) -> str | None:
    found = policy.source_text(terms_doc, src)
    return found[0] if found and src.article else None


# --- 서류 올리기 ---
c1, c2 = st.columns([3, 2])
with c1:
    files = st.file_uploader(
        "진료 서류 (PDF·TXT, 여러 개)",
        type=["pdf", "txt"],
        accept_multiple_files=True,
        help="영수증과 세부내역서를 함께 올려야 치료 항목별로 연결됩니다. 진단서는 보상 제외 확인에 씁니다.",
    )
with c2:
    sample = st.selectbox("또는 가상 샘플 서류", ["(선택 안 함)", *SAMPLES])

docs_input: list[tuple[str, str]] = []
for f in files or []:
    try:
        docs_input.append((f.name, bytes_to_text(f.name, f.getvalue())))
    except TextExtractionError as e:
        st.error(f"{f.name}: {e}")
if not docs_input and sample in SAMPLES:
    docs_input = SAMPLES[sample]
if not docs_input:
    st.info("서류를 올리거나 가상 샘플을 고르면 보장맵이 나옵니다.")
    st.stop()

docs = [parse_document(name, text) for name, text in docs_input]
claim = build_claim(docs)
cmap = link_claim(claim, product, section=section)

# --- 요약 ---
st.divider()
m = st.columns(5)
m[0].metric("서류", len(docs))
m[1].metric("치료 항목", len(claim.items))
m[2].metric("보장 연결", sum(link.status == "linked" for link in cmap.links))
m[3].metric("확인·제외", sum(link.status in ("check", "excluded") for link in cmap.links))
diag_links = [x for x in cmap.links if x.item.benefit == "diagnosis" and x.status == "linked"]
if cmap.estimates or not diag_links:
    m[4].metric("참고 계산", f"{sum(e.payable for e in cmap.estimates):,}원")
else:
    m[4].metric(
        "진단 보장",
        f"{len(diag_links)}건",
        help="정액형은 가입금액 기준이라 금액을 계산하지 않습니다.",
    )
info = [
    f"진료일 {claim.visit_date}" if claim.visit_date else None,
    f"{claim.facility} ({claim.facility_type or '종류 미상'})" if claim.facility else None,
    ("입원" if claim.setting == "hospitalization" else "통원") if claim.items else None,
    f"진단 {', '.join(claim.kcd)}" if claim.kcd else None,
]
st.caption(" · ".join(x for x in info if x))
for w in claim.warnings:
    st.warning(_md(w))
for code, ex in cmap.claim_exclusions:
    msg = f"진단 {code} 는 보상하지 않는 질병 「{ex.description}」 에 해당합니다 ({article_label(ex.source)})."
    if ex.exception:
        msg += f" 예외: {ex.exception}"
    st.error(_md(msg))

# --- 맵 ---
st.subheader("보장맵")
st.caption(
    "초록 = 보장 연결 · 노랑 = 확인 필요 · 회색 = 이 약관 보상 대상 아님 · 빨강 = 보상 제외. 점선은 근거 조항."
)
st.graphviz_chart(to_dot(cmap, title_of=_title), use_container_width=True)

# --- 항목별 연결 ---
st.subheader("치료 항목별 연결")
icon = {"linked": "🟢", "check": "🟡", "not_covered": "⚪", "excluded": "🔴"}
st.dataframe(
    [
        {
            "": icon[link.status],
            "치료 항목": link.item.name,
            "구분": {"covered": "급여", "uncovered": "비급여", "diagnosis": "진단"}.get(
                link.item.benefit, "?"
            ),
            "환자 부담(원)": link.item.patient if link.item.benefit != "diagnosis" else None,
            "상태": STATUS_LABEL[link.status],
            "약관 보장": link.rule.name if link.rule else "",
            "근거 조항": ", ".join(article_label(s) for s in link.sources),
            "원문 근거": _grounded(link),
            "메모": " / ".join(link.notes),
        }
        for link in cmap.links
    ],
    hide_index=True,
    width="stretch",
)

if cmap.estimates:
    st.subheader("참고 계산")
    for e in cmap.estimates:
        line = f"**{e.rule.name}** — 대상 {e.covered:,}원 − 공제 {e.deductible:,}원 = **{e.payable:,}원**"
        st.markdown(line)
        for n in e.notes:
            st.caption(f"· {n}")

# --- 근거 조항 (약관 PDF 원문) ---
st.subheader("근거 조항")
st.caption(f"{pdf_name} 에서 구조화한 원문입니다. 노란 표시는 보장 데이터가 인용한 문구입니다.")
seen = set()
for link in cmap.links:
    for src in link.sources:
        key = (src.part, src.section, src.article, src.paragraph, src.quote)
        if key in seen:
            continue
        seen.add(key)
        art = policy.source_text(terms_doc, src)  # (제목, 원문) — 조 또는 별표
        where = article_label(src) + (f" ({art[0]})" if art and art[0] and src.article else "")
        where += f" 《{src.section}》" if src.section else ""
        with st.expander(f"{where} — {src.part}" + ("" if art else "  ⚠️ 원문에서 못 찾음")):
            if art:
                body = policy.highlight(art[1], src.quote)
                st.markdown(
                    f"<div style='white-space:pre-wrap;font-size:14px;line-height:1.6'>{body}</div>",
                    unsafe_allow_html=True,
                )
            elif src.quote:
                st.markdown(f"> {_md(src.quote)}")

with st.expander("읽은 서류 내용"):
    for d in docs:
        shown = {k: v for k, v in d.fields.items() if k not in PRIVATE_FIELDS}
        st.markdown(f"**{KIND_LABEL[d.kind]}** · `{d.filename}`")
        st.json(shown, expanded=False)
    st.caption("이름·환자번호 등 개인정보 항목은 화면에 표시하지 않습니다.")
