"""실행 추적 화면. 결과가 이상할 때 어디서 무엇이 잘못됐는지 찾는 용도.

위에서 아래로 읽으면 되게 구성:
  1. 워크플로우 목록: 문제 있는 실행(🔴/🟡)을 찾음 (workflow_id = 이름-시각-난수)
  2. trace 목록: 그 워크플로우 안의 호출들 (채팅 메시지, 워크플로우 단계 등)
  3. 요약: 에러가 처음 난 지점과 traceback 을 맨 위에 표시
  4. 타임라인: 단계별 입력/출력/요청 원문. 에러 단계는 자동으로 펼쳐짐
"""

import json
from datetime import datetime

import streamlit as st

from backend.tracing import (
    delete_all_traces,
    get_trace,
    get_workflow,
    get_workflow_summary,
    list_traces,
    list_workflow_names,
    search_workflows,
)
from schema.trace import SpanRecord

STATUS_ICON = {"ok": "🟢", "warning": "🟡", "error": "🔴", "running": "⏳", "cancelled": "⚪"}
STATUS_LABEL = {
    "ok": "정상",
    "warning": "경고",
    "error": "에러",
    "running": "실행 중 (끝나지 않았다면 비정상 종료)",
    "cancelled": "중단됨",
}
KIND_ICON = {"workflow": "🧩", "agent": "🤖", "llm": "💬", "tool": "🛠️", "step": "▶️"}


def fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "-"
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.2f} s"


