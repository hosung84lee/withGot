"""사고보장 데이터(schema.coverage.Product) ↔ 관계형 테이블(SQLite).

    conn = connect("coverage.db")
    save_product(conn, product, "silson-2605")      # 같은 product_id 가 있으면 지우고 다시 저장
    product = load_product(conn, "silson-2605")     # 저장한 것과 같은 Product 로 되돌림

테이블 정의는 schema.sql, 설명은 docs/coverage_tables.md.
"""

import sqlite3
from pathlib import Path

from schema.coverage import (
    AmountLimit,
    Benefit,
    BenefitRule,
    Coverage,
    CoverageCode,
    Deductible,
    Exclusion,
    Extension,
    Installment,
    KcdRange,
    Limit,
    Product,
    Ratio,
    Reduction,
    Risk,
    RuleConditions,
    SourceRef,
    SpecialCondition,
)

SCHEMA_SQL = Path(__file__).with_name("schema.sql")

# 참조조건 항목코드 → (이름, 단위). 금액 한도는 LIMIT_AMT_<한도 단위>.
CONDITION_ITEMS: dict[str, tuple[str, str]] = {
    "EXEMPT_DAYS": ("면책기간", "일"),
    "REDUCE_DAYS": ("감액기간", "일"),
    "REDUCE_RATIO_NUM": ("감액 지급비율 분자", "-"),
    "REDUCE_RATIO_DEN": ("감액 지급비율 분모", "-"),
    "DEDUCT_DAYS": ("공제일수", "일"),
    "LIMIT_EVENT_DAYS": ("1회 입원당 한도일수", "일"),
    "LIMIT_TOTAL_DAYS": ("통산 한도일수", "일"),
    "LIMIT_COUNT": ("지급 횟수", "회"),
    "LIMIT_AMT_VISIT": ("금액 한도: 통원 1회당", "원"),
    "LIMIT_AMT_DAY": ("금액 한도: 1일당", "원"),
    "LIMIT_AMT_STAY": ("금액 한도: 입원 1회당", "원"),
    "LIMIT_AMT_YEAR": ("금액 한도: 연간", "원"),
    "LIMIT_AMT_DAILY_AVERAGE": ("금액 한도: 1일 평균", "원"),
    "LIMIT_AMT_EVENT": ("금액 한도: 사고 1건당", "원"),
    "EXT_DAYS": ("계약 종료 후 보상 일수", "일"),
    "EXT_VISITS": ("계약 종료 후 통원 최대 횟수", "회"),
    "EXT_VISIT_DAYS": ("계약 종료 후 통원 최대 일수", "일"),
}

