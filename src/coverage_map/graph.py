"""보장맵 그림 (Graphviz DOT): 서류 → 치료 항목 → 보장 규칙 → 약관 조항."""

from collections.abc import Callable

from schema.coverage import SourceRef

from .linker import STATUS_LABEL, CoverageMap, article_label

COLOR = {"linked": "#2e7d5b", "check": "#c98a14", "not_covered": "#9aa3a8", "excluded": "#c0392b"}
FILL = {"linked": "#e5f4e4", "check": "#f9eeda", "not_covered": "#f0efec", "excluded": "#fbebeb"}


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _short(s: str, n: int = 22) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def to_dot(cmap: CoverageMap, title_of: Callable[[SourceRef], str | None] | None = None) -> str:
    """title_of: 근거 조항의 조 제목 (약관 PDF 를 연결했을 때). 예: 제3조 → '보상내용'."""
    out = [
        "digraph G {",
        "rankdir=LR; nodesep=0.25; ranksep=0.9; bgcolor=transparent;",
        (
            'node [shape=box style="rounded,filled" fontname="Noto Sans KR, sans-serif" '
            'fontsize=11 color="#c9d1d6" fillcolor="#ffffff" penwidth=1.2];'
        ),
        'edge [color="#9aa3a8" arrowsize=0.6 fontname="Noto Sans KR, sans-serif" fontsize=9];',
    ]

    def cluster(name: str, label: str, body: list[str]) -> None:
        out.append(
            f"subgraph cluster_{name} {{ label={_q(label)}; fontsize=12; "
            'fontname="Noto Sans KR, sans-serif"; color="#e3e7ea"; style=rounded;'
        )
        out.extend(body)
        out.append("}")

    claim = cmap.claim
    docs = [d for d in claim.docs]
    cluster(
        "docs",
        "① 올린 서류",
        [
            f'd{i} [label={_q(d.label + chr(10) + _short(d.filename, 26))} fillcolor="#eef2f5"];'
            for i, d in enumerate(docs)
        ],
    )
    doc_index = {d.filename: i for i, d in enumerate(docs)}

    item_nodes = []
    item_id: dict[int, str] = {}  # 같은 항목(진단 하나 → 규칙 여러 개)은 칸 하나로
    for link in cmap.links:
        key = id(link.item)
        if key in item_id:
            continue
        item_id[key] = f"i{len(item_id)}"
        it = link.item
        if it.benefit == "diagnosis":
            label = f"{_short(it.name, 16)}\n진단서 질병코드"
        else:
            kind = {"covered": "급여", "uncovered": "비급여"}.get(it.benefit, "구분 없음")
            label = f"{_short(it.name, 16)}\n{kind} · {it.patient:,}원"
        item_nodes.append(
            f"{item_id[key]} [label={_q(label)} color={_q(COLOR[link.status])} "
            f"fillcolor={_q(FILL[link.status])}];"
        )
    cluster("items", "② 치료 항목·진단", item_nodes)

    rule_ids: dict[str, str] = {}
    rule_nodes = []
    for link in cmap.links:
        if link.rule and not link.exclusion and link.rule.id not in rule_ids:
            n = f"r{len(rule_ids)}"
            rule_ids[link.rule.id] = n
            rule_nodes.append(f'{n} [label={_q(_short(link.rule.name, 24))} fillcolor="#e7f1fb"];')
    special = {
        "not_covered": ("x_nc", "이 약관 보상 대상 아님\n(비급여 특약 확인)"),
        "check": ("x_ck", "확인 필요"),
    }
    used_special = {link.status for link in cmap.links if not link.rule and link.status in special}
    for st in used_special:
        n, label = special[st]
        rule_nodes.append(
            f"{n} [label={_q(label)} color={_q(COLOR[st])} fillcolor={_q(FILL[st])}];"
        )
    excl_ids: dict[str, str] = {}
    for link in cmap.links:
        ex = link.exclusion
        if ex and ex.id not in excl_ids:
            n = f"e{len(excl_ids)}"
            excl_ids[ex.id] = n
            rule_nodes.append(
                f"{n} [label={_q('보상 제외' + chr(10) + _short(ex.description, 20))} "
                f'color="{COLOR["excluded"]}" fillcolor="{FILL["excluded"]}"];'
            )
    cluster("rules", "③ 약관 보장", rule_nodes)

    art_ids: dict[str, str] = {}
    art_nodes = []
    edges_art = set()
    for link in cmap.links:
        owner = (
            excl_ids.get(link.exclusion.id)
            if link.exclusion
            else rule_ids.get(link.rule.id)
            if link.rule
            else None
        )
        for src in link.sources:
            key = f"{src.section or ''} {article_label(src)}"
            if key not in art_ids:
                art_ids[key] = f"a{len(art_ids)}"
                label = article_label(src)
                title = title_of(src) if title_of else None
                if title:
                    label += f"\n({_short(title, 14)})"
                if src.section:
                    label += f"\n《{src.section}》"
                art_nodes.append(
                    f'{art_ids[key]} [label={_q(label)} shape=note fillcolor="#fffdf5"];'
                )
            if owner:
                edges_art.add((owner, art_ids[key]))
    cluster("arts", "④ 약관 조항 (근거)", art_nodes)

    doc_edges = set()
    for link in cmap.links:
        node = item_id[id(link.item)]
        di = doc_index.get(link.item.doc)
        if di is not None and (di, node) not in doc_edges:
            doc_edges.add((di, node))
            out.append(f"d{di} -> {node};")
        if link.exclusion:
            target = excl_ids[link.exclusion.id]
        elif link.rule:
            target = rule_ids[link.rule.id]
        else:
            target = special.get(link.status, ("x_ck",))[0]
        color = COLOR[link.status]
        out.append(
            f"{node} -> {target} [color={_q(color)} penwidth=1.6 "
            f"tooltip={_q(STATUS_LABEL[link.status])}];"
        )
    for a, b in sorted(edges_art):
        out.append(f"{a} -> {b} [style=dashed];")
    out.append("}")
    return "\n".join(out)
