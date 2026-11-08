import streamlit as st

from backend.config import get_settings

st.title(get_settings().app_name)
st.write("Streamlit 초기 세팅입니다.")

if st.button("Mock Workflow 실행하러 가기 →", type="primary"):
    st.switch_page("views/workflow_page.py")
