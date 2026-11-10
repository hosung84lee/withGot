"""보장 JSON 스키마(src/schema/json/coverage.json): 검증 · KCD 정규식 · 변환 · 비교 · AI 추출(가짜 LLM)."""

import json
import re
from pathlib import Path

from fakes import fake_llm, gpt

from coverage_json import (
    compare_items,
    load_schema,
    product_to_items,
    range_to_patterns,
    validate_items,
)
from coverage_json.extract import extract_items
from coverage_map.linker import DEFAULT_PRODUCT, load_product
from terms import parse_terms

SCHEMA_DIR = Path(__file__).parent.parent / "src" / "schema" / "json"
FIXTURES = Path(__file__).parent / "fixtures"


def test_schema_is_valid_and_samples_pass():
    import jsonschema

    jsonschema.Draft202012Validator.check_schema(load_schema())
    for name in ("cov_sample.json", "cov_samples_7policies.json"):
        items = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        assert validate_items(items) == [], name


def test_samples_cover_policy_types():
    items = json.loads((SCHEMA_DIR / "cov_samples_7policies.json").read_text(encoding="utf-8"))
    reasons = {x["claim_reason"] for x in items}
    assert {"의료비", "사망", "진단", "치료", "간병", "생존"} <= reasons
    assert any(x.get("annuity") for x in items)
    assert any(
        r.get("visit_step") for x in items if x.get("indemnity") for r in x["indemnity"]["rules"]
    )


def test_validation_reports_errors():
    bad = {
        "coverage_id": "bad id",
        "coverage_name": "x",
        "insured_role": "주피보험자",
        "claim_reason": "몰라",
        "benefits": [],
    }
    errors = validate_items([bad])
    assert any("coverage_id" in e for e in errors) and any("claim_reason" in e for e in errors)


def test_kcd_ranges_to_patterns():
    (p,) = range_to_patterns("C00", "C14")
    assert re.match(p, "C14.9") and re.match(p, "C00") and not re.match(p, "C15")
    (p,) = range_to_patterns("D47.1", "D47.1")
    assert re.match(p, "D47.1") and not re.match(p, "D47.2")
    (p,) = range_to_patterns("C81", "C96")
    assert re.match(p, "C85.1") and not re.match(p, "C80")


def test_product_conversion_is_schema_valid():
    silson = product_to_items(load_product())
    assert validate_items(silson) == []
    (item,) = silson
    assert (
        item["claim_reason"] == "의료비" and item["indemnity"]["no_health_insurance_ratio"] == 0.4
    )
    assert item["coverage_id"] == "SL-IND2605-MAIN-DIS-COV"
    assert len(item["exclusions"]) == 7 and item["exclusions"][0]["kcd_code_patterns"]
    cancer = product_to_items(
        load_product(DEFAULT_PRODUCT.parent / "cancer_2404_diagnosis_draft.json")
    )
    assert validate_items(cancer) == []
    first = cancer[0]
    assert first["claim_reason"] == "진단" and first["contract_exemption_days"] == 90
    assert first["reduction_periods"][0]["ratio"] == 0.5
    assert first["benefits"][0]["amount"]["ratio"] == 0.4


def test_compare_pairs_and_differences():
    a = product_to_items(load_product(DEFAULT_PRODUCT.parent / "cancer_2404_diagnosis_draft.json"))
    b = json.loads(json.dumps(a))
    b[0]["benefits"][0]["amount"]["ratio"] = 0.5
    b.pop()  # B 에는 마지막 보장이 없음
    r = compare_items(a, b)
    assert len(r["pairs"]) == len(b) and len(r["only_a"]) == 1 and r["only_b"] == []
    diffs = [row for p in r["pairs"] for row in p["rows"] if not row["같음"]]
    assert [d["필드"] for d in diffs] == ["보험금"] and "50%" in diffs[0]["B"]


def _cancer_item(ratio=0.4, cid="SL-CA9999-MAIN-DX"):
    return {
        "coverage_id": cid,
        "coverage_name": "암진단",
        "insured_role": "주피보험자",
        "claim_reason": "진단",
        "benefits": [
            {
                "benefit_code": "B1",
                "benefit_name": "암진단보험금",
                "amount": {"amount_type": "가입금액비율", "ratio": ratio},
            }
        ],
    }


def test_ai_extraction_retries_on_schema_errors():
    doc = parse_terms((FIXTURES / "silson_mini.txt").read_text(encoding="utf-8"))
    bad = json.dumps({"items": [_cancer_item(cid="bad id")]}, ensure_ascii=False)
    good = json.dumps({"items": [_cancer_item()]}, ensure_ascii=False)
    llm, calls = fake_llm([gpt({"content": bad}, "stop"), gpt({"content": good}, "stop")])
    out = extract_items(doc, keys=None, llm=llm)
    key = next(iter(out))
    assert out[key]["items"][0]["coverage_id"] == "SL-CA9999-MAIN-DX" and out[key]["errors"] == []
    assert "스키마에 맞지 않습니다" in calls[1]["messages"][-1]["content"]
    assert '"coverage_id"' in calls[0]["messages"][-1]["content"]  # 스키마를 프롬프트에 넣음
