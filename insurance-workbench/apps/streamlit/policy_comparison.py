import streamlit as st
from comparison_charts import show_comparison_charts
from indemnity_comparison import BASELINE_NAME, MAX_MB, compare_pdf
from samsung_life_policy_review import reviewed_changes

st.set_page_config(page_title="보장잇 · 실손 약관 비교", layout="wide")
st.title("실손 4세대 ↔ 5세대 약관 비교")
st.write("5세대 약관 PDF를 올려 4세대와 달라진 보장과 자기부담 기준을 확인하세요.")
st.caption(f"비교 기준 · {BASELINE_NAME}")

upload = st.file_uploader(
    "5세대 실손 약관 PDF",
    type=["pdf"],
    max_upload_size=MAX_MB,
    help="표지와 특약이 포함된 텍스트 PDF를 선택하세요. 원본은 실행 중인 앱에서 처리합니다.",
)
if upload is None:
    st.link_button(
        "시연용 5세대 약관 PDF 열기 · 삼성화재 2605.1",
        "https://direct.samsungfire.com/docs/realloss.pdf",
    )
    st.stop()

pdf = upload.getvalue()
try:
    with st.spinner("약관의 자기부담 근거를 찾는 중입니다."):
        rows = compare_pdf(pdf)
except ValueError as error:
    st.error(str(error))
    st.stop()

if all(not row.evidence for row in rows):
    st.warning("지원 형식의 자기부담 근거를 찾지 못했습니다. 약관 표와 조항을 직접 확인해 주세요.")
changes = reviewed_changes(pdf)
show_comparison_charts(rows, changes)

st.subheader("자기부담 기준 비교")
st.caption("일반 의료비 기준으로 비교합니다. 4세대 일반 비급여를 5세대 중증·비중증과 각각 대조합니다.")
st.table([
    {
        "비교 항목": row.label,
        "4세대 기준": row.baseline.rule.describe(),
        "업로드한 5세대": row.uploaded,
        "비교 결과": row.status,
    }
    for row in rows
])

st.subheader("문서별 상세 변경")
if not changes:
    st.caption("이 PDF에는 대조가 완료된 상세 변경 자료가 없습니다. 위 기본 공제 결과를 확인하세요.")
else:
    for change in changes:
        with st.expander(change.title):
            st.markdown(f"**4세대 2601 · PDF {change.before_pages}쪽**")
            st.write(change.before)
            st.markdown(f"**5세대 2605 · PDF {change.after_pages}쪽**")
            st.write(change.after)

st.subheader("세대별 원문 근거")
for row in rows:
    with st.expander(f"{row.label} · {row.status}"):
        st.write(f"4세대 · PDF {row.baseline.page}쪽 · {row.baseline.section}")
        st.code(row.baseline.excerpt, language=None, wrap_lines=True)
        if not row.evidence:
            st.write("5세대 PDF에서 비교 가능한 근거를 찾지 못했습니다.")
        for evidence in row.evidence:
            st.write(f"5세대 · PDF {evidence.page}쪽 · {evidence.section}")
            st.code(evidence.excerpt, language=None, wrap_lines=True)
