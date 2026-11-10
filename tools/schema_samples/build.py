"""샘플 약관 7개 원문을 읽고 손으로 옮긴 보장 JSON 예시 → src/schema/json/cov_samples_7policies.json

스키마(coverage.json)가 실제 약관의 보장을 담을 수 있는지 확인하는 용도. 값은 모두 원문(조·별표)에서 옮김.
    uv run python tools/schema_samples/build.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coverage_json import range_to_patterns, validate_items

OUT = ROOT / "src" / "schema" / "json" / "cov_samples_7policies.json"


def kcd(*ranges: str) -> list[str]:
    out = []
    for r in ranges:
        a, _, b = r.partition("~")
        out += range_to_patterns(a, b or a)
    return out


def src(policy, quote, article=None, paragraph=None, item=None, appendix=None):
    return {
        "policy_name": policy,
        "article": article,
        "paragraph": paragraph,
        "item": item,
        "appendix": appendix,
        "quote": quote,
    }


# 별표 악성신생물 분류표 (암) — 인터넷암 2404 별표2 기준 (C44 기타피부암, C73 은 일반암에서 따로 다룸)
CANCER = kcd(
    "C00~C14", "C15~C26", "C30~C39", "C40~C41", "C43", "C45~C49", "C50", "C51~C58",
    "C60~C63", "C64~C68", "C69~C72", "C73", "C74", "C75", "C76~C80", "C81~C96", "C97",
    "D45", "D46", "D47.1", "D47.3", "D47.4", "D47.5",
)  # fmt: skip
CANCER_EXCL = kcd("C44")
IND_2605 = "삼성 급여 실손의료비보장보험(2605)(갱신형, 무배당)"
SEVERE = "중증 비급여 실손의료비보장특약D(갱신형,무배당) 약관"
NONSEVERE = "비중증 비급여 실손의료비보장특약D(갱신형,무배당) 약관"
CA_PLUS = "삼성 암치료플러스종신보험(2605)(무배당,저해약환급금형) 약관"
NONRENEW = "인터넷 비갱신 암보험(2601)(무배당,무해약환급금형) 약관"
ICA = "삼성 인터넷암보험(2404)(갱신형,무배당)"
LTC = "중증간병연금전환특약(무배당) 약관"
CANCER_START = {
    "basis": "최초계약일",
    "waiting_days": 90,
    "renewal_resets": True,
    "reinstatement_waiting_days": 90,
    "description": "계약일부터 그 날을 포함하여 90일이 지난 날의 다음 날(암보장개시일). 갱신계약은 갱신일, 부활은 부활일부터 90일.",
}
ONE_YEAR_HALF = [
    {"basis": "최초계약일", "until_days": 365, "ratio": 0.5, "applies_to_renewal": False}
]
SELF_HARM = {
    "kind": "원인",
    "description": "피보험자가 고의로 자신을 해친 경우 (보험수익자·계약자가 고의로 피보험자를 해친 경우 포함)",
    "exception": "심신상실 등으로 자유로운 의사결정을 할 수 없는 상태에서 자신을 해친 경우는 지급",
}

ITEMS = [
    # ---------------------------------------------------------------- 실손 2605 중증 비급여 3대비급여형
    {
        "coverage_id": "SL-IND2605-R2-TOP3",
        "coverage_name": "3대비급여 (근골격계이학요법·체외충격파, 주사료, 자기공명영상) (중증 비급여 특약)",
        "insured_role": "주피보험자",
        "claim_reason": "의료비",
        "policy": {
            "product_name": IND_2605,
            "policy_name": SEVERE,
            "policy_kind": "보장특약",
            "section": "3대비급여형",
            "renewal": "갱신형",
            "policy_version": "2026-09-23",
        },
        "indemnity": {
            "generation": "5세대",
            "special_case_scope": "산정특례대상",
            "annual_limit_amount": None,
            "extension_after_termination": {"days": 180, "max_outpatient_visits": None},
            "no_health_insurance_ratio": 0.4,
            "rules": [
                {
                    "care_type": "입원·통원",
                    "benefit_category": "근골격계이학요법·체외충격파",
                    "facility_group": "전체",
                    "covered_ratio": None,
                    "min_deductible_amounts": {"1회당": 30000},
                    "deductible_ratio": 0.3,
                    "annual_limit_amount": 3500000,
                    "annual_visit_limit": 50,
                    "visit_step": {
                        "initial_visits": 10,
                        "step_visits": 10,
                        "condition": "객관적·일반적 검사결과로 증상 개선·병변 호전이 확인된 경우에 10회 단위로 연 50회까지",
                    },
                    "source": src(
                        SEVERE, "1회당 3만원과 보장대상의료비의 30%중 큰 금액", "제3조", 1
                    ),
                },
                {
                    "care_type": "입원·통원",
                    "benefit_category": "비급여주사료",
                    "facility_group": "전체",
                    "min_deductible_amounts": {"1회당": 30000},
                    "deductible_ratio": 0.3,
                    "annual_limit_amount": 2500000,
                    "annual_visit_limit": 50,
                    "source": src(SEVERE, "합산하여 250만원 이내에서 50회까지 보상", "제3조", 1),
                },
                {
                    "care_type": "입원·통원",
                    "benefit_category": "비급여자기공명영상",
                    "facility_group": "전체",
                    "min_deductible_amounts": {"1회당": 30000},
                    "deductible_ratio": 0.3,
                    "annual_limit_amount": 3000000,
                    "source": src(SEVERE, "합산하여 300만원 이내에서 보상", "제3조", 1),
                },
            ],
        },
        "benefits": [
            {
                "benefit_code": "SL-IND2605-R2-TOP3-B1",
                "benefit_name": "3대비급여 실손의료비",
                "benefit_description": "본인이 실제로 부담한 비급여의료비에서 공제금액을 뺀 금액을 항목별 보장한도 내에서 보상. 항암제·항생제·희귀의약품 주사료는 질병·상해비급여형에서 보상.",
                "calc_tool_name": "calc_indemnity",
                "amount": {"amount_type": "실손"},
            }
        ],
        "pgm_review_items": [
            {
                "pgm_review_code": "PGM-VISIT-COUNT",
                "pgm_review_name": "연간 보상 횟수·금액 잔여",
                "pgm_review_description": "계약일 또는 계약해당일부터 1년 단위로 항목별 보상 횟수(50회)와 금액(350/250/300만원)을 합산해 잔여를 반환",
                "tool": {"tool_name": "check_annual_usage"},
            }
        ],
        "ai_review_items": [
            {
                "ai_review_group": 1,
                "ai_review_code": "AI-SPECIAL-CASE",
                "ai_review_name": "산정특례 대상 질환 치료 여부",
                "ai_review_description": "진료비 서류에서 산정특례 대상 질환(암·뇌혈관·심장·희귀·중증난치 등) 치료인지 판정. 치료 완료 후 기능회복 목적 이학요법은 미해당.",
            },
            {
                "ai_review_group": 2,
                "ai_review_code": "AI-IMPROVEMENT",
                "ai_review_name": "증상 개선·병변 호전 확인 (11회차 이후)",
                "ai_review_description": "관절가동(ROM)·통증평가척도·자세평가·근력검사(MMT)·초음파 등 이학적 검사로 체절기능부전 개선이 확인되면 통과",
            },
        ],
        "source": src(
            SEVERE,
            "산정특례 대상 질환에 대한 아래의 비급여 의료행위로 치료를 받은 경우",
            "제3조",
            1,
        ),
    },
    # ---------------------------------------------------------------- 실손 2605 비중증 비급여 질병비급여형
    {
        "coverage_id": "SL-IND2605-R1-DIS-NONCOV",
        "coverage_name": "질병 비급여 의료비 (비중증 비급여 특약)",
        "insured_role": "주피보험자",
        "claim_reason": "의료비",
        "policy": {
            "product_name": IND_2605,
            "policy_name": NONSEVERE,
            "policy_kind": "보장특약",
            "section": "질병비급여형",
            "renewal": "갱신형",
            "policy_version": "2026-09-23",
        },
        "indemnity": {
            "generation": "5세대",
            "special_case_scope": "산정특례대상외",
            "annual_limit_amount": 10000000,
            "extension_after_termination": {"days": 180, "max_outpatient_visits": 90},
            "no_health_insurance_ratio": 0.4,
            "rules": [
                {
                    "care_type": "입원",
                    "benefit_category": "비급여",
                    "facility_group": "전체",
                    "covered_ratio": 0.5,
                    "per_admission_limit_amount": 3000000,
                    "source": src(
                        NONSEVERE, "비급여 의료비는 1회당 300만원을 한도로 합니다", "제3조", 1
                    ),
                },
                {
                    "care_type": "입원",
                    "benefit_category": "상급병실료차액",
                    "covered_ratio": 0.5,
                    "daily_limit_amount": 100000,
                    "source": src(NONSEVERE, "1일 평균금액 10만원을 한도로 하며", "제3조", 1),
                },
                {
                    "care_type": "통원",
                    "benefit_category": "비급여",
                    "facility_group": "전체",
                    "min_deductible_amounts": {"1일당": 50000},
                    "deductible_ratio": 0.5,
                    "per_day_limit_amount": 200000,
                    "annual_day_limit": 100,
                    "source": src(NONSEVERE, "1년간 통원 100일을 한도로 합니다", "제3조", 1),
                },
            ],
        },
        "benefits": [
            {
                "benefit_code": "SL-IND2605-R1-DIS-NONCOV-B1",
                "benefit_name": "질병 비급여 실손의료비",
                "benefit_description": "입원 비급여 50%(의원급 1회당 300만원), 상급병실료 차액 50%(1일 평균 10만원), 통원 1일당 비급여에서 5만원과 50% 중 큰 금액 공제(통원 1일당 20만원 이내 선택 한도, 연 100일)",
                "calc_tool_name": "calc_indemnity",
                "amount": {"amount_type": "실손"},
            }
        ],
        "exclusions": [
            {
                "kind": "비용항목",
                "description": "비급여 자기공명영상진단 (비급여자기공명영상진단형에서 보상)",
                "source": src(NONSEVERE, "비급여 자기공명영상진단은 제외합니다", "제3조", 1),
            }
        ],
        "source": src(
            NONSEVERE, "산정특례 대상 질환 외 치료를 받은 경우에는 비급여의료비", "제3조", 1
        ),
    },
    # ---------------------------------------------------------------- 암치료플러스종신 사망보험금Ⅰ (체증)
    {
        "coverage_id": "SL-WL2605-MAIN-DTH1",
        "coverage_name": "사망보험금Ⅰ (체증형) (주계약)",
        "insured_role": "주피보험자",
        "claim_reason": "사망",
        "policy": {
            "product_name": "삼성 암치료플러스종신보험(2605)(무배당,저해약환급금형)",
            "policy_name": CA_PLUS,
            "policy_kind": "주계약",
            "renewal": "비갱신형",
            "policy_version": "2026-09-23",
        },
        "contract_exemption_days": None,
        "benefits": [
            {
                "benefit_code": "SL-WL2605-MAIN-DTH1-B1",
                "benefit_name": "사망보험금Ⅰ",
                "benefit_description": "보험기간(종신) 중 사망. 증액서비스 기간 중이면 증액보험금을 더하고, 이미 납입한 보험료·해약환급금 중 큰 금액 지급.",
                "calc_tool_name": "calc_step_up_death_benefit",
                "amount": {
                    "amount_type": "체증",
                    "base": "보험가입금액",
                    "schedule": [
                        {"from_year": 0, "to_year": 10, "ratio": 1.0, "yearly_step_ratio": None},
                        {"from_year": 10, "to_year": 20, "ratio": 1.0, "yearly_step_ratio": 0.1},
                        {"from_year": 20, "to_year": None, "ratio": 2.0, "yearly_step_ratio": None},
                    ],
                    "minimum_rules": ["이미납입한보험료", "해약환급금"],
                },
                "payment_limit": {"count": 1, "per": "보험기간"},
                "combinable_with": ["SL-WL2605-MAIN-DTH2-B1"],
                "source": src(
                    CA_PLUS, "20년 경과 연계약해당일 이후 보험가입금액의 200%", appendix="별표 1"
                ),
            }
        ],
        "exclusions": [
            {
                **SELF_HARM,
                "exception": SELF_HARM["exception"]
                + ". 보장개시일부터 2년이 지난 후 자살하면 사망보험금 지급",
            }
        ],
        "source": src(
            CA_PLUS, "피보험자가 보험기간(종신) 중 사망하였을 경우 : 사망보험금Ⅰ", "제3조", 1, 1
        ),
    },
    # ---------------------------------------------------------------- 암치료플러스종신 사망보험금Ⅱ (치료 횟수 합산)
    {
        "coverage_id": "SL-WL2605-MAIN-DTH2",
        "coverage_name": "사망보험금Ⅱ (암치료 이력 합산) (주계약)",
        "insured_role": "주피보험자",
        "claim_reason": "사망",
        "policy": {"policy_name": CA_PLUS, "policy_kind": "주계약", "renewal": "비갱신형"},
        "benefits": [
            {
                "benefit_code": "SL-WL2605-MAIN-DTH2-B1",
                "benefit_name": "사망보험금Ⅱ",
                "benefit_description": "제3호~제7호(항암약물·방사선·암수술·중환자실·특정항암호르몬) 지급사유가 발생하고 사망. 치료별 지급사유 발생횟수 × 치료별 지급비율의 합 × 보험가입금액.",
                "calc_tool_name": "calc_treatment_sum_death_benefit",
                "amount": {
                    "amount_type": "치료횟수합산",
                    "base": "보험가입금액",
                    "components": [
                        {"name": "항암약물치료(호르몬치료 제외)보험금", "ratio": 0.1},
                        {"name": "항암방사선치료보험금", "ratio": 0.1},
                        {"name": "암수술보장보험금", "ratio": 0.1},
                        {"name": "중환자실치료보험금", "ratio": 0.05},
                        {"name": "특정항암호르몬약물허가치료보험금", "ratio": 0.01},
                    ],
                },
                "source": src(
                    CA_PLUS, "치료별 사망보험금Ⅱ 산정비율의 합산 × 보험가입금액", appendix="별표 1"
                ),
            }
        ],
        "pgm_review_items": [
            {
                "pgm_review_code": "PGM-TREATMENT-COUNT",
                "pgm_review_name": "치료별 보험금 지급 횟수",
                "pgm_review_description": "제3호~제7호 보험금의 치료별 지급 횟수를 반환",
                "tool": {"tool_name": "count_paid_benefits"},
            }
        ],
        "source": src(
            CA_PLUS, "제3호에서 제7호까지 중 어느 하나의 보험금 지급사유가 발생하고", "제3조", 1, 2
        ),
    },
    # ---------------------------------------------------------------- 암치료플러스종신 항암약물치료 (연 1회, 종합병원 이상)
    {
        "coverage_id": "SL-WL2605-MAIN-TX-CHEMO",
        "coverage_name": "항암약물치료(호르몬치료 제외) (주계약)",
        "insured_role": "주피보험자",
        "claim_reason": "치료",
        "policy": {"policy_name": CA_PLUS, "policy_kind": "주계약", "renewal": "비갱신형"},
        "kcd_code_patterns": CANCER,
        "kcd_exclude_patterns": CANCER_EXCL,
        "kcd_source": "별표2 악성신생물 분류표(기타피부암 및 갑상선암 제외)",
        "contract_exemption_days": 90,
        "coverage_start": CANCER_START,
        "facility_requirement": "종합병원이상",
        "benefits": [
            {
                "benefit_code": "SL-WL2605-MAIN-TX-CHEMO-B1",
                "benefit_name": "항암약물치료(호르몬치료 제외)보험금",
                "benefit_description": "암보장개시일 이후 암 진단 확정, 상급종합병원 혹은 종합병원에서 그 암의 직접적인 치료 목적 항암약물치료",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "보험가입금액", "ratio": 0.1},
                "payment_limit": {"count": 1, "per": "보험연도"},
                "source": src(CA_PLUS, "지급금액 보험가입금액의 10%", appendix="별표 1"),
            }
        ],
        "pgm_review_items": [
            {
                "pgm_review_code": "PGM-YEARLY-ONCE",
                "pgm_review_name": "보험연도 1회 확인",
                "pgm_review_description": "당해 보험연도(계약해당일~차년도 계약해당일 전일)에 이미 지급했는지",
                "tool": {"tool_name": "check_prior_payment"},
            },
            {
                "pgm_review_code": "PGM-FACILITY",
                "pgm_review_name": "의료기관 종별",
                "pgm_review_description": "치료 의료기관이 상급종합병원 또는 종합병원인지 (요양기관 기호·종별)",
                "tool": {"tool_name": "check_facility_type"},
            },
        ],
        "ai_review_items": [
            {
                "ai_review_group": 1,
                "ai_review_code": "AI-DIRECT-TREATMENT",
                "ai_review_name": "암의 직접적인 치료 해당",
                "ai_review_description": "암을 제거·증식 억제하는 치료인지 (합병증·후유증 치료, 면역력 강화, 요양 목적은 미해당). 호르몬치료는 제외.",
            }
        ],
        "source": src(CA_PLUS, "“항암약물치료(호르몬치료 제외)”를 받은 경우", "제3조", 1, 3),
    },
    # ---------------------------------------------------------------- 인터넷비갱신암 2601 암진단 (4대 특정암만 감액)
    {
        "coverage_id": "SL-CA2601-MAIN-DX-4",
        "coverage_name": "암진단 (초기 이외 유방암·중증 갑상선암·자궁암·전립선암) (주계약)",
        "insured_role": "주피보험자",
        "claim_reason": "진단",
        "policy": {
            "policy_name": NONRENEW,
            "policy_kind": "주계약",
            "renewal": "비갱신형",
            "policy_version": "2026-09-23",
        },
        "kcd_code_patterns": kcd("C50", "C73", "C53~C55", "C61"),
        "kcd_source": "별표2 유방·별표3 자궁·별표4 전립선·별표5 갑상선 악성신생물 분류표",
        "contract_exemption_days": 90,
        "coverage_start": CANCER_START | {"renewal_resets": None},
        "reduction_periods": [
            {"basis": "계약일", "until_days": 365, "ratio": 0.5, "applies_to_renewal": False}
        ],
        "benefits": [
            {
                "benefit_code": "SL-CA2601-MAIN-DX-4-B1",
                "benefit_name": "암진단보험금",
                "benefit_description": "「초기 이외 유방암, 중증 갑상선암, 자궁암, 전립선암」 진단 확정. 계약일부터 1년 이내 50%, 1년 초과 100%.",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "보험가입금액", "ratio": 1.0},
                "payment_limit": {"count": 1, "per": "보험기간"},
                "source": src(NONRENEW, "계약일부터 1년 이내 : 보험가입금액의 50%", "제3조"),
            }
        ],
        "ai_review_items": [
            {
                "ai_review_group": 1,
                "ai_review_code": "AI-CAT-SPECIFIC4",
                "ai_review_name": "4대 특정암 해당",
                "ai_review_description": "C50 중 초기유방암(TNM 1기)이 아니고, C73 중 수질성·역형성(중증 갑상선암)이거나, C53~C55(자궁), C61(전립선)이면 통과",
            }
        ],
        "source": src(
            NONRENEW,
            "최초1회에 한하여 보험수익자에게 아래 보험금을 “암진단보험금”으로 지급",
            "제3조",
        ),
    },
    {
        "coverage_id": "SL-CA2601-MAIN-DX-GEN",
        "coverage_name": "암진단 (4대 특정암 이외의 암, 감액 없음) (주계약)",
        "insured_role": "주피보험자",
        "claim_reason": "진단",
        "policy": {"policy_name": NONRENEW, "policy_kind": "주계약", "renewal": "비갱신형"},
        "kcd_code_patterns": CANCER,
        "kcd_exclude_patterns": CANCER_EXCL,
        "contract_exemption_days": 90,
        "coverage_start": CANCER_START | {"renewal_resets": None},
        "reduction_periods": [],
        "benefits": [
            {
                "benefit_code": "SL-CA2601-MAIN-DX-GEN-B1",
                "benefit_name": "암진단보험금",
                "benefit_description": "4대 특정암 이외의 암. 감액기간 없이 보험가입금액의 100%.",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "보험가입금액", "ratio": 1.0},
                "payment_limit": {"count": 1, "per": "보험기간"},
                "excludes": ["SL-CA2601-MAIN-DX-4-B1"],
                "source": src(
                    NONRENEW, "이외의 암으로 진단 확정되었을 경우 보험가입금액의 100%", "제3조"
                ),
            }
        ],
        "source": src(NONRENEW, "이외의 암으로 진단 확정되었을 경우", "제3조"),
    },
    # ---------------------------------------------------------------- 인터넷암 2404 암진단보험금 Ⅰ·Ⅱ·Ⅲ (합산·성별)
    {
        "coverage_id": "SL-CA2404-MAIN-DX-CANCER",
        "coverage_name": "암진단보험금Ⅰ·Ⅱ·Ⅲ (주계약)",
        "insured_role": "주피보험자",
        "claim_reason": "진단",
        "policy": {
            "product_name": ICA,
            "policy_name": f"{ICA} 약관",
            "policy_kind": "주계약",
            "renewal": "갱신형",
        },
        "kcd_code_patterns": CANCER,
        "kcd_exclude_patterns": CANCER_EXCL,
        "kcd_source": "별표2 악성신생물 분류표(기타피부암, 초기유방암, 중증 이외 갑상선암, 비침습 방광암 및 대장점막내암 제외)",
        "sex_restrictions": [
            {"kcd_code_patterns": kcd("C53~C55"), "sex": "여성"},
            {"kcd_code_patterns": kcd("C61"), "sex": "남성"},
        ],
        "contract_exemption_days": 90,
        "coverage_start": CANCER_START,
        "reduction_periods": ONE_YEAR_HALF,
        "benefits": [
            {
                "benefit_code": "SL-CA2404-MAIN-DX-1",
                "benefit_name": "암진단보험금Ⅰ",
                "benefit_description": "모든 암 (자궁암 여성·전립선암 남성 한정)",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "보험가입금액", "ratio": 0.4},
                "payment_limit": {"count": 1, "per": "보험기간"},
                "combinable_with": ["SL-CA2404-MAIN-DX-2", "SL-CA2404-MAIN-DX-3"],
                "source": src(
                    f"{ICA} 약관",
                    "최초계약의 계약일부터 1년 초과 : 보험가입금액의 40%",
                    appendix="별표 1",
                ),
            },
            {
                "benefit_code": "SL-CA2404-MAIN-DX-2",
                "benefit_name": "암진단보험금Ⅱ",
                "benefit_description": "전립선암 이외의 암",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "보험가입금액", "ratio": 0.4},
                "payment_limit": {"count": 1, "per": "보험기간"},
                "combinable_with": ["SL-CA2404-MAIN-DX-1", "SL-CA2404-MAIN-DX-3"],
            },
            {
                "benefit_code": "SL-CA2404-MAIN-DX-3",
                "benefit_name": "암진단보험금Ⅲ",
                "benefit_description": "중증 갑상선암·초기 이외 유방암·자궁암·전립선암 이외의 암",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "보험가입금액", "ratio": 1.2},
                "payment_limit": {"count": 1, "per": "보험기간"},
                "combinable_with": ["SL-CA2404-MAIN-DX-1", "SL-CA2404-MAIN-DX-2"],
            },
        ],
        "premium_waiver": {
            "triggers": [
                {
                    "reason": "진단",
                    "kcd_code_patterns": CANCER,
                    "description": "암보장개시일 이후 납입기간 중 암(소액암 제외) 진단 확정 시 차회 이후 보험료 납입 면제. 갱신 후 같은 암 재진단은 면제 안 함.",
                }
            ]
        },
        "exclusions": [SELF_HARM],
        "source": src(
            f"{ICA} 약관", "암진단보험금Ⅰ, 암진단보험금Ⅱ, 암진단보험금Ⅲ을 합하여", "제3조", item=1
        ),
    },
    # ---------------------------------------------------------------- 인터넷암 2404 재진단암보장특약Ⅱ
    {
        "coverage_id": "SL-CA2404-R3-DX-RECUR",
        "coverage_name": "재진단암치료 (재진단암보장특약Ⅱ)",
        "insured_role": "주피보험자",
        "claim_reason": "진단",
        "policy": {
            "product_name": ICA,
            "policy_name": "삼성인터넷암보험(2404)(갱신형,무배당) 재진단암보장특약Ⅱ 약관",
            "policy_kind": "보장특약",
            "renewal": "갱신형",
        },
        "kcd_code_patterns": CANCER,
        "kcd_exclude_patterns": CANCER_EXCL + kcd("C61"),
        "coverage_start": {
            "basis": "직전진단확정일",
            "waiting_days": 730,
            "renewal_resets": False,
            "description": "첫번째 재진단암: 첫번째 암(기타피부암·갑상선암·비침습 방광암·대장점막내암 제외) 진단 확정일부터 2년이 지난 다음 날. 두번째 이후: 직전 재진단암 진단 확정일부터 2년.",
        },
        "benefits": [
            {
                "benefit_code": "SL-CA2404-R3-DX-RECUR-B1",
                "benefit_name": "재진단암치료보험금",
                "benefit_description": "재진단암 보장개시일 이후 재진단암(전립선암 등 제외) 진단 확정 시 특약보험가입금액의 100% (2년마다 반복 가능)",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "특약보험가입금액", "ratio": 1.0},
                "payment_limit": {"count": None, "per": "진단건별"},
                "source": src(
                    "삼성인터넷암보험(2404)(갱신형,무배당) 재진단암보장특약Ⅱ 약관",
                    "특약보험가입금액의 100%를 재진단암치료보험금으로 지급합니다",
                    "제3조",
                ),
            }
        ],
        "ai_review_items": [
            {
                "ai_review_group": 1,
                "ai_review_code": "AI-RECUR",
                "ai_review_name": "재진단암 해당",
                "ai_review_description": "원발암·전이암·재발암·잔존암에 대해 재진단암 보장개시일 이후 새로 진단 확정되었는지 (제2조의5 재진단암의 정의)",
            }
        ],
    },
    # ---------------------------------------------------------------- 인터넷암 2404 암사망특약Ⅱ
    {
        "coverage_id": "SL-CA2404-R2-DTH-CANCER",
        "coverage_name": "암사망 (암사망특약Ⅱ)",
        "insured_role": "주피보험자",
        "claim_reason": "사망",
        "policy": {
            "product_name": ICA,
            "policy_name": f"{ICA} 암사망특약Ⅱ 약관",
            "policy_kind": "보장특약",
            "renewal": "갱신형",
        },
        "kcd_code_patterns": CANCER + kcd("C44", "D09.0", "D01.0~D01.2"),
        "coverage_start": CANCER_START
        | {
            "description": "암은 최초계약일+90일. 기타피부암·갑상선암·비침습 방광암·대장점막내암은 최초계약의 보장개시일부터"
        },
        "benefits": [
            {
                "benefit_code": "SL-CA2404-R2-DTH-CANCER-B1",
                "benefit_name": "암사망보험금",
                "benefit_description": "암(또는 기타피부암·갑상선암·비침습 방광암·대장점막내암)으로 진단 확정되고 그 암으로 사망",
                "calc_tool_name": "calc_fixed_ratio_benefit",
                "amount": {"amount_type": "가입금액비율", "base": "특약보험가입금액", "ratio": 1.0},
                "payment_limit": {"count": 1, "per": "보험기간"},
            }
        ],
        "ai_review_items": [
            {
                "ai_review_group": 1,
                "ai_review_code": "AI-DEATH-CAUSE",
                "ai_review_name": "사망 원인이 그 암인지",
                "ai_review_description": "사망진단서·의무기록에서 직접 사인이 진단 확정된 암인지 판정",
            }
        ],
    },
    # ---------------------------------------------------------------- 중증간병연금전환특약
    {
        "coverage_id": "SL-LTC-MAIN-ANN-CARE",
        "coverage_name": "중증간병연금 (중증간병연금전환특약)",
        "insured_role": "주피보험자",
        "claim_reason": "간병",
        "policy": {"policy_name": LTC, "policy_kind": "보장특약", "renewal": "비갱신형"},
        "coverage_start": {
            "basis": "연금전환일",
            "waiting_days": 0,
            "description": "보장개시일은 계약자가 신청한 연금전환일",
        },
        "annuity": {
            "annuity_type": "간병연금",
            "payment_trigger": "연금지급개시일 이후 최초의 중증장기요양상태 판정 또는 중증치매상태 진단 확정일(해당일)을 최초로 매년 해당일에 살아 있을 때",
            "max_payments": 10,
            "frequency_options": ["연"],
            "amount_basis": "특약 보험료에서 생존연금 재원을 뺀 금액 기준, 발생률·사망률·공시이율로 산출방법서에 따라 계산",
        },
        "benefits": [
            {
                "benefit_code": "SL-LTC-MAIN-ANN-CARE-B1",
                "benefit_name": "중증간병연금",
                "calc_tool_name": "calc_annuity",
                "amount": {"amount_type": "연금산출"},
                "payment_limit": {"count": 10, "per": "보험기간"},
                "source": src(
                    LTC,
                    "보험기간 중 지급하는 중증간병연금은 10회를 최고 한도로 하여 지급",
                    "제2조",
                    item=2,
                ),
            }
        ],
        "ai_review_items": [
            {
                "ai_review_group": 1,
                "ai_review_code": "AI-LTC-STATE",
                "ai_review_name": "중증장기요양상태 또는 중증치매상태",
                "ai_review_description": "노인장기요양보험 1·2등급 판정(중증장기요양상태) 또는 CDR 3점 이상 중증치매상태 진단 확정 여부",
            }
        ],
    },
    {
        "coverage_id": "SL-LTC-MAIN-ANN-LIFE",
        "coverage_name": "생존연금 (중증간병연금전환특약)",
        "insured_role": "주피보험자",
        "claim_reason": "생존",
        "policy": {"policy_name": LTC, "policy_kind": "보장특약", "renewal": "비갱신형"},
        "annuity": {
            "annuity_type": "생존연금",
            "payment_trigger": "연금지급개시일부터 매년 연계약해당일에 살아 있을 때 (사망해도 보증지급횟수 잔여분 지급)",
            "guaranteed_payments": "최소 10회(기대여명이 10보다 작으면 기대여명, 최소 5회) ~ 최대 100-연금지급개시나이 중 선택",
            "frequency_options": ["연", "월", "3개월", "6개월"],
            "amount_basis": "특약 보험료에서 중증간병연금 재원을 뺀 금액 기준, 연금사망률·공시이율",
        },
        "benefits": [
            {
                "benefit_code": "SL-LTC-MAIN-ANN-LIFE-B1",
                "benefit_name": "생존연금",
                "calc_tool_name": "calc_annuity",
                "amount": {"amount_type": "연금산출"},
                "source": src(
                    LTC,
                    "피보험자가 연금지급개시일부터 매년 연계약해당일에 살아 있을 때",
                    "제2조",
                    item=1,
                ),
            }
        ],
    },
]


def main() -> int:
    errors = validate_items(ITEMS)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(ITEMS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"저장: {OUT} ({len(ITEMS)}개, 스키마 검증 통과)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
