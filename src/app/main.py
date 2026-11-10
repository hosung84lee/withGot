"""Streamlit 진입점. 실행: uv run streamlit run src/app/main.py"""

import streamlit as st

from backend.config import get_settings
from backend.db import init_db

settings = get_settings()
st.set_page_config(page_title=settings.app_name, page_icon="🙏", layout="wide")


@st.cache_resource
def _bootstrap() -> None:
    init_db()


_bootstrap()

pages = [
    st.Page("views/home.py", title="Home", icon="🏠", default=True),
    st.Page("views/terms_page.py", title="약관 분석", icon="📜"),
    st.Page("views/coverage_map_page.py", title="보장맵", icon="🗺️"),
    st.Page("views/workflow_page.py", title="Workflow", icon="⚙️"),
    st.Page("views/agent_page.py", title="Agent", icon="🤖"),
    st.Page("views/trace_page.py", title="Trace", icon="🔍"),
]
st.navigation(pages).run()
