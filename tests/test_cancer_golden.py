"""정액형(암보험) 근거 검증: 별표 근거와 암진단 정답 초안.

정액형은 지급 금액이 조가 아니라 별표1(보험금 지급기준표)에 있어서, 별표를 근거로 인용문·숫자를
확인할 수 있어야 합니다. 별표 번호는 약관마다 1부터라 source.part 약관 안에서 찾습니다.
"""

import json
from pathlib import Path

import pytest

from coverage_extract import build_bundles
from coverage_extract.compare import compare_products
from coverage_extract.gaps import analyze_gaps
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


def test_extension_visit_days_vs_visits():
    """계약 종료 후 통원 한도: '최대 90일' 은 max_visit_days, '최대 90회' 는 max_visits 로 따로 확인."""
    part = "테스트 비급여 특약 약관"
    doc = parse_terms(
        f"보험약관\n{part}\n제1조 [목적]\n이 특약은 비급여를 보장합니다.\n제3조 [보상내용]\n"
        "① 회사는 비급여의료비의 50%에 해당하는 금액을 보상합니다.\n"
        "② 보험계약 종료일 다음 날부터 180일 이내의 통원을 보상하며 최대 90일 한도 내에서 보상합니다.\n"
    )

    def product(ext: dict) -> Product:
        rule = {
            "id": "r1",
            "name": "비급여 통원",
            "conditions": {"extension": {"days": 180, **ext}},
            "benefit": {"type": "actual_cost", "base": "medical_cost", "ratio": {"numerator": 50}},
            "source": {
                "part": part,
                "article": "제3조",
                "paragraph": 1,
                "quote": "50%에 해당하는 금액",
            },
            "extra_sources": [
                {"part": part, "article": "제3조", "paragraph": 2, "quote": "최대 90일"}
            ],
        }
        risk = {"id": "k", "claim_reason": "outpatient", "rules": [rule]}
        return Product.model_validate(
            {"name": part, "coverages": [{"id": "c", "name": part, "risks": [risk]}]}
        )

    assert ground_product(product({"max_visit_days": 90}), doc).issues == []
    wrong_unit = ground_product(product({"max_visits": 90}), doc)
    assert [i.code for i in wrong_unit.issues] == ["NUMBER_NOT_FOUND"]  # 원문은 90회가 아니라 90일
    conn = connect()
    save_product(conn, product({"max_visit_days": 90}), "p")
    assert load_product(conn, "p").rules()[0].conditions.extension.max_visit_days == 90


# ---------------------------------------------------------------- 정액형 묶음·비교·갭


def test_fixed_bundle_includes_own_payment_table():
    """정액형 묶음에는 그 약관의 지급기준표가 들어가고, 재해분류표·다른 약관 별표는 빠짐."""
    bundles = {b.key: b for b in build_bundles(parse_terms(TWO_PARTS))}
    main = bundles["테스트 암보험 약관"]
    assert [x.label for x in main.appendices] == ["별표 1 보험금 지급기준표"]
    body = main.render()
    assert "### 별표 1 보험금 지급기준표" in body and "보험가입금액의 40%" in body
    assert "재해분류표" not in body and "암사망보험금" not in body


def test_fixed_rules_matched_by_benefit_name():
    """정액형 규칙은 보험금 이름으로 짝지음 (청구사유가 모두 diagnosis 라 순서로는 못 맞춤)."""
    golden = draft()
    shuffled = draft()
    shuffled.coverages[0].risks.reverse()
    assert compare_products(shuffled, golden).score == 1.0

    wrong = draft()
    rules = {r.name: r for r in wrong.rules()}
    rules["암진단보험금Ⅲ"].benefit.ratio.numerator = 100
    rules["암진단보험금Ⅰ"].conditions.exemption_days = None
    rules["암진단보험금Ⅱ"].conditions.reduction = None
    result = compare_products(wrong, golden)
    text = "\n".join(result.different)
    assert len(result.different) == 3 and not result.missing and not result.extra
    assert "암진단보험금Ⅲ" in text and "면책기간" in text and "감액" in text


CANCER_TERMS = """보험약관
테스트 암보험 약관
제1조 [목적]
이 계약은 암을 보장합니다.
제2조 [암의 정의 및 진단 확정]
① 이 계약에 있어서 "초기유방암"이라 함은 별표3에서 정한 질병 중 AJCC 암병기설정매뉴얼 제8판에서 정한 1기에 해당하는 경우를 말합니다.
② 이 계약에 있어서 "초기 이외 유방암"이라 함은 "유방암"에 해당하는 질병 중 "초기유방암"을 제외한 나머지 유방암을 말합니다.
③ 암의 진단 확정은 병리과 전문의 자격증을 가진 자에 의하여 내려져야 합니다.
제3조 [보험금의 지급사유]
① 피보험자가 암보장개시일 이후에 암으로 진단 확정 되었을 경우 암진단보험금을 지급합니다. (단, 최초 1회에 한하며, 자궁암은 피보험자가 여성인 경우에 한합니다.)
제4조 [보험금 지급에 관한 세부규정]
① 암으로 진단 확정 되었을 때에는 차회 이후의 보험료 납입을 면제합니다.
② 이미 암진단보험금이 지급된 암으로 인한 경우(종양세포가 잔존하거나 재발 또는 전이된 경우 포함)에 회사는 해당 보험금을 지급하지 않습니다.
[별표 1] 보험금 지급기준표
암진단보험금 보험가입금액의 100%
"""


def test_fixed_concepts_found():
    found = {f.concept.code for f in analyze_gaps(parse_terms(CANCER_TERMS)).findings}
    assert found == {
        "STAGE_CRITERIA",
        "CODE_SUBTRACTION",
        "DIAGNOSIS_METHOD",
        "INSURED_SEX",
        "PREMIUM_WAIVER",
        "RECURRENCE",
    }


@pytest.mark.pdf
def test_real_cancer_2404_bundle_and_gaps():
    pdf = next(POLICIES.glob("삼성생명_인터넷암보험_2404*.pdf"), None)
    if pdf is None:
        pytest.skip("인터넷암보험 2404 약관 PDF 없음")
    doc = parse_terms(pdf_to_text(pdf))
    main = next(b for b in build_bundles(doc) if b.section is None and "약관" in b.key)
    assert (len(main.articles), len(main.appendices)) == (11, 9)  # 정의 조 + 별표 1~9
    assert len(main.render()) < 30000

    report = analyze_gaps(doc, draft())
    fixed = {f.concept.code for f in report.findings}
    assert len(fixed) == 10 and "STAGE_CRITERIA" in fixed and "GROUPED_OCCURRENCE" in fixed
    assert [(c.units, c.cited) for c in report.coverage] == [(60, 17)]
    reasons = [x.reason for x in report.uncovered]
    assert (
        reasons.count("schema_gap"),
        reasons.count("uncited_value"),
        reasons.count("extraction_gap"),
    ) == (38, 1, 4)
