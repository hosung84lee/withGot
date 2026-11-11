"""실제 병원 서식(계산서·영수증, 세부산정내역, 진단서 묶음) 읽기 테스트. 서류 내용은 모두 가상."""

from coverage_map import build_claims, claim_label, link_claim, load_product, parse_documents
from coverage_map.hospital_forms import is_hospital_form, split_documents

RECEIPT_OUT = """[√]외래 [  ]입원    ([  ]퇴원 [  ]중간)    진료비 계산서 · 영수증
환자등록번호 환자 성명 진료기간 야간(공휴일)진료
T-0001 김가상(가명) 2026.07.06 ~ 2026.07.09 [  ]야간 [  ]공휴일
정형외과 - - 건강보험 202607-000001
⑧ 환자부담 총액
((①-⑤)+③+④) 220,0004인실이상
주상병: M54.5 요통(가상)
부상병: M51.2 요추 추간판 장애(가상)
합 계 20,000 46,000 0 200,000
상한액 초과금 0
요양기관 종류 [√]의원급·보건기관   [  ]병원급,   [  ]종합병원,   [  ]상급종합병원
사업자등록번호 000-00-00000 상 호 가상정형외과의원(테스트)
3. 계산서·영수증은 「소득세법」에 따른 의료비 공제신청에 사용할 수 있습니다.
"""
DETAIL_OUT = """진료비 세부산정내역
환자등록번호 환자성명 진료과 진료기간 병실 환자구분 비고(의사명/면허번호) DRG 번호
T-0001 김가상(가명) 정형외과 2026.07.06 ~ 2026.07.09 - 건강보험 정가상 / 00004 -
항목 일자 코드 명칭 금액 횟수 일수 총액
진찰료 07.06 AA154 외래 초진진찰료(의원) 18,410 1 1 18,410 5,520 12,890 0 0
07.09 AA157 외래 재진진찰료(의원) 13,130 1 1 13,130 3,940 9,190 0 0
영상진단료 07.06 G2604 요추 단순촬영(4매) 35,130 1 1 35,130 10,540 24,590 0 0
재활물리 07.06~07.09 MX122 도수치료(30분) 100,000 1 2 200,000 0 0 0 200,000
합 계 266,670 20,000 46,670 0 200,000
"""
RECEIPT_IN = """[  ]외래 [√]입원    ([√]퇴원 [  ]중간)    진료비 계산서 · 영수증
T-0001 김가상(가명) 2026.03.23 ~ 2026.03.29 [  ]야간 [  ]공휴일
유방외과 - W0712 건강보험(산정특례) 202603-004127
주상병: C50.4 유방의 악성신생물(가상)
합 계 100,000 900,000 0 300,000
요양기관 종류 [  ]의원급·보건기관   [  ]병원급,   [√]종합병원,   [  ]상급종합병원
사업자등록번호 000-00-00000 상 호 가상종합병원(테스트)
"""
DETAIL_IN = """진료비 세부산정내역
T-0001 김가상(가명) 유방외과 2026.03.23 ~ 2026.03.29 W0712 건강보험(산정특례) 이가상 / 00001 -
입원료 03.23 AB220 일반병동 입원료(4인실) 78,420 1 6 470,520 60,000 410,520 0 0
처치수술 03.24 N7131 유방부분절제술(악성) 529,480 1 1 529,480 40,000 489,480 0 0
03.24 NB-M001 유착방지제 280,000 1 1 280,000 0 0 0 280,000
제증명수수료 03.29 PDZ01 일반진단서 20,000 1 1 20,000 0 0 0 20,000
합 계 1,300,000 100,000 900,000 0 300,000
"""
DIAGNOSIS = """■ 의료법 시행규칙 [별지 제 5 호의 2 서식] 양식 참고
진   단   서
환자의 성명 김가상(가명) 주민등록번호 780415-2******
병    명 [  ] 임상적 추정     [√] 최종 진단 질병분류 기호 C50.4
C77.3
Z51.0
(방사선
치료 예정)
진단명
주상병 : 좌측 유방 상외측 사분역의 악성 신생물 (침윤성 유관암)
병  기 : pT1c pN1a(sn) M0, Stage IIA (AJCC 8 판 해부학적 병기)
발병일 미상 진단일 2026 년 03 월 10 일
입원일 2026 년 03 월 23 일 퇴원일 2026 년 03 월 29 일
"""
EXTRA = """병 리 검 사 결 과 지
SURGICAL PATHOLOGY REPORT
보 고 일 2026.03.10
방사선치료 확인서 (치료 내역서)
치료 기간 2026.04.27 ~ 2026.06.02
"""
BUNDLE = RECEIPT_OUT + DETAIL_OUT + RECEIPT_IN + DETAIL_IN + DIAGNOSIS + EXTRA


