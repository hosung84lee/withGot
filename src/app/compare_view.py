"""약관 분석 화면의 '약관 비교 (스키마)' 탭: 약관 2개 → 보장 JSON(coverage.json) → 보장별 비교."""

import json

import streamlit as st

from backend.config import get_settings
from coverage_json import compare_items, validate_items
from coverage_json import store as schema_store
from coverage_map import policy

UPLOAD = "PDF 직접 올리기"


def _pick(label: str, key: str, default: int) -> tuple[bytes, str] | None:
    samples = policy.sample_policies()
    names = [p.stem for p in samples] + [UPLOAD]
    choice = st.selectbox(label, names, index=min(default, len(names) - 1), key=f"{key}_pick")
    if choice == UPLOAD:
        up = st.file_uploader(label, type=["pdf"], key=f"{key}_up", label_visibility="collapsed")
        return (up.getvalue(), up.name) if up else None
    path = samples[names.index(choice)]
    return path.read_bytes(), path.name


def _build(raw: bytes, name: str, use_ai: bool, model: str | None, box) -> dict:
    key = policy.file_hash(raw)
    with box:
        st.write(f"▶ {name}: 텍스트·구조화 (처음 한 번은 1분 안팎)")
    doc = policy.load_terms(raw)
    errors: dict[str, list[str]] = {}
    if use_ai:
        with box:
            st.write(f"▶ {name}: AI 스키마 추출 (캐시에 없는 묶음만)")
        errors = schema_store.extract_missing(
            key,
            doc,
            model=model,
            on_progress=lambda i, n, b: box.write(f"　· 묶음 {i}/{n} 끝: {b.key}"),
        )
    items, source = schema_store.items_for(doc, key)
    return {
        "name": name,
        "items": items,
        "source": source,
        "errors": errors,
        "validation": validate_items(items),
    }


def _short(item: dict) -> str:
    return f"{item['coverage_name']} · {item.get('claim_reason') or '-'}"


def render(model: str | None = None) -> None:
    settings = get_settings()
    st.caption(
        "약관 2개에서 보장을 스키마(src/schema/json/coverage.json) 모양으로 뽑아, 보장끼리 짝을 맞춰 "
        "청구사유·대상 질병·감액·보험금·실손 규칙 등을 나란히 비교합니다."
    )
    c1, c2 = st.columns(2)
    with c1:
        a = _pick("약관 A", "cmp_a", 0)
    with c2:
        b = _pick("약관 B", "cmp_b", 1)
    use_ai = st.toggle(
        "AI 스키마 추출 (OpenAI)",
        value=False,
        help="켜면 약관 조문·지급기준표에서 스키마를 직접 뽑습니다 (묶음 동시 처리, API 비용, 결과 캐시). "
        "끄면 API 없이 정답 데이터·이전 사고보장 추출 결과를 스키마로 변환해 비교합니다.",
        key="cmp_ai",
    )
    if use_ai and not settings.openai_api_key:
        st.warning(".env 에 OPENAI_API_KEY 가 없어 AI 스키마 추출을 할 수 없습니다.")
    if st.button("비교", type="primary", disabled=not (a and b), key="cmp_run"):
        with st.status("약관 2개 처리 중…", expanded=True) as status:
            box = st.container()
            sides = [
                _build(raw, name, use_ai and bool(settings.openai_api_key), model, box)
                for raw, name in (a, b)
            ]
            failed = any(s["errors"] for s in sides)
            status.update(
                label="완료" + (" (일부 실패)" if failed else ""),
                state="error" if failed else "complete",
                expanded=False,
            )
        st.session_state.compare_result = {
            "sides": sides,
            "cmp": compare_items(sides[0]["items"], sides[1]["items"]),
        }

    res = st.session_state.get("compare_result")
    if not res:
        return
    sa, sb = res["sides"]
    cmp = res["cmp"]
    st.divider()
    m = st.columns(5)
    m[0].metric("A 보장", len(sa["items"]))
    m[1].metric("B 보장", len(sb["items"]))
    m[2].metric("짝 맞춘 보장", len(cmp["pairs"]))
    m[3].metric("A 에만", len(cmp["only_a"]))
    m[4].metric("B 에만", len(cmp["only_b"]))
    st.caption(f"A: {sa['name']} — {sa['source']}  \nB: {sb['name']} — {sb['source']}")
    for side, tag in ((sa, "A"), (sb, "B")):
        for k, errs in side["errors"].items():
            st.warning(f"{tag} 추출 실패·부분 실패: {k} — {errs[0][:200]}")
        if side["validation"]:
            st.warning(
                f"{tag} 스키마 검증 오류 {len(side['validation'])}건: {side['validation'][0]}"
            )
        if not side["items"]:
            st.info(
                f"{tag}({side['name']})는 보장 데이터가 없습니다. 'AI 스키마 추출' 을 켜고 다시 비교하세요."
            )

    if cmp["pairs"]:
        st.subheader("보장별 비교")
        st.caption("❗ = 두 약관이 다른 필드")
        for p in cmp["pairs"]:
            diff = sum(not r["같음"] for r in p["rows"])
            title = (
                f"{'❗' if diff else '✅'} {p['a']['coverage_name']}  ↔  {p['b']['coverage_name']}"
            )
            with st.expander(title + (f"  (다른 필드 {diff}개)" if diff else "  (같음)")):
                st.dataframe(
                    [
                        {"": "" if r["같음"] else "❗", "필드": r["필드"], "A": r["A"], "B": r["B"]}
                        for r in p["rows"]
                    ],
                    hide_index=True,
                    width="stretch",
                )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**A 에만 있는 보장 ({len(cmp['only_a'])})**")
        for x in cmp["only_a"]:
            st.markdown(f"- {_short(x)}")
    with c2:
        st.markdown(f"**B 에만 있는 보장 ({len(cmp['only_b'])})**")
        for x in cmp["only_b"]:
            st.markdown(f"- {_short(x)}")

    with st.expander("스키마 JSON 보기·다운로드"):
        d1, d2 = st.columns(2)
        for col, side, tag in ((d1, sa, "A"), (d2, sb, "B")):
            col.download_button(
                f"{tag} 보장 JSON 다운로드",
                json.dumps(side["items"], ensure_ascii=False, indent=2),
                file_name=f"coverage_{tag}_{policy.file_hash(side['name'].encode())}.json",
                mime="application/json",
                key=f"cmp_dl_{tag}",
            )
            col.json(side["items"], expanded=False)
