"""정액형(암보험) 근거 검증: 별표 근거와 암진단 정답 초안.

정액형은 지급 금액이 조가 아니라 별표1(보험금 지급기준표)에 있어서, 별표를 근거로 인용문·숫자를
확인할 수 있어야 합니다. 별표 번호는 약관마다 1부터라 source.part 약관 안에서 찾습니다.
"""

import json
from pathlib import Path

import pytest

from coverage_extract.grounding import find_appendix, ground_product, numbers_in
from coverage_store import connect, load_product, save_product
from schema.coverage import Product, SourceRef
from terms import parse_terms
from terms.extract import pdf_to_text

FIXTURES = Path(__file__).parent / "fixtures"
DRAFT = FIXTURES / "cancer_2404_diagnosis_draft.json"
POLICIES = Path(__file__).parent.parent / "insurance-workbench" / "data" / "reference" / "policies"

TWO_PARTS = """보험약관
테스트 암보험 약관
제1관 목적
제1조 [목적]
이 계약은 암을 보장합니다.
제2조 [보험금의 지급사유]
회사는 암으로 진단 확정되면 별표1 보험금 지급기준표의 보험금을 지급합니다.
[별표 1] 보험금 지급기준표
암진단보험금 최초계약의 계약일부터 1년 초과 : 보험가입금액의 40%
최초계약의 계약일부터 1년 이내 : 보험가입금액의 20%
[별표 10] 재해분류표
재해란 우발적인 외래의 사고를 말합니다. 보험가입금액의 99%
테스트 암사망특약 약관
제1조 [목적]
이 특약은 암사망을 보장합니다.
[별표 1] 보험금 지급기준표
암사망보험금 보험가입금액의 100%
"""


def draft() -> Product:
    return Product.model_validate_json(DRAFT.read_text(encoding="utf-8"))


def test_years_read_as_days():
    assert 365.0 in numbers_in("최초계약의 계약일부터 1년 이내")["days"]
    assert 730.0 in numbers_in("보험가입일로부터 2 년이내에 발생한 의료비")["days"]
    assert numbers_in("2026년 1월 1일 시행")["days"] == {1.0}  # 날짜의 '년'은 기간이 아님


def test_find_appendix_by_exact_number_and_part():
    doc = parse_terms(TWO_PARTS)
    main = "테스트 암보험 약관"
    x = find_appendix(doc, SourceRef(part=main, appendix="별표1"))
    assert x is not None and "40%" in x.text and "99%" not in x.text  # 별표 10 과 섞이지 않음
    rider = find_appendix(doc, SourceRef(part="테스트 암사망특약 약관", appendix="별표 1"))
    assert rider is not None and "100%" in rider.text  # 특약의 별표 1 은 따로
    assert find_appendix(doc, SourceRef(part=main, appendix="별표 3")) is None


def test_appendix_quote_and_numbers_are_checked():
    doc = parse_terms(TWO_PARTS)
    part = "테스트 암보험 약관"
    rule = {
        "id": "r1",
        "name": "암진단",
        "conditions": {"reduction": {"days": 365, "ratio": {"numerator": 50}}},
        "benefit": {"type": "rate", "ratio": {"numerator": 40}},
        "source": {"part": part, "appendix": "별표 1", "quote": "보험가입금액의 40%"},
        "extra_sources": [{"part": part, "article": "제2조", "quote": "별표1 보험금 지급기준표"}],
    }
    product = {
        "name": part,
        "coverages": [
            {
                "id": "c",
                "name": part,
                "risks": [{"id": "k", "claim_reason": "diagnosis", "rules": [rule]}],
            }
        ],
    }
    ok = ground_product(Product.model_validate(product), doc)
    assert ok.issues == [] and ok.confirmed == 1  # 40% 는 별표, 1년 → 365일

    rule["benefit"]["ratio"]["numerator"] = 45
    rule["source"]["quote"] = "보험가입금액의 45%"
    bad = ground_product(Product.model_validate(product), doc)
    assert {i.code for i in bad.issues} == {"QUOTE_NOT_FOUND", "NUMBER_NOT_FOUND"}

    rule["source"]["appendix"] = "별표 7"
    missing = ground_product(Product.model_validate(product), doc)
    assert [i.code for i in missing.issues] == ["SOURCE_NOT_FOUND"]


def test_draft_is_valid_and_round_trips_through_tables():
    p = draft()
    assert [r.name for r in p.rules()][:3] == ["암진단보험금Ⅰ", "암진단보험금Ⅱ", "암진단보험금Ⅲ"]
    assert [r.benefit.ratio.numerator for r in p.rules()] == [40, 40, 120, 24, 12]
    assert all(r.conditions.reduction.days == 365 for r in p.rules())
    assert [r.conditions.exemption_days for r in p.rules()] == [90, 90, 90, None, None]
    kcd = {c.code.split("/")[-1]: c for c in p.coverage_codes}
    assert "C44" not in {k.start for k in kcd["CANCER"].kcd}  # 기타피부암은 암에서 빠짐
    conn = connect()
    save_product(conn, p, "cancer-2404")
    assert load_product(conn, "cancer-2404") == p
    assert json.loads(DRAFT.read_text(encoding="utf-8"))["version"].endswith("확인 필요)")


@pytest.mark.pdf
def test_real_cancer_2404_draft_is_grounded():
    pdf = next(POLICIES.glob("삼성생명_인터넷암보험_2404*.pdf"), None)
    if pdf is None:
        pytest.skip("인터넷암보험 2404 약관 PDF 없음")
    report = ground_product(draft(), parse_terms(pdf_to_text(pdf)))
    assert report.issues == []
    assert report.confirmed == 8 and report.needs_review == 0