def test_split_bundle_by_title_lines():
    assert is_hospital_form(BUNDLE)
    assert not is_hospital_form(
        "진료비 계산서·영수증\nBOJANGIT SAMPLE V1 RECEIPT\n사례번호 | DEMO-001\n"
    )
    kinds = [k for k, _ in split_documents(BUNDLE)]
    assert kinds == [
        "RECEIPT",
        "DETAIL",
        "RECEIPT",
        "DETAIL",
        "DIAGNOSIS",
        "PATHOLOGY",
        "RADIATION",
    ]
    # 영수증 아래 안내문의 '계산서·영수증은 …' 은 제목 줄이 아님


def test_receipt_and_detail_fields():
    r, d = parse_documents("out.pdf", RECEIPT_OUT + DETAIL_OUT)
    assert r.filename == "out.pdf #1" and d.filename == "out.pdf #2"
    assert r.fields["진료형태"] == "외래" and r.fields["요양기관 종류"] == "의원"
    assert r.fields["의료기관"] == "가상정형외과의원(테스트)"
    assert r.fields["진료기간"] == "2026.07.06 ~ 2026.07.09"
    assert (r.fields["급여 본인부담 합계"], r.fields["비급여 합계"]) == ("20000", "200000")
    assert (
        r.fields["환자 부담 합계"] == "220000"
    )  # 줄이 붙은 '220,0004인실이상' 이 아니라 합계 줄에서
    assert (r.fields["질병분류기호"], r.fields["부상병"]) == ("M54.5", "M51.2")
    assert "이름" not in r.fields and "환자 성명" not in r.fields  # 개인정보는 담지 않음
    assert [(i.name, i.benefit, i.patient, i.days) for i in d.items] == [
        ("외래 초진진찰료(의원)", "covered", 5520, 1),
        ("외래 재진진찰료(의원)", "covered", 3940, 1),
        ("요추 단순촬영(4매)", "covered", 10540, 1),
        ("도수치료(30분)", "uncovered", 200000, 2),
    ]
    assert d.items[3].date == "07.06~07.09" and d.items[3].code == "MX122"


def test_diagnosis_uses_primary_code_only():
    (d,) = parse_documents("dx.pdf", DIAGNOSIS)
    assert d.kind == "DIAGNOSIS"
    assert d.fields["질병분류기호"] == "C50.4" and d.fields["부상병"] == "C77.3, Z51.0"
    assert d.fields["진단일"] == "2026-03-10" and d.fields["퇴원일"] == "2026-03-29"
    assert d.fields["병기"].startswith("pT1c pN1a") and d.fields["진단 구분"] == "최종 진단"
    (claim,) = build_claims([d])
    assert claim.kcd == ["C50.4"]  # 전이(C77.3)·Z 코드는 진단 코드로 쓰지 않음


def test_bundle_becomes_two_claims_and_links():
    docs = parse_documents("bundle.pdf", BUNDLE)
    out, inp = build_claims(docs)
    assert claim_label(out) == "통원 · 가상정형외과의원(테스트) · 2026.07.06 ~ 2026.07.09"
    assert claim_label(inp) == "입원 · 가상종합병원(테스트) · 2026.03.23 ~ 2026.03.29"
    assert (out.facility_type, out.kcd) == (
        "의원",
        ["M54.5"],
    )  # 영수증의 주상병 (진단서 C50.4 아님)
    assert (inp.facility_type, inp.setting, inp.kcd) == ("종합병원", "hospitalization", ["C50.4"])
    assert len(out.items) == 4 and len(inp.items) == 4  # 세부내역은 진료기간이 같은 영수증에만
    assert any("여러 날 통원" in w for w in out.warnings)
    assert not any("다릅니다" in w for w in out.warnings + inp.warnings)  # 영수증 = 세부내역 합계

    product = load_product()
    m_out = link_claim(out, product, section="질병급여형")
    assert [x.status for x in m_out.links] == ["linked", "linked", "linked", "not_covered"]
    (est,) = m_out.estimates
    assert est.rule.name.startswith("급여 통원 - 의원")
    assert (est.covered, est.deductible, est.payable) == (20000, 10000, 10000)

    m_in = link_claim(inp, product, section="질병급여형")
    (est,) = m_in.estimates
    assert est.rule.name == "급여 입원"
    assert (est.covered, est.payable) == (100000, 80000)  # 급여 본인부담의 80%


def test_legacy_sample_format_still_single_document():
    docs = parse_documents(
        "r.txt", "진료비 계산서·영수증\nBOJANGIT SAMPLE V1 RECEIPT\n의료기관 | 가상한빛의원\n"
    )
    assert [d.kind for d in docs] == ["RECEIPT"] and docs[0].filename == "r.txt"
