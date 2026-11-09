import streamlit as st

from agent import Agent
from backend.attachments import SUPPORTED_EXTENSIONS, attachment_from_document, media_type_of
from backend.config import get_settings
from backend.storage import list_documents, save_upload
from backend.tracing import new_workflow_id, workflow
from schema.agent import AgentMessage, Attachment
from schema.document import DocumentKind

TRACE_PAGE = "views/trace_page.py"
settings = get_settings()


def save_files(files) -> list[Attachment]:
    """업로드 파일을 문서 보관함에 저장. 저장된 문서는 agent 가 나중에 read_document 로도 열 수 있음."""
    out = []
    for f in files:
        kind = (
            DocumentKind.PDF if media_type_of(f.name) == "application/pdf" else DocumentKind.IMAGE
        )
        out.append(attachment_from_document(save_upload(f.name, f.getvalue(), kind)))
    return out


def show_attachments(attachments: list[Attachment]) -> None:
    if attachments:
        st.caption("  ".join(f"📎 {a.filename}" for a in attachments))


st.title("Agent")

with st.sidebar:
    model = st.text_input("OpenAI 모델", value=settings.openai_model)
    if st.button("대화 초기화"):
        st.session_state.agent_history = []
        st.session_state.chat_workflow_id = new_workflow_id("chat")

    # 대화 1개 = workflow 1개 (chat-...), 메시지 1개 = trace 1개
    chat_id = st.session_state.setdefault("chat_workflow_id", new_workflow_id("chat"))
    st.caption(f"대화 ID `{chat_id}`")
    st.page_link(
        TRACE_PAGE, label="이 대화의 Trace", icon="🔍", query_params={"workflow_id": chat_id}
    )

    st.divider()
    st.subheader("문서 보관함")
    st.caption(
        "여기 올린 문서는 agent 가 필요할 때 직접 찾아서 읽습니다. (예: “3번 문서 요약해줘”)"
    )
    with st.form("library_upload", clear_on_submit=True):
        files = st.file_uploader(
            "PDF / 이미지", type=SUPPORTED_EXTENSIONS, accept_multiple_files=True
        )
        if st.form_submit_button("보관함에 추가") and files:
            save_files(files)
            st.toast(f"{len(files)}개 추가됨")
    for d in list_documents()[:20]:
        st.caption(f"#{d.id} · {'📄' if d.kind == DocumentKind.PDF else '🖼️'} {d.filename}")

history: list[AgentMessage] = st.session_state.setdefault("agent_history", [])

for m in history:
    if m.role == "user":
        with st.chat_message("user"):
            show_attachments(m.attachments)
            st.write(m.content)
    elif m.role == "assistant" and m.content:
        st.chat_message("assistant").write(m.content)
    elif m.role == "tool":
        label = "도구 결과" + (" (에러)" if m.is_error else "")
        with st.chat_message("assistant", avatar="🛠️"), st.expander(label):
            show_attachments(m.attachments)
            st.code(m.content)

submitted = st.chat_input(
    "메시지를 입력하세요 (PDF·이미지 첨부 가능)",
    accept_file="multiple",
    file_type=SUPPORTED_EXTENSIONS,
)
if submitted and (submitted.text or submitted.files):
    attachments = save_files(submitted.files)
    user_msg = AgentMessage(role="user", content=submitted.text, attachments=attachments)
    with st.chat_message("user"):
        show_attachments(attachments)
        st.write(submitted.text)
    history.append(user_msg)

    with st.chat_message("assistant"):
        with st.status("Agent 실행 중…", expanded=False) as status:

            def on_event(kind: str, data: dict) -> None:
                if kind == "tool":
                    st.write(f"🛠️ `{data['name']}`({data['arguments']})")

            agent = None
            try:
                agent = Agent(model, name="chat")
                with workflow("chat", workflow_id=chat_id):
                    result = agent.run(history, on_event=on_event)
            except Exception as e:  # noqa: BLE001  API 키 누락, 네트워크 오류 등
                status.update(label="실패", state="error")
                history.pop()
                st.error(f"{type(e).__name__}: {e}")
                if agent and agent.last_trace_id:
                    st.page_link(
                        TRACE_PAGE,
                        label="Trace 에서 원인 보기",
                        icon="🔍",
                        query_params={"workflow_id": chat_id, "trace_id": agent.last_trace_id},
                    )
                st.stop()
            status.update(
                label=f"완료 · {result.turns}턴 · 도구 {len(result.tool_traces)}회 · {result.stop_reason}",
                state="complete",
            )
        if result.output:
            st.write(result.output)
        if result.stop_reason == "max_tokens":
            st.warning("응답이 토큰 한도에 걸려 잘렸습니다. AGENT_MAX_TOKENS 를 늘려 보세요.")
        elif result.stop_reason == "max_turns":
            st.warning("최대 반복 횟수(AGENT_MAX_TURNS)에 도달해 중단했습니다.")
        elif result.stop_reason == "refusal" and not result.output:
            st.warning("모델이 요청을 거절했습니다.")
        st.page_link(
            TRACE_PAGE,
            label=f"Trace 보기 · {result.trace_id}",
            icon="🔍",
            query_params={"workflow_id": chat_id, "trace_id": result.trace_id},
        )

    st.session_state.agent_history = result.messages
