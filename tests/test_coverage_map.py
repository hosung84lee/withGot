"""보장맵: 서류 → 치료 항목 → 약관 보장 연결."""

import json
from pathlib import Path

import pytest

from coverage_map import build_claim, link_claim, load_product, parse_document, to_dot
from coverage_map.linker import DEFAULT_PRODUCT, kcd_in

RECEIPT = """진료비 계산서·영수증
BOJANGIT SAMPLE V1 RECEIPT
사례번호 | DEMO-001
이름 | 가상 김하늘
진료일 | 2026-11-02
의료기관 | 가상한빛의원
환자 부담 합계 | 563150
"""
DETAIL = """진료비 세부산정내역서
BOJANGIT SAMPLE V1 DETAIL
사례번호 | DEMO-001
치료 | 외래 진찰료 | 급여 | 18500 | 5550
치료 | 혈액 검사 | 급여 | 42000 | 12600
치료 | 복부 MRI | 비급여 | 480000 | 480000
치료 | 영양 주사 | 비급여 | 65000 | 65000
환자 부담 합계 | 563150
"""


def _diagnosis(code: str, case: str = "DEMO-001") -> str:
    return f"진단서\nBOJANGIT SAMPLE V1 DIAGNOSIS\n사례번호 | {case}\n질병분류기호 | {code}\n"


def _map(*docs):
    claim = build_claim([parse_document(name, text) for name, text in docs])
    return link_claim(claim, load_product(), section="질병급여형")


def test_parse_documents():
    r, d = parse_document("r.pdf", RECEIPT), parse_document("d.pdf", DETAIL)
    assert (r.kind, d.kind) == ("RECEIPT", "DETAIL")
    assert [i.benefit for i in d.items] == ["covered", "covered", "uncovered", "uncovered"]
    assert d.items[2].patient == 480000
    claim = build_claim([r, d])
    assert claim.case_id == "DEMO-001"
    assert claim.facility_type == "의원" and claim.setting == "outpatient"
    assert claim.warnings == []


def test_links_outpatient_clinic():
    cmap = _map(("r.pdf", RECEIPT), ("d.pdf", DETAIL))
    status = [link.status for link in cmap.links]
    assert status == ["linked", "linked", "not_covered", "not_covered"]
    rule = cmap.links[0].rule
    assert rule.name.startswith("급여 통원 - 의원")
    assert [s.article for s in cmap.links[0].sources] == ["제3조", "제5조"]
    # 급여 본인부담 18,150 - max(10,000, 20% = 3,630) = 8,150
    (est,) = cmap.estimates
    assert (est.covered, est.deductible, est.payable) == (18150, 10000, 8150)


def test_general_hospital_uses_larger_deductible():
    receipt = RECEIPT.replace("가상한빛의원", "가상대학교종합병원")
    cmap = _map(("r.pdf", receipt), ("d.pdf", DETAIL))
    assert cmap.links[0].rule.name.startswith("급여 통원 - 종합병원")
    assert cmap.estimates[0].deductible == 20000


def test_excluded_diagnosis_and_mismatch_warnings():
    # F10 (알코올 사용 장애): 정신 및 행동장애(F04~F99) 제외, 예외 목록에 없음
    cmap = _map(("r.pdf", RECEIPT), ("d.pdf", DETAIL), ("x.pdf", _diagnosis("F10.2")))
    assert [c for c, _ in cmap.claim_exclusions] == ["F10.2"]
    assert cmap.links[0].status == "excluded"
    assert cmap.links[0].sources[0].article == "제4조"
    assert cmap.estimates == []

    other = _map(("r.pdf", RECEIPT.replace("563150", "100")), ("x.pdf", _diagnosis("X", "DEMO-9")))
    joined = " ".join(other.claim.warnings)
    assert "섞여" in joined and "KCD 형식" in joined


def test_exception_diagnosis_needs_check():
    # F32 (우울 에피소드): F04~F99 제외지만 F30~F39 요양급여는 보상 예외 → 확인 필요
    cmap = _map(("r.pdf", RECEIPT), ("d.pdf", DETAIL), ("x.pdf", _diagnosis("F32.1")))
    assert [link.status for link in cmap.links[:2]] == ["check", "check"]
    assert "예외" in cmap.links[0].notes[0]
    # 조건부 예외(가입 당시 태아면 F80~F89)는 그대로 제외
    cmap = _map(("r.pdf", RECEIPT), ("d.pdf", DETAIL), ("x.pdf", _diagnosis("F84.0")))
    assert cmap.links[0].status == "excluded"


def test_kcd_range():
    assert kcd_in("F32.1", "F04", "F99")
    assert not kcd_in("F03", "F04", "F99")
    assert kcd_in("N39.4", "N39.4", "N39.4") and not kcd_in("N39.3", "N39.4", "N39.4")


