import streamlit as st

from workflow.mock import STEPS, run_mock_workflow

st.title("Mock Workflow")
st.caption("텍스트를 입력하고 실행하면 mock 워크플로우 결과를 받아옵니다.")

with st.form("workflow_form"):
    text = st.text_area("입력", height=150, placeholder="분석할 텍스트를 입력하세요")
    delay = st.slider("단계별 지연(초)", 0.0, 3.0, 0.8, 0.1)
    submitted = st.form_submit_button("실행", type="primary")

if submitted:
    if not text.strip():
        st.warning("입력 텍스트를 넣어주세요.")
    else:
        with st.status("워크플로우 실행 중…", expanded=True) as status:
            progress = st.progress(0)

            def on_step(i: int, name: str) -> None:
                st.write(f"▶ {name}")
                progress.progress(i / len(STEPS))

            result = run_mock_workflow(text, delay=delay, on_step=on_step)
            progress.progress(1.0)
            status.update(label="완료", state="complete", expanded=False)
        st.session_state.workflow_result = result

result = st.session_state.get("workflow_result")
if result:
    st.subheader("결과")
    c1, c2, c3 = st.columns(3)
    c1.metric("Workflow ID", result.workflow_id)
    c2.metric("단계 수", len(result.steps))
    c3.metric("총 소요(초)", result.total_sec)

    st.info(result.summary)
    if result.keywords:
        st.write("**키워드:** " + ", ".join(f"`{k}`" for k in result.keywords))

    st.dataframe([s.model_dump() for s in result.steps], width="stretch", hide_index=True)

    with st.expander("Raw JSON"):
        st.json(result.model_dump(mode="json"))
