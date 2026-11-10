"""사고보장 데이터(Product)를 화면용 표·테이블·DB 파일로 바꾸는 도우미."""

import sqlite3

from coverage_map.linker import LIMIT_PER, article_label
from coverage_store import connect, save_product
from schema.coverage import BenefitRule, Product

CLAIM_REASON = {
    "diagnosis": "진단",
    "surgery": "수술",
    "hospitalization": "입원",
    "outpatient": "통원",
    "death": "사망",
    "disability": "장해",
    "other": "기타",
}
EXCLUSION_KIND = {"kcd": "질병(KCD)", "cost_item": "비용 항목", "cause": "원인"}


def _won(n: float) -> str:
    return f"{int(n):,}원"


def benefit_text(rule: BenefitRule) -> str:
    b, c = rule.benefit, rule.conditions
    parts = []
    if b.type == "fixed" and b.fixed_amount:
        parts.append(f"정액 {_won(b.fixed_amount)}")
    if b.ratio:
        base = {"sum_insured": "가입금액", "medical_cost": "의료비"}.get(b.base, b.base)
        parts.append(f"{base} × {b.ratio.numerator / b.ratio.denominator:.0%}")
    if b.deductible:
        ded = [_won(a) for a in b.deductible.amounts]
        ded += [f"{r.numerator / r.denominator:.0%}" for r in b.deductible.ratios]
        parts.append(f"공제 {'/'.join(ded)}")
    if c.limit:
        parts += [f"한도 {LIMIT_PER.get(a.per, a.per)} {_won(a.amount)}" for a in c.limit.amounts]
        if c.limit.count:
            parts.append(f"{c.limit.count}회 한도")
    if c.exemption_days:
        parts.append(f"면책 {c.exemption_days}일")
    if c.reduction:
        r = c.reduction
        parts.append(f"{r.days}일 이내 {r.ratio.numerator / r.ratio.denominator:.0%} 지급")
    return " · ".join(parts)


def rule_rows(product: Product) -> list[dict]:
    rows = []
    for cov in product.coverages:
        for risk in cov.risks:
            for r in risk.rules:
                rows.append(
                    {
                        "": "✅" if r.status == "confirmed" else "🟡",
                        "약관": cov.name,
                        "보장종목": risk.section or "",
                        "청구사유": CLAIM_REASON.get(risk.claim_reason, risk.claim_reason),
                        "지급 규칙": r.name,
                        "급부·조건": benefit_text(r),
                        "근거": ", ".join(article_label(s) for s in [r.source, *r.extra_sources]),
                        "id": r.id,
                    }
                )
    return rows


def exclusion_rows(product: Product) -> list[dict]:
    codes = {c.code: c for c in product.coverage_codes}
    rows = []
    for cov in product.coverages:
        for e in cov.exclusions:
            cc = codes.get(e.coverage_code or "")
            kcd = (
                ", ".join(f"{k.start}~{k.end}" if k.start != k.end else k.start for k in cc.kcd)
                if cc
                else ""
            )
            rows.append(
                {
                    "": "✅" if e.status == "confirmed" else "🟡",
                    "약관": cov.name,
                    "보장종목": e.section or "",
                    "종류": EXCLUSION_KIND.get(e.kind, e.kind),
                    "내용": e.description,
                    "KCD": kcd,
                    "예외": e.exception,
                    "근거": article_label(e.source),
                }
            )
    return rows


def _db(product: Product) -> sqlite3.Connection:
    conn = connect(":memory:")
    save_product(conn, product, "product")
    return conn


def store_tables(product: Product) -> dict[str, list[dict]]:
    """coverage_store 테이블 그대로 (테이블 이름 → 행 목록). 비어 있는 테이블도 포함."""
    conn = _db(product)
    conn.row_factory = sqlite3.Row
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        )
    ]
    out = {n: [dict(r) for r in conn.execute(f'SELECT * FROM "{n}"')] for n in names}
    conn.close()
    return out


def sqlite_bytes(product: Product) -> bytes:
    """사고보장 테이블을 담은 SQLite DB 파일 내용."""
    conn = _db(product)
    data = conn.serialize()
    conn.close()
    return data
