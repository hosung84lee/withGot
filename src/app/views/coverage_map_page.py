"""보장맵: 진료 서류를 올리면 치료 항목을 약관의 보장 규칙·조항과 연결해 그림으로 보여 줍니다."""

import streamlit as st

from coverage_map import build_claim, link_claim, load_product, parse_document, to_dot
from coverage_map.documents import KIND_LABEL, PRIVATE_FIELDS
from coverage_map.linker import STATUS_LABEL, article_label
from schema.coverage import Product
from terms.extract import TextExtractionError, bytes_to_text

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
SAMPLES["정신과 진단 (보상 제외)"] = SAMPLES["의원 외래 (급여 + 비급여)"] + [
    (
        "진단서.txt",
        (
            "진단서\nBOJANGIT SAMPLE V1 DIAGNOSIS\n사례번호 | DEMO-001\n진단명 | 가상 알코올 사용 장애\n"
            "질병분류기호 | F10.2\n"
        ),
    )
]


def _md(text: str) -> str:
    """마크다운에서 ~ 가 취소선이 되지 않게 (F04~F09)."""
    return text.replace("~", r"\~")


@st.cache_resource
def _default_product() -> Product:
    return load_product()


# --- 약관(보장) 고르기 ---
with st.sidebar:
    st.markdown("**연결할 약관 보장**")
    up_product = st.file_uploader(
        "보장 데이터 JSON (선택)",
        type=["json"],
        help="사고보장 추출 결과(`python -m coverage_extract … --out`)를 올리면 그 약관으로 연결합니다.",
    )
    product = _default_product()
    if up_product is not None:
        try:
            import json

            data = json.loads(up_product.getvalue().decode("utf-8"))
            product = Product.model_validate(data.get("product", data))
        except Exception as e:  # noqa: BLE001 — 사용자 파일 형식 오류를 화면에 표시
            st.error(f"보장 데이터를 읽지 못했습니다: {e}")
    sections = sorted({r.section for c in product.coverages for r in c.risks if r.section})
    section = st.selectbox("보장종목", sections) if sections else None
    st.caption(f"{product.name}" + (" · 정답 데이터(사람 검토)" if up_product is None else ""))

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
m[4].metric("참고 계산", f"{sum(e.payable for e in cmap.estimates):,}원")
info = [
    f"진료일 {claim.visit_date}" if claim.visit_date else None,
    f"{claim.facility} ({claim.facility_type or '종류 미상'})" if claim.facility else None,
    "입원" if claim.setting == "hospitalization" else "통원",
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
st.graphviz_chart(to_dot(cmap), use_container_width=True)

# --- 항목별 연결 ---
st.subheader("치료 항목별 연결")
icon = {"linked": "🟢", "check": "🟡", "not_covered": "⚪", "excluded": "🔴"}
st.dataframe(
    [
        {
            "": icon[link.status],
            "치료 항목": link.item.name,
            "구분": {"covered": "급여", "uncovered": "비급여"}.get(link.item.benefit, "?"),
            "환자 부담(원)": link.item.patient,
            "상태": STATUS_LABEL[link.status],
            "약관 보장": link.rule.name if link.rule else "",
            "근거 조항": ", ".join(article_label(s) for s in link.sources),
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

# --- 근거 조항 ---
st.subheader("근거 조항")
seen = set()
for link in cmap.links:
    for src in link.sources:
        key = (src.section, src.article, src.paragraph, src.quote)
        if key in seen:
            continue
        seen.add(key)
        where = f"{article_label(src)}" + (f" 《{src.section}》" if src.section else "")
        st.markdown(f"**{where}** — {src.part}")
        if src.quote:
            st.markdown(f"> {_md(src.quote)}")

with st.expander("읽은 서류 내용"):
    for d in docs:
        shown = {k: v for k, v in d.fields.items() if k not in PRIVATE_FIELDS}
        st.markdown(f"**{KIND_LABEL[d.kind]}** · `{d.filename}`")
        st.json(shown, expanded=False)
    st.caption("이름·환자번호 등 개인정보 항목은 화면에 표시하지 않습니다.")