def test_dot_has_all_layers():
    dot = to_dot(_map(("r.pdf", RECEIPT), ("d.pdf", DETAIL)))
    for word in ("올린 서류", "치료 항목", "약관 보장", "약관 조항", "제3조①", "제5조⑤"):
        assert word in dot


def test_bundled_product_matches_golden():
    golden = Path(__file__).parent / "fixtures" / "silson_2605_disease_covered.json"
    assert json.loads(DEFAULT_PRODUCT.read_text("utf-8")) == json.loads(golden.read_text("utf-8"))


def test_highlight_ignores_whitespace_and_escapes():
    from coverage_map.policy import highlight

    out = highlight("통원 1 회당 20만원 <한도>", "1회당20만원")
    assert "<mark>1 회당 20만원</mark>" in out and "&lt;한도&gt;" in out
    assert highlight("abc", "") == "abc"


@pytest.mark.pdf
def test_real_policy_pdf_links_to_articles(tmp_path, monkeypatch):
    from coverage_map import policy

    monkeypatch.setattr(policy, "CACHE_DIR", tmp_path)
    pdf = next(p for p in policy.sample_policies() if "2605갱신형" in p.stem)
    data = pdf.read_bytes()
    doc = policy.load_terms(data)
    golden = policy.golden_for(doc)
    assert golden is not None
    report = policy.ground(golden, doc)
    assert report.confirmed == 11 and report.needs_review == 0
    cmap = _map(("r.pdf", RECEIPT), ("d.pdf", DETAIL))
    art = policy.article_for(doc, cmap.links[0].sources[0])
    assert art is not None and art.label == "제3조" and art.section == "질병급여형"
    assert (tmp_path / "text").exists()  # 텍스트 캐시


def test_coverage_view_tables_and_rows():
    from app import coverage_view

    product = load_product()
    tables = coverage_view.store_tables(product)
    assert len(tables["benefit_rule"]) == 4 and len(tables["exclusion"]) == 7
    assert coverage_view.sqlite_bytes(product)[:15] == b"SQLite format 3"
    row = coverage_view.rule_rows(product)[1]
    assert row["청구사유"] == "통원" and "공제 10,000원/20%" in row["급부·조건"]
    assert coverage_view.exclusion_rows(product)[0]["KCD"] == "F04~F99"


def test_merge_combines_same_coverage(tmp_path):
    from coverage_map import policy

    golden = load_product()
    merged = policy.merge([golden, golden.model_copy(update={"coverages": []})], "x")
    assert len(merged.coverages) == 1 and len(merged.rules()) == 4


def test_uncovered_rules_in_other_section_do_not_leak():
    # 다른 보장종목(비급여형)에 비급여 규칙이 있어도 질병급여형에서는 '보상 대상 아님' + 안내
    from coverage_map import policy

    golden = load_product()
    extra = golden.model_copy(deep=True)
    risk = extra.coverages[0].risks[0]
    risk.id, risk.section = "p1/질병비급여형/h1", "질병비급여형"
    rule = risk.rules[0]
    rule.id, rule.name = "p1/질병비급여형/h1/1", "비급여 입원"
    rule.benefit.cost_type = "non_covered"
    extra.coverages[0].id, extra.coverages[0].risks = "p1", [risk]
    extra.coverages[0].exclusions, extra.coverage_codes = [], []
    product = policy.merge([golden, extra], "x")
    claim = build_claim([parse_document("r", RECEIPT), parse_document("d", DETAIL)])
    cmap = link_claim(claim, product, section="질병급여형")
    assert [link.status for link in cmap.links] == [
        "linked",
        "linked",
        "not_covered",
        "not_covered",
    ]
    assert "질병비급여형 에서 확인" in cmap.links[2].notes[0]


def test_diagnosis_links_to_fixed_benefit_by_kcd():
    # 정액형: 진단서 C50.9 → 인터넷암 2404 정답 초안의 암진단보험금 Ⅰ·Ⅱ·Ⅲ (담보코드 암 KCD 범위)
    product = load_product(DEFAULT_PRODUCT.parent / "cancer_2404_diagnosis_draft.json")
    claim = build_claim([parse_document("x.pdf", _diagnosis("C50.9"))])
    cmap = link_claim(claim, product)
    assert [(link.status, link.rule.name) for link in cmap.links] == [
        ("linked", "암진단보험금Ⅰ"),
        ("linked", "암진단보험금Ⅱ"),
        ("linked", "암진단보험금Ⅲ"),
    ]
    assert "가입금액의 40%" in cmap.links[0].notes
    assert cmap.links[0].sources[0].appendix == "별표 1"
    dot = to_dot(cmap)
    assert dot.count("진단서 질병코드") == 1  # 진단 하나는 칸 하나
    # 담보코드에 없는 코드 → 확인 필요 (담보코드 없는 소액암 보장 안내)
    other = link_claim(build_claim([parse_document("x.pdf", _diagnosis("D05.1"))]), product)
    assert [link.status for link in other.links] == ["check"]
    assert "소액암" in other.links[0].notes[0]
