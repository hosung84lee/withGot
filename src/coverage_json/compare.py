"""두 약관에서 뽑은 보장 JSON 목록 비교.

보장끼리 짝을 맞춘 뒤(청구사유 + 이름 유사도 + 보장종목) 주요 필드를 나란히 놓습니다.
"""

import re
from difflib import SequenceMatcher


def _norm(name: str) -> str:
    # 괄호 안(대상 질병 등)도 구분에 쓰고, 약관 구분 표기 '(주계약)' 과 보장종목 《》 만 뺌
    name = re.sub(r"\((주계약|특약)\)|《.*?》", "", name)
    return re.sub(r"[\s·,()]+", "", name)


def _score(a: dict, b: dict) -> float:
    if a.get("claim_reason") != b.get("claim_reason"):
        return 0.0
    sec_a = (a.get("policy") or {}).get("section")
    sec_b = (b.get("policy") or {}).get("section")
    s = SequenceMatcher(None, _norm(a["coverage_name"]), _norm(b["coverage_name"])).ratio()
    if sec_a and sec_a == sec_b:
        s += 0.5
    ka, kb = set(a.get("kcd_code_patterns") or []), set(b.get("kcd_code_patterns") or [])
    if ka and kb:
        s += 0.3 * len(ka & kb) / len(ka | kb)
    return s


def _pct(x) -> str:
    return f"{x:.0%}" if isinstance(x, int | float) else "-"


def _won(x) -> str:
    return f"{int(x):,}원" if isinstance(x, int | float) else "-"


def summary(item: dict) -> dict[str, str]:
    """비교할 필드를 사람이 읽는 글로."""
    out = {
        "청구사유": item.get("claim_reason") or "-",
        "약관": (item.get("policy") or {}).get("policy_name") or "-",
        "보장종목": (item.get("policy") or {}).get("section") or "-",
        "KCD 패턴 수": str(len(item.get("kcd_code_patterns") or [])),
        "면책일수": str(item.get("contract_exemption_days") or "-"),
        "감액기간": ", ".join(
            f"{r['until_days']}일 이내 {_pct(r['ratio'])}"
            for r in item.get("reduction_periods") or []
        )
        or "-",
    }
    benefits = item.get("benefits") or []
    out["보험금"] = (
        "; ".join(
            b["benefit_name"]
            + (
                f" {_pct((b.get('amount') or {}).get('ratio'))}"
                if (b.get("amount") or {}).get("ratio") is not None
                else ""
            )
            + (
                f" ({b['payment_limit']['per']} {b['payment_limit']['count']}회)"
                if b.get("payment_limit") and b["payment_limit"].get("count")
                else ""
            )
            for b in benefits
        )
        or "-"
    )
    ind = item.get("indemnity")
    if ind:
        out["연간 한도"] = _won(ind.get("annual_limit_amount"))
        out["건보 미적용 비율"] = _pct(ind.get("no_health_insurance_ratio"))
        out["실손 규칙"] = " / ".join(
            f"{r.get('care_type')}·{r.get('benefit_category')}"
            + (f"·{r['facility_group']}" if r.get("facility_group") else "")
            + f" {_pct(r.get('covered_ratio'))}"
            + (
                f" 공제 {','.join(_won(v) for v in r['min_deductible_amounts'].values())}"
                if r.get("min_deductible_amounts")
                else ""
            )
            + (f"/{_pct(r['deductible_ratio'])}" if r.get("deductible_ratio") else "")
            for r in ind.get("rules") or []
        )
    out["보상 제외 수"] = str(len(item.get("exclusions") or []))
    return out


def compare_items(a_items: list[dict], b_items: list[dict]) -> dict:
    """짝 맞춘 보장 목록과 필드별 비교. {'pairs': [...], 'only_a': [...], 'only_b': [...]}"""
    cands = sorted(
        ((_score(a, b), i, j) for i, a in enumerate(a_items) for j, b in enumerate(b_items)),
        reverse=True,
    )
    used_a, used_b, pairs = set(), set(), []
    for s, i, j in cands:
        if s < 0.45 or i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        sa, sb = summary(a_items[i]), summary(b_items[j])
        rows = [
            {"필드": k, "A": sa.get(k, "-"), "B": sb.get(k, "-"), "같음": sa.get(k) == sb.get(k)}
            for k in dict.fromkeys([*sa, *sb])
            if k != "약관"
        ]
        pairs.append({"a": a_items[i], "b": b_items[j], "score": round(s, 2), "rows": rows})
    pairs.sort(key=lambda p: p["a"]["coverage_name"])
    return {
        "pairs": pairs,
        "only_a": [x for i, x in enumerate(a_items) if i not in used_a],
        "only_b": [x for j, x in enumerate(b_items) if j not in used_b],
    }
