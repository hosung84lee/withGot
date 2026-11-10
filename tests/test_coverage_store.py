"""사고보장 데이터 ↔ 테이블(SQLite) 저장·조회 테스트."""

import sqlite3
from pathlib import Path

import pytest

from coverage_store import connect, list_products, load_product, save_product
from coverage_store.__main__ import main
from schema.coverage import Product

GOLDEN = Path(__file__).parent / "fixtures" / "silson_2605_disease_covered.json"


def golden() -> Product:
    return Product.model_validate_json(GOLDEN.read_text(encoding="utf-8"))


def full_product() -> Product:
    """스키마의 모든 필드를 한 번씩 쓰는 정액형 예시 (실손 정답에 없는 필드 확인용)."""
    src = {"part": "암진단특약", "article": "제3조", "paragraph": 1, "item": 2, "quote": "가입금액"}
    return Product.model_validate(
        {
            "name": "예시 암보험",
            "insurer": "예시생명",
            "version": "2026-01-01",
            "coverage_codes": [
                {
                    "code": "CANCER",
                    "name": "암",
                    "kcd": [
                        {
                            "start": "C00",
                            "end": "C97",
                            "level": 1,
                            "kcd_version": 8,
                            "valid_from": "2021-01-01",
                            "valid_to": "9999-12-31",
                        }
                    ],
                    "source": {"part": "암진단특약", "appendix": "별표4", "quote": "C00~C97"},
                }
            ],
            "coverages": [
                {
                    "id": "c1",
                    "name": "암진단특약",
                    "kind": "rider",
                    "source": {"part": "암진단특약", "article": "제1조"},
                    "risks": [
                        {
                            "id": "c1/dx",
                            "claim_reason": "diagnosis",
                            "coverage_code": "CANCER",
                            "rules": [
                                {
                                    "id": "c1/dx/1",
                                    "name": "암 진단",
                                    "insured_role": "secondary",
                                    "policy_status": "정상",
                                    "conditions": {
                                        "exemption_days": 90,
                                        "reduction": {
                                            "days": 365,
                                            "ratio": {"numerator": 1, "denominator": 2},
                                        },
                                        "deductible_days": 3,
                                        "limit": {
                                            "per_event_days": 120,
                                            "total_days": 365,
                                            "count": 1,
                                            "amounts": [{"amount": 3000000, "per": "stay"}],
                                        },
                                        "occurrence": "first",
                                        "facility": "종합병원",
                                        "extension": {
                                            "days": 180,
                                            "max_visits": 90,
                                            "max_visit_days": 60,
                                        },
                                    },
                                    "special_conditions": [
                                        {
                                            "type": "prior_payment",
                                            "related_rule_id": "c1/dx/2",
                                            "description": "소액암 기지급 시 차감",
                                        }
                                    ],
                                    "benefit": {
                                        "type": "rate",
                                        "ratio": {"numerator": 100},
                                        "min_amount": 1000000,
                                        "max_amount": 50000000,
                                    },
                                    "installment": {"count": 20, "cycle_months": 12},
                                    "source": src,
                                    "extra_sources": [{**src, "article": "제4조", "quote": ""}],
                                    "status": "confirmed",
                                },
                                {
                                    "id": "c1/dx/2",
                                    "name": "소액암 진단",
                                    "benefit": {"type": "fixed", "fixed_amount": 2000000},
                                    "source": src,
                                },
                            ],
                        }
                    ],
                    "exclusions": [
                        {"id": "c1/ex1", "kind": "cause", "description": "고의", "source": src}
                    ],
                }
            ],
        }
    )


@pytest.mark.parametrize("make", [golden, full_product], ids=["silson_golden", "all_fields"])
def test_round_trip(make):
    """저장했다가 읽으면 처음과 똑같은 Product 가 나와야 함."""
    conn = connect()
    original = make()
    save_product(conn, original, "p")
    assert load_product(conn, "p") == original


def test_golden_rows():
    conn = connect()
    save_product(conn, golden(), "silson-2605")

    def count(table: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    assert (count("risk"), count("benefit_rule"), count("exclusion")) == (3, 4, 7)
    assert count("source_ref") == 21  # 규칙 근거 9 + 보상 제외 7 + 담보코드 5
    rows = conn.execute(
        "SELECT item_code, value, selectable FROM rule_condition "
        "WHERE rule_id = 'p0/질병급여형/outpatient2/1' ORDER BY seq"
    ).fetchall()
    assert rows == [
        ("LIMIT_AMT_VISIT", 200000, 1),
        ("LIMIT_AMT_YEAR", 50000000, 1),
        ("EXT_DAYS", 180, 0),
        ("EXT_VISITS", 90, 0),
    ]
    ded = conn.execute(
        "SELECT kind, amount, ratio_num FROM deductible "
        "WHERE rule_id = 'p0/질병급여형/outpatient2/2' ORDER BY seq"
    ).fetchall()
    assert ded == [("AMOUNT", 20000, None), ("RATIO", None, 20), ("COPAY_RATE", None, None)]


def test_same_rule_ids_in_two_products_and_overwrite():
    """개정 전후 상품은 규칙 id 가 같아도 product_id 로 구분되고, 같은 id 로 다시 저장하면 덮어씀."""
    conn = connect()
    p = golden()
    save_product(conn, p, "silson-2601")
    save_product(conn, p, "silson-2605")
    save_product(conn, p, "silson-2605")
    assert [pid for pid, _ in list_products(conn)] == ["silson-2601", "silson-2605"]
    assert conn.execute("SELECT COUNT(*) FROM benefit_rule").fetchone()[0] == 8
    assert load_product(conn, "silson-2601") == load_product(conn, "silson-2605")


def test_constraints():
    conn = connect()
    save_product(conn, golden(), "p")
    with pytest.raises(sqlite3.IntegrityError):  # 항목 사전에 없는 참조조건 코드
        conn.execute(
            "INSERT INTO rule_condition VALUES ('p', 'p0/질병급여형/hospitalization1/1', 99, 'NOPE', 1, 0)"
        )
    with pytest.raises(sqlite3.IntegrityError):  # 없는 규칙의 급부
        conn.execute(
            "INSERT INTO benefit (product_id, rule_id, benefit_type, base) "
            "VALUES ('p', 'nope', 'rate', 'sum_insured')"
        )
    with pytest.raises(LookupError):
        load_product(conn, "없는상품")


def test_cli(tmp_path, capsys):
    db = str(tmp_path / "c.db")
    assert main(["save", str(GOLDEN), "--db", db, "--id", "silson-2605"]) == 0
    assert main(["show", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "[silson-2605]" in out and "benefit_rule 4" in out
    target = tmp_path / "out.json"
    assert main(["load", "--db", db, "--id", "silson-2605", "--out", str(target)]) == 0
    assert Product.model_validate_json(target.read_text(encoding="utf-8")) == golden()