# 상품 하나를 이루는 테이블 (지울 때 자식부터)
PRODUCT_TABLES = [
    "source_ref",
    "installment",
    "special_condition",
    "deductible",
    "benefit",
    "rule_condition",
    "benefit_rule",
    "exclusion",
    "risk",
    "kcd_range",
    "coverage_code",
    "coverage",
    "product",
]


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    """DB 를 열고 테이블·항목 사전을 만듦 (이미 있으면 그대로)."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT OR REPLACE INTO condition_item VALUES (?, ?, ?)",
        [(code, name, unit) for code, (name, unit) in CONDITION_ITEMS.items()],
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------- 저장


def _conditions(c: RuleConditions) -> list[tuple[str, float, bool]]:
    """RuleConditions → (항목코드, 값, 선택가능) 목록. 순서 = 저장 순서."""
    rows: list[tuple[str, float, bool]] = []
    if c.exemption_days is not None:
        rows.append(("EXEMPT_DAYS", c.exemption_days, False))
    if c.reduction:
        rows += [
            ("REDUCE_DAYS", c.reduction.days, False),
            ("REDUCE_RATIO_NUM", c.reduction.ratio.numerator, False),
            ("REDUCE_RATIO_DEN", c.reduction.ratio.denominator, False),
        ]
    if c.deductible_days is not None:
        rows.append(("DEDUCT_DAYS", c.deductible_days, False))
    if c.limit:
        for code, v in (
            ("LIMIT_EVENT_DAYS", c.limit.per_event_days),
            ("LIMIT_TOTAL_DAYS", c.limit.total_days),
            ("LIMIT_COUNT", c.limit.count),
        ):
            if v is not None:
                rows.append((code, v, False))
        for a in c.limit.amounts:
            rows.append((f"LIMIT_AMT_{a.per.upper()}", a.amount, a.selectable))
    if c.extension:
        rows.append(("EXT_DAYS", c.extension.days, False))
        if c.extension.max_visits is not None:
            rows.append(("EXT_VISITS", c.extension.max_visits, False))
        if c.extension.max_visit_days is not None:
            rows.append(("EXT_VISIT_DAYS", c.extension.max_visit_days, False))
    return rows


def save_product(conn: sqlite3.Connection, product: Product, product_id: str) -> None:
    """product 를 product_id 로 저장. 같은 product_id 가 있으면 먼저 지움 (한 트랜잭션)."""
    with conn:
        delete_product(conn, product_id, commit=False)

        def ins(table: str, *values) -> None:
            conn.execute(
                f"INSERT INTO {table} VALUES ({', '.join('?' * (len(values) + 1))})",
                (product_id, *values),
            )

        def sources(target_type: str, target_id: str, refs: list[tuple[str, SourceRef]]) -> None:
            for seq, (role, s) in enumerate(refs, 1):
                ins(
                    "source_ref",
                    target_type,
                    target_id,
                    seq,
                    role,
                    s.part,
                    s.section,
                    s.article,
                    s.paragraph,
                    s.item,
                    s.appendix,
                    s.quote,
                )

        conn.execute(
            "INSERT INTO product VALUES (?, ?, ?, ?)",
            (product_id, product.name, product.insurer, product.version),
        )
        for seq, cc in enumerate(product.coverage_codes, 1):
            ins("coverage_code", cc.code, seq, cc.name)
            for i, k in enumerate(cc.kcd, 1):
                ins(
                    "kcd_range",
                    cc.code,
                    i,
                    k.start,
                    k.end,
                    k.level,
                    k.kcd_version,
                    k.valid_from,
                    k.valid_to,
                )
            if cc.source:
                sources("coverage_code", cc.code, [("primary", cc.source)])

        for cseq, c in enumerate(product.coverages, 1):
            ins("coverage", c.id, cseq, c.name, c.kind)
            if c.source:
                sources("coverage", c.id, [("primary", c.source)])
            for kseq, k in enumerate(c.risks, 1):
                ins("risk", k.id, c.id, kseq, k.section, k.claim_reason, k.coverage_code)
                for rseq, r in enumerate(k.rules, 1):
                    _save_rule(ins, r, k.id, rseq)
                    sources(
                        "rule",
                        r.id,
                        [("primary", r.source)] + [("extra", s) for s in r.extra_sources],
                    )
            for eseq, e in enumerate(c.exclusions, 1):
                ins(
                    "exclusion",
                    e.id,
                    c.id,
                    eseq,
                    e.section,
                    e.kind,
                    e.description,
                    e.coverage_code,
                    e.exception,
                    e.status,
                )
                sources("exclusion", e.id, [("primary", e.source)])


def _save_rule(ins, r: BenefitRule, risk_id: str, seq: int) -> None:
    c, b = r.conditions, r.benefit
    ins(
        "benefit_rule",
        r.id,
        risk_id,
        seq,
        r.name,
        r.insured_role,
        r.policy_status,
        c.facility,
        c.occurrence,
        r.status,
    )
    for i, (code, value, selectable) in enumerate(_conditions(c), 1):
        ins("rule_condition", r.id, i, code, value, int(selectable))
    d = b.deductible
    ins(
        "benefit",
        r.id,
        b.type,
        b.base,
        b.cost_type,
        b.ratio.numerator if b.ratio else None,
        b.ratio.denominator if b.ratio else None,
        b.fixed_amount,
        b.min_amount,
        b.max_amount,
        b.copay_cap_annual,
        d.pick if d else None,
    )
    if d:
        rows = [("AMOUNT", a, None, None) for a in d.amounts]
        rows += [("RATIO", None, x.numerator, x.denominator) for x in d.ratios]
        if d.copay_rate:
            rows.append(("COPAY_RATE", None, None, None))
        for i, row in enumerate(rows, 1):
            ins("deductible", r.id, i, *row)
    for i, s in enumerate(r.special_conditions, 1):
        ins("special_condition", r.id, i, s.type, s.related_rule_id, s.description)
    if r.installment:
        ins("installment", r.id, r.installment.count, r.installment.cycle_months)


def delete_product(conn: sqlite3.Connection, product_id: str, commit: bool = True) -> None:
    for table in PRODUCT_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE product_id = ?", (product_id,))
    if commit:
        conn.commit()


# ---------------------------------------------------------------- 읽기


def list_products(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return conn.execute("SELECT product_id, name FROM product ORDER BY product_id").fetchall()


def load_product(conn: sqlite3.Connection, product_id: str) -> Product:
    conn.row_factory = sqlite3.Row
    try:
        return _load(conn, product_id)
    finally:
        conn.row_factory = None


def _load(conn: sqlite3.Connection, pid: str) -> Product:
    def q(sql: str, *args) -> list[sqlite3.Row]:
        return conn.execute(sql, (pid, *args)).fetchall()

    head = q("SELECT * FROM product WHERE product_id = ?")
    if not head:
        raise LookupError(f"상품 {pid} 가 없습니다.")

    refs: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for s in q(
        "SELECT * FROM source_ref WHERE product_id = ? ORDER BY target_type, target_id, seq"
    ):
        refs.setdefault((s["target_type"], s["target_id"]), []).append(s)

    def to_ref(s: sqlite3.Row) -> SourceRef:
        return SourceRef(
            part=s["part"],
            section=s["section"],
            article=s["article"],
            paragraph=s["paragraph"],
            item=s["item"],
            appendix=s["appendix"],
            quote=s["quote"],
        )

    def primary(target_type: str, target_id: str) -> SourceRef | None:
        rows = [s for s in refs.get((target_type, target_id), []) if s["role"] == "primary"]
        return to_ref(rows[0]) if rows else None

    codes = []
    for cc in q("SELECT * FROM coverage_code WHERE product_id = ? ORDER BY seq"):
        kcd = [
            KcdRange(
                start=k["kcd_start"],
                end=k["kcd_end"],
                level=k["level"],
                kcd_version=k["kcd_version"],
                valid_from=k["valid_from"],
                valid_to=k["valid_to"],
            )
            for k in q(
                "SELECT * FROM kcd_range WHERE product_id = ? AND code = ? ORDER BY seq", cc["code"]
            )
        ]
        codes.append(
            CoverageCode(
                code=cc["code"],
                name=cc["name"],
                kcd=kcd,
                source=primary("coverage_code", cc["code"]),
            )
        )

    coverages = []
    for c in q("SELECT * FROM coverage WHERE product_id = ? ORDER BY seq"):
        risks = []
        for k in q(
            "SELECT * FROM risk WHERE product_id = ? AND coverage_id = ? ORDER BY seq",
            c["coverage_id"],
        ):
            rules = [
                _load_rule(q, r, refs, to_ref)
                for r in q(
                    "SELECT * FROM benefit_rule WHERE product_id = ? AND risk_id = ? ORDER BY seq",
                    k["risk_id"],
                )
            ]
            risks.append(
                Risk(
                    id=k["risk_id"],
                    claim_reason=k["claim_reason"],
                    coverage_code=k["coverage_code"],
                    section=k["section"],
                    rules=rules,
                )
            )
        exclusions = [
            Exclusion(
                id=e["exclusion_id"],
                kind=e["kind"],
                description=e["description"],
                coverage_code=e["coverage_code"],
                exception=e["exception"],
                section=e["section"],
                source=primary("exclusion", e["exclusion_id"]),
                status=e["status"],
            )
            for e in q(
                "SELECT * FROM exclusion WHERE product_id = ? AND coverage_id = ? ORDER BY seq",
                c["coverage_id"],
            )
        ]
        coverages.append(
            Coverage(
                id=c["coverage_id"],
                name=c["name"],
                kind=c["kind"],
                risks=risks,
                exclusions=exclusions,
                source=primary("coverage", c["coverage_id"]),
            )
        )

    h = head[0]
    return Product(
        name=h["name"],
        insurer=h["insurer"],
        version=h["version"],
        coverages=coverages,
        coverage_codes=codes,
    )


def _load_rule(q, r: sqlite3.Row, refs, to_ref) -> BenefitRule:
    rid = r["rule_id"]
    cond = {
        row["item_code"]: row
        for row in q(
            "SELECT * FROM rule_condition WHERE product_id = ? AND rule_id = ? ORDER BY seq", rid
        )
    }

    def val(code: str) -> int | None:
        return int(cond[code]["value"]) if code in cond else None

    amounts = [
        AmountLimit(
            amount=int(row["value"]),
            per=code.removeprefix("LIMIT_AMT_").lower(),
            selectable=bool(row["selectable"]),
        )
        for code, row in cond.items()
        if code.startswith("LIMIT_AMT_")
    ]
    limit_vals = {
        k: val(c)
        for k, c in (
            ("per_event_days", "LIMIT_EVENT_DAYS"),
            ("total_days", "LIMIT_TOTAL_DAYS"),
            ("count", "LIMIT_COUNT"),
        )
    }
    has_limit = amounts or any(v is not None for v in limit_vals.values())
    reduction = None
    if "REDUCE_DAYS" in cond:
        reduction = Reduction(
            days=val("REDUCE_DAYS"),
            ratio=Ratio(
                numerator=cond["REDUCE_RATIO_NUM"]["value"],
                denominator=cond["REDUCE_RATIO_DEN"]["value"],
            ),
        )
    conditions = RuleConditions(
        exemption_days=val("EXEMPT_DAYS"),
        reduction=reduction,
        deductible_days=val("DEDUCT_DAYS"),
        limit=Limit(**limit_vals, amounts=amounts) if has_limit else None,
        occurrence=r["occurrence"],
        facility=r["facility"],
        extension=Extension(
            days=val("EXT_DAYS"),
            max_visits=val("EXT_VISITS"),
            max_visit_days=val("EXT_VISIT_DAYS"),
        )
        if "EXT_DAYS" in cond
        else None,
    )

    b = q("SELECT * FROM benefit WHERE product_id = ? AND rule_id = ?", rid)[0]
    ded_rows = q("SELECT * FROM deductible WHERE product_id = ? AND rule_id = ? ORDER BY seq", rid)
    deductible = None
    if b["deductible_pick"]:
        deductible = Deductible(
            amounts=[d["amount"] for d in ded_rows if d["kind"] == "AMOUNT"],
            ratios=[
                Ratio(numerator=d["ratio_num"], denominator=d["ratio_den"])
                for d in ded_rows
                if d["kind"] == "RATIO"
            ],
            copay_rate=any(d["kind"] == "COPAY_RATE" for d in ded_rows),
            pick=b["deductible_pick"],
        )
    benefit = Benefit(
        type=b["benefit_type"],
        base=b["base"],
        cost_type=b["cost_type"],
        ratio=Ratio(numerator=b["ratio_num"], denominator=b["ratio_den"])
        if b["ratio_num"] is not None
        else None,
        fixed_amount=b["fixed_amount"],
        min_amount=b["min_amount"],
        max_amount=b["max_amount"],
        copay_cap_annual=b["copay_cap_annual"],
        deductible=deductible,
    )

    specials = [
        SpecialCondition(
            type=s["type"], related_rule_id=s["related_rule_id"], description=s["description"]
        )
        for s in q(
            "SELECT * FROM special_condition WHERE product_id = ? AND rule_id = ? ORDER BY seq", rid
        )
    ]
    inst = q("SELECT * FROM installment WHERE product_id = ? AND rule_id = ?", rid)
    srcs = refs.get(("rule", rid), [])
    main = [s for s in srcs if s["role"] == "primary"]
    if not main:
        raise LookupError(f"규칙 {rid} 의 근거(source_ref primary)가 없습니다.")
    return BenefitRule(
        id=rid,
        name=r["name"],
        insured_role=r["insured_role"],
        policy_status=r["policy_status"],
        conditions=conditions,
        special_conditions=specials,
        benefit=benefit,
        installment=Installment(count=inst[0]["count"], cycle_months=inst[0]["cycle_months"])
        if inst
        else None,
        source=to_ref(main[0]),
        extra_sources=[to_ref(s) for s in srcs if s["role"] == "extra"],
        status=r["status"],
    )
