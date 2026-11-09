"""Visual summaries for the policy comparison screen."""

import altair as alt
import streamlit as st
from indemnity_comparison import ComparisonRow
from samsung_life_policy_review import Change

GENERATIONS = ["4세대", "5세대"]


def _source_pages(before: int | str, after: int | str) -> str:
    return f"PDF 근거 · 4세대 {before}쪽 / 5세대 {after}쪽"


def _key_changes(rows: list[ComparisonRow], changes: tuple[Change, ...]) -> None:
    by_title = {change.title: change for change in changes}
    limit = by_title["비중증 비급여 지급한도"]
    pregnancy = by_title["임신·출산·산후기 급여"]
    rate = next(
        (row for row in rows if row.label == "비중증 비급여 입원" and row.status == "변경"),
        None,
    )
    assert limit.annual_limit is not None
    _, old_limit, new_limit = limit.annual_limit
    cards = [
        (
            "비중증 비급여 연간 지급한도", "한도 축소", "orange",
            f"{old_limit:,}만 원", f"{new_limit:,}만 원",
            "4세대 일반 비급여 한도와 비교",
            _source_pages(limit.before_pages, limit.after_pages),
        ),
    ]
    if rate:
        before, after = rate.baseline.rule.percent, rate.evidence[0].rule.percent
        pages = "·".join(str(page) for page in sorted({source.page for source in rate.evidence}))
        cards.append((
            "비중증 비급여 입원 자기부담률", "부담 증가", "orange",
            f"{before}%", f"{after}%",
            "보장대상 입원 의료비 중 가입자 부담 비율",
            _source_pages(rate.baseline.page, pages),
        ))
    cards.append((
        "임신·출산·산후기 급여", "보장 신설", "green",
        "보상 제외", "조건부 보상",
        "개인 계약은 분만예정일로부터 280일 이전 가입",
        _source_pages(pregnancy.before_pages, pregnancy.after_pages),
    ))

    for column, card in zip(st.columns(len(cards), border=True), cards, strict=True):
        title, status, color, before, after, description, source = card
        with column:
            st.badge(status, color=color)
            st.markdown(f"**{title}**")
            st.markdown(f"4세대　{before}  \n5세대　**{after}**")
            st.write(description)
            st.caption(source)


def _bars(before: int, after: int, unit: str, maximum: int) -> None:
    values = [
        {"세대": generation, "값": value, "표시": f"{value:,}{unit}"}
        for generation, value in zip(GENERATIONS, (before, after), strict=True)
    ]
    chart = alt.Chart(alt.Data(values=values)).encode(
        x=alt.X(
            "값:Q",
            title=f"비교 단위 ({unit})",
            scale=alt.Scale(domain=[0, maximum], nice=False),
            axis=alt.Axis(values=[0, 25, 50, 75, 100]) if unit == "%" else alt.Axis(tickCount=4),
        ),
        y=alt.Y("세대:N", sort=GENERATIONS, title=None, axis=alt.Axis(labelPadding=10)),
        tooltip=[alt.Tooltip("세대:N"), alt.Tooltip("표시:N", title="기준")],
    )
    bars = chart.mark_bar(size=22, cornerRadiusEnd=4).encode(
        color=alt.Color(
            "세대:N", scale=alt.Scale(domain=GENERATIONS, range=["#64748b", "#2679d2"]), legend=None
        )
    )
    labels = chart.mark_text(align="left", dx=7, fontSize=14, fontWeight=500).encode(text="표시:N")
    st.altair_chart((bars + labels).properties(height=165), width="stretch")


def _deductible_chart(rows: list[ComparisonRow]) -> None:
    eligible = {
        row.label: row for row in rows
        if row.label.endswith("입원") and row.status in {"동일", "변경"}
    }
    if not eligible:
        st.info("두 문서에서 공통으로 확인할 수 있는 입원 공제율이 없습니다.")
        return
    labels = list(eligible)
    default = "비중증 비급여 입원"
    label = st.selectbox(
        "비교할 입원 유형", labels, index=labels.index(default) if default in eligible else 0
    )
    row = eligible[label]
    before, after = row.baseline.rule.percent, row.evidence[0].rule.percent
    st.write(f"보장대상 의료비에서 가입자가 부담하는 기본 비율 **{before}% → {after}%**")
    _bars(before, after, "%", 120)
    pages = "·".join(str(page) for page in sorted({source.page for source in row.evidence}))
    st.caption(
        f"근거는 4세대 PDF {row.baseline.page}쪽과 5세대 PDF {pages}쪽입니다. "
        "별도 연간 자기부담 상한은 아래 상세 변경에서 확인할 수 있습니다."
    )


def _annual_limit_chart(changes: tuple[Change, ...]) -> None:
    amounts = {change.annual_limit[0]: change for change in changes if change.annual_limit}
    if not amounts:
        st.info("이 PDF의 연간 지급한도는 원문 대조가 완료되면 표시됩니다.")
        return
    label = st.selectbox("비교할 보장", list(amounts))
    change = amounts[label]
    assert change.annual_limit is not None
    _, before, after = change.annual_limit
    st.write(f"보험사가 1년간 지급하는 약관상 최대액 **{before:,}만 원 → {after:,}만 원**")
    _bars(before, after, "만 원", int(max(before, after) * 1.35))
    st.caption(f"근거는 4세대 PDF {change.before_pages}쪽과 5세대 PDF {change.after_pages}쪽입니다.")


def _coverage_comparison(changes: tuple[Change, ...]) -> None:
    topics = {
        change.title: change for change in changes
        if change.title in {"임신·출산·산후기 급여", "정신발달장애 급여", "비중증 치료 면책"}
    }
    change = topics[st.selectbox("비교할 보장 조건", list(topics))]
    before, after = st.columns(2, border=True)
    for column, generation, text, pages in (
        (before, "4세대", change.before, change.before_pages),
        (after, "5세대", change.after, change.after_pages),
    ):
        column.markdown(f"**{generation}**")
        column.write(text)
        column.caption(f"PDF {pages}쪽")


def show_comparison_charts(rows: list[ComparisonRow], changes: tuple[Change, ...]) -> None:
    st.subheader("한눈에 보는 실손 약관 비교")
    if changes:
        _key_changes(rows, changes)
        st.markdown("**그래프와 보장 조건**")
        limits, deductible, coverage = st.tabs(["연간 지급한도", "입원 자기부담률", "보장 조건"])
        with limits:
            _annual_limit_chart(changes)
        with deductible:
            _deductible_chart(rows)
        with coverage:
            _coverage_comparison(changes)
    else:
        _deductible_chart(rows)
