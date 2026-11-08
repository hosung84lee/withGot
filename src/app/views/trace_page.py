"""실행 추적 화면. 결과가 이상할 때 어디서 무엇이 잘못됐는지 찾는 용도.

위에서 아래로 읽으면 되게 구성:
  1. 목록: 문제 있는 실행(🔴/🟡)을 찾음
  2. 요약: 에러가 처음 난 지점과 traceback 을 맨 위에 표시
  3. 타임라인: 단계별 입력/출력/요청 원문. 에러 단계는 자동으로 펼쳐짐
"""

import json
from datetime import datetime

import streamlit as st

from backend.tracing import delete_all_traces, get_trace, list_traces
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


# ------------------------------------------------------------------ 목록

st.title("Trace")

with st.sidebar:
    status_filter = st.segmented_control(
        "상태", ["전체", "🔴 에러", "🟡 경고"], default="전체", key="trace_status"
    )
    search = st.text_input("검색 (이름, 입력, 에러 메시지)")
    limit = st.number_input("최근 N개", 10, 1000, 100, step=50)
    st.button("새로고침", width="stretch")
    with st.expander("관리"):
        if st.button("trace 전체 삭제", type="secondary"):
            delete_all_traces()
            st.query_params.clear()
            st.rerun()

traces = list_traces(int(limit))
if status_filter == "🔴 에러":
    traces = [t for t in traces if t.worst_status == "error"]
elif status_filter == "🟡 경고":
    traces = [t for t in traces if t.worst_status == "warning"]
if search:
    q = search.lower()
    traces = [
        t
        for t in traces
        if q in t.name.lower()
        or q in t.input_preview.lower()
        or q in (t.error_message or "").lower()
    ]

if not traces:
    st.info("기록된 실행이 없습니다. Agent 나 Workflow 화면에서 실행하면 여기에 쌓입니다.")
    st.stop()

event = st.dataframe(
    [
        {
            "상태": STATUS_ICON[t.worst_status],
            "시작": fmt_time(t.started_at),
            "종류": KIND_ICON[t.kind],
            "이름": t.name,
            "소요": fmt_ms(t.duration_ms),
            "LLM": t.llm_calls,
            "도구": t.tool_calls,
            "에러": t.errors,
            "토큰 (in/out)": f"{t.input_tokens:,} / {t.output_tokens:,}",
            "입력": t.input_preview,
        }
        for t in traces
    ],
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    key="trace_table",
)

rows = event.selection.rows
if rows:
    selected_id = traces[rows[0]].trace_id
    st.query_params["trace_id"] = selected_id  # URL 로 공유 가능
else:
    selected_id = st.query_params.get("trace_id")

if not selected_id:
    st.caption("목록에서 실행을 하나 선택하세요.")
    st.stop()

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
st.caption(f"trace_id `{root.trace_id}` · 시작 {root.started_at} · {STATUS_LABEL[worst]}")

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
    file_name=f"trace_{root.trace_id}.json",
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
                if out.get("thinking"):
                    st.caption("추론 요약 (왜 이렇게 응답했는지)")
                    st.info(out["thinking"])
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
