"""사고보장 Canonical Schema 형식·정합성 검사 테스트."""

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from schema.coverage import KcdRange, Product, RuleConditions, SourceRef

DOC = (Path(__file__).parents[1] / "docs" / "coverage_schema.md").read_text(encoding="utf-8")


def example() -> dict:
    """설계 문서의 예시 JSON 을 그대로 읽음 (문서와 코드가 어긋나지 않게)."""
    body = re.search(r"```json\n(.*?)```", DOC, re.DOTALL).group(1)
    return {"name": "예시 상품", **json.loads(body)}


def test_doc_example_is_valid():
    p = Product.model_validate(example())
    rule = p.rules()[0]
    assert rule.benefit.ratio.value == 0.25
    assert rule.conditions.exemption_days == 90
    assert p.coverage_codes[0].kcd[0].start == "C50"


def test_unknown_coverage_code():
    data = example()
    data["coverages"][0]["risks"][0]["coverage_code"] = "NOPE"
    with pytest.raises(ValidationError, match="담보코드"):
        Product.model_validate(data)


def test_duplicate_rule_id_and_broken_relation():
    data = example()
    rules = data["coverages"][0]["risks"][0]["rules"]
    rules.append(dict(rules[0]))
    with pytest.raises(ValidationError, match="중복"):
        Product.model_validate(data)

    data = example()
    rule = data["coverages"][0]["risks"][0]["rules"][0]
    rule["special_conditions"] = [{"type": "prior_payment", "related_rule_id": "x"}]
    with pytest.raises(ValidationError, match="관계 규칙"):
        Product.model_validate(data)


def test_field_rules():
    with pytest.raises(ValidationError):
        KcdRange(start="C97", end="C00")
    with pytest.raises(ValidationError):
        KcdRange(start="암", end="C00")
    with pytest.raises(ValidationError):
        SourceRef(part="암진단특약")  # 조도 별표도 없음
    with pytest.raises(ValidationError, match="면책기간"):
        RuleConditions(exemption_days=400, reduction={"days": 365, "ratio": {"numerator": 50}})
    data = example()
    data["coverages"][0]["risks"][0]["rules"][0]["benefit"] = {"type": "rate"}
    with pytest.raises(ValidationError, match="ratio"):
        Product.model_validate(data)