def fmt_time(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%m-%d %H:%M:%S")


def short(v, n: int = 60) -> str:
    if v is None:
        return ""
    text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"


def show_value(label: str, v) -> None:
    st.caption(label)
    if v is None or v == "" or v == {} or v == []:
        st.text("(없음)")
    elif isinstance(v, str):
        st.code(v, language=None, wrap_lines=True)
    else:
        st.json(v, expanded=2)


def pick(event, items, param: str, attr: str, default=None):  # trace 목록 선택용
    """표에서 고른 행 > URL 파라미터 > 기본값 순으로 선택. 고른 값은 URL 에 남겨 공유 가능."""
    ids = [getattr(x, attr) for x in items]
    if event.selection.rows:
        chosen = ids[event.selection.rows[0]]
    elif st.query_params.get(param) in ids:
        chosen = st.query_params[param]
    else:
        chosen = default
    if chosen:
        st.query_params[param] = chosen
    return chosen


# ------------------------------------------------------------------ 1. 워크플로우 목록

STATUS_FILTERS: dict[str, list | None] = {
    "전체": None,
    "🔴 에러": ["error"],
    "🟡 경고": ["warning"],
    "⏳ 실행 중·중단": ["running", "cancelled"],
}

st.title("Trace")

with st.sidebar:
    st.button("새로고침", width="stretch")
    with st.expander("관리"):
        if st.button("trace 전체 삭제", type="secondary"):
            delete_all_traces()
            st.query_params.clear()
            st.rerun()

# trace_id 만 넘어온 경우 (예전 링크) → 소속 워크플로우를 찾아서 선택
if st.query_params.get("trace_id") and not st.query_params.get("workflow_id"):
    found = get_trace(st.query_params["trace_id"])
    if found and found[0].workflow_id:
        st.query_params["workflow_id"] = found[0].workflow_id

st.subheader("워크플로우")
c_query, c_name, c_size = st.columns([3, 1.4, 1])
query = c_query.text_input(
    "검색",
    placeholder="workflow ID, 이름, 입력, 채팅 메시지, 에러 메시지",
    key="wf_query",
)
name = c_name.selectbox("종류", ["전체", *list_workflow_names()], key="wf_name")
page_size = c_size.selectbox("페이지당", [10, 20, 50, 100], index=1, key="wf_page_size")
status_label = st.segmented_control("상태", list(STATUS_FILTERS), default="전체", key="wf_status")

# 검색 조건이 바뀌면 1페이지로
filters = (query, name, page_size, status_label)
if st.session_state.get("wf_filters") != filters:
    st.session_state.wf_filters = filters
    st.session_state.wf_page = 1

result = search_workflows(
    query=query,
    statuses=STATUS_FILTERS.get(status_label or "전체"),
    name=None if name == "전체" else name,
    page=st.session_state.get("wf_page", 1),
    page_size=page_size,
)
st.session_state.wf_page = result.page  # 범위를 넘으면 마지막 페이지로 맞춰진 값
workflows = result.items

wf_event = None
if workflows:
    wf_event = st.dataframe(
        [
            {
                "상태": STATUS_ICON[w.worst_status],
                "시작": fmt_time(w.started_at),
                "workflow_id": w.id,
                "trace": w.traces,
                "LLM": w.llm_calls,
                "도구": w.tool_calls,
                "에러": w.errors,
                "토큰 (in/out)": f"{w.input_tokens:,} / {w.output_tokens:,}",
                "입력": w.input_preview,
            }
            for w in workflows
        ],
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        # 페이지나 검색 조건이 바뀌면 표 선택 초기화 (선택한 워크플로우는 URL 에 남아 있음)
        key=f"workflow_table_{hash(filters)}_{result.page}",
    )
elif query or name != "전체" or status_label not in (None, "전체"):
    st.info("조건에 맞는 워크플로우가 없습니다.")
else:
    st.info("기록된 실행이 없습니다. Agent 나 Workflow 화면에서 실행하면 여기에 쌓입니다.")


def go(delta: int) -> None:
    st.session_state.wf_page += delta


first = (result.page - 1) * result.page_size + 1 if result.total else 0
last = min(result.page * result.page_size, result.total)
c_prev, c_page, c_next, c_info = st.columns([1, 1.2, 1, 3], vertical_alignment="bottom")
c_prev.button("◀ 이전", on_click=go, args=(-1,), disabled=result.page <= 1, width="stretch")
c_page.number_input(
    f"페이지 (/ {result.pages})", 1, result.pages, key="wf_page", label_visibility="collapsed"
)
c_next.button(
    "다음 ▶", on_click=go, args=(1,), disabled=result.page >= result.pages, width="stretch"
)
c_info.caption(
    f"{first}–{last} / 총 {result.total:,}개 · {result.page} / {result.pages} 페이지"
    if result.total
    else "총 0개"
)

# 표에서 고른 행 > URL 의 workflow_id (다른 페이지에 있어도 유지)
if wf_event and wf_event.selection.rows:
    wf_id = workflows[wf_event.selection.rows[0]].id
    st.query_params["workflow_id"] = wf_id
    st.query_params.pop("trace_id", None)
else:
    wf_id = st.query_params.get("workflow_id")

wf = get_workflow(wf_id) if wf_id else None
if not wf:
    if wf_id:
        st.warning(f"워크플로우 `{wf_id}` 를 찾을 수 없습니다.")
    elif workflows:
        st.caption("목록에서 워크플로우를 하나 선택하세요.")
    st.stop()

# ------------------------------------------------------------------ 2. trace 목록

wf_summary = next((w for w in workflows if w.id == wf_id), None) or get_workflow_summary(wf_id)
traces = list_traces(wf_id, limit=1000)

st.divider()
st.subheader(f"{STATUS_ICON[wf_summary.worst_status]} {wf_id}")
st.caption(
    f"이름 {wf.name} · 시작 {wf.started_at} · 마지막 {wf.ended_at or '-'} · "
    f"{STATUS_LABEL[wf_summary.worst_status]}"
)
if wf.error_type:  # trace 밖(워크플로우 코드)에서 난 에러
    with st.container(border=True):
        st.error(f"**워크플로우 에러**: {wf.error_type}: {wf.error_message}")
        if wf.attributes.get("error_origin"):
            st.caption(f"하위 단계에서 발생: {wf.attributes['error_origin']}")
        if wf.traceback:
            st.code(wf.traceback, language="python")
if wf.output is not None:
    with st.expander("워크플로우 최종 출력"):
        show_value("output", wf.output)

if not traces:
    st.info("이 워크플로우에는 아직 기록된 호출(trace)이 없습니다.")
    st.stop()

st.markdown(f"**호출 (trace) {len(traces)}개**")
tr_event = st.dataframe(
    [
        {
            "#": i,
            "상태": STATUS_ICON[t.worst_status],
            "시작": fmt_time(t.started_at),
            "trace_id": t.trace_id,
            "종류": KIND_ICON[t.kind],
            "이름": t.name,
            "소요": fmt_ms(t.duration_ms),
            "LLM": t.llm_calls,
            "도구": t.tool_calls,
            "토큰 (in/out)": f"{t.input_tokens:,} / {t.output_tokens:,}",
            "입력": t.input_preview,
        }
        for i, t in enumerate(traces, 1)
    ],
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    key=f"trace_table_{wf_id}",  # 워크플로우가 바뀌면 선택 초기화
)
# 기본 선택: 처음 에러 난 호출, 없으면 마지막 호출
first_error = next((t.trace_id for t in traces if t.worst_status == "error"), None)
selected_id = pick(tr_event, traces, "trace_id", "trace_id", first_error or traces[-1].trace_id)

spans = get_trace(selected_id)
if not spans:
    st.warning(f"trace `{selected_id}` 를 찾을 수 없습니다.")
    st.stop()

# ------------------------------------------------------------------ 요약

root = spans[0]
by_id = {s.id: s for s in spans}


def depth(s: SpanRecord) -> int:
    d = 0
    while s.parent_id and s.parent_id in by_id:
        s, d = by_id[s.parent_id], d + 1
    return d


def path(s: SpanRecord) -> str:
    names = [f"{KIND_ICON[s.kind]} {s.name}"]
    while s.parent_id and s.parent_id in by_id:
        s = by_id[s.parent_id]
        names.append(f"{KIND_ICON[s.kind]} {s.name}")
    return " › ".join(reversed(names))


# 목록과 같은 기준: 하위 단계까지 포함한 가장 나쁜 상태
worst = next(
    (
        st_
        for st_ in ("error", "running", "cancelled", "warning")
        if any(s.status == st_ for s in spans)
    ),
    "ok",
)
st.divider()
st.subheader(f"{STATUS_ICON[worst]} {KIND_ICON[root.kind]} {root.name}")
st.caption(
    f"trace_id `{root.trace_id}` · workflow_id `{root.workflow_id}` · "
    f"시작 {root.started_at} · {STATUS_LABEL[worst]}"
)

llm_spans = [s for s in spans if s.kind == "llm"]
tool_spans = [s for s in spans if s.kind == "tool"]
c = st.columns(5)
c[0].metric("소요", fmt_ms(root.duration_ms))
c[1].metric("LLM 호출", len(llm_spans))
c[2].metric("도구 호출", len(tool_spans))
c[3].metric("에러", sum(s.status == "error" for s in spans))
c[4].metric(
    "토큰 in / out",
    f"{sum(s.attributes.get('usage', {}).get('input', 0) for s in llm_spans):,} / "
    f"{sum(s.attributes.get('usage', {}).get('output', 0) for s in llm_spans):,}",
)

# 에러가 처음 난 곳 = traceback 이 있거나, 자식 중에 에러가 없는 에러 span
errors = [s for s in spans if s.status == "error"]
origins = [
    s
    for s in errors
    if s.traceback or not any(c.parent_id == s.id and c.status == "error" for c in spans)
]
for s in origins:
    with st.container(border=True):
        st.error(f"**에러 발생 지점**: {path(s)}")
        st.markdown(f"**{s.error_type}**: {s.error_message}")
        if s.traceback:
            with st.expander("traceback", expanded=True):
                st.code(s.traceback, language="python")

warnings = [s for s in spans if s.status in ("warning", "running", "cancelled")]
for s in warnings:
    reason = s.attributes.get("stop_reason") or STATUS_LABEL[s.status]
    st.warning(f"{STATUS_ICON[s.status]} {path(s)} — {reason}")

if root.output is not None and root.kind in ("agent", "workflow"):
    with st.expander("최종 출력", expanded=not origins):
        show_value("output", root.output)

st.download_button(
    "trace JSON 내려받기",
    data=json.dumps([s.model_dump() for s in spans], ensure_ascii=False, indent=2),
    file_name=f"{root.workflow_id}_{root.trace_id}.json",
    mime="application/json",
)

# ------------------------------------------------------------------ 타임라인

st.subheader("타임라인")


def summary(s: SpanRecord) -> str:
    a = s.attributes
    if s.status == "error" and s.kind != "tool":
        return f"❗ {s.error_type}: {short(s.error_message, 60)}"
    if s.kind == "llm":
        out = s.output or {}
        u = a.get("usage", {})
        parts = [f"turn {a.get('turn')}", a.get("stop_reason") or s.status]
        if u:
            parts.append(f"{u.get('input', 0):,}→{u.get('output', 0):,} tok")
        if out.get("tool_calls"):
            parts.append("🛠️ " + ", ".join(c["name"] for c in out["tool_calls"]))
        elif out.get("text"):
            parts.append(short(out["text"], 40))
        return " · ".join(parts)
    if s.kind == "tool":
        return f"{short(s.input, 40)} → {short(s.error_message or s.output, 40)}"
    return short(s.output, 60)


for s in spans:
    indent = " " * depth(s)
    label = (
        f"{indent}{STATUS_ICON[s.status]} {KIND_ICON[s.kind]} **{s.name}** · "
        f"{fmt_ms(s.duration_ms)} · {summary(s)}"
    )
    with st.expander(label, expanded=s.status == "error"):
        if s.error_type:
            st.error(f"**{s.error_type}**: {s.error_message}")
            if s.attributes.get("error_origin"):
                st.caption(f"하위 단계에서 발생: {s.attributes['error_origin']}")
            if s.traceback:
                st.code(s.traceback, language="python")

        if s.kind == "llm":
            out = s.output or {}
            t_resp, t_req, t_meta = st.tabs(["응답", "보낸 요청 (원문)", "속성"])
            with t_resp:
                show_value("text", out.get("text"))
                if out.get("tool_calls"):
                    show_value("tool_calls", out["tool_calls"])
            with t_req:
                req = s.input or {}
                st.caption(
                    f"messages {len(req.get('messages', []))}개 · tools {len(req.get('tools', []))}개"
                )
                st.json(req, expanded=1)
            with t_meta:
                st.json(s.attributes)
        elif s.kind == "tool":
            left, right = st.columns(2)
            with left:
                show_value("인자", s.input)
            with right:
                show_value("결과", s.output)
            if s.attributes.get("attachments"):
                files = ", ".join(a["filename"] for a in s.attributes["attachments"])
                st.caption(f"📎 모델에게 전달한 파일: {files}")
            st.caption(f"tool_call_id: {s.attributes.get('tool_call_id', '-')}")
        else:
            t_in, t_out, t_meta = st.tabs(["입력", "출력", "속성"])
            with t_in:
                show_value("input", s.input)
            with t_out:
                show_value("output", s.output)
            with t_meta:
                st.json(s.attributes)
