import copy
import json

import pytest
from app.main import app
from fastapi.testclient import TestClient

PAYLOAD = {
    "rule_version": "synthetic-v1",
    "contract": {"standard": "enrolled", "mri": "unknown", "injection": "not_enrolled"},
    "items": [
        {"item_id": 1, "kind": "consultation", "benefit": "covered",
         "total_won": 18500, "patient_won": 5550},
        {"item_id": 2, "kind": "mri", "benefit": "uncovered",
         "total_won": 480000, "patient_won": 480000},
        {"item_id": 3, "kind": "injection", "benefit": "uncovered",
         "total_won": 65000, "patient_won": 65000},
    ],
}
MARKER = "PRIVATE-PATIENT-TRACE-48291"


def test_candidate_contract():
    response = TestClient(app).post("/api/coverage/candidates", json=PAYLOAD)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "rule_version": "synthetic-v1", "synthetic": True,
        "items": [
            {"item_id": 1, "coverage": "standard", "status": "candidate",
             "checks": ["공제·한도와 실제 적용 약관 확인"]},
            {"item_id": 2, "coverage": "mri", "status": "missing_information",
             "checks": ["담보 가입 여부와 급여 구분 확인"]},
            {"item_id": 3, "coverage": "injection", "status": "not_enrolled",
             "checks": ["사용자가 선택한 가상 계약에서 해당 담보 미가입"]},
        ],
    }


def test_covered_mri_uses_standard_synthetic_coverage():
    payload = copy.deepcopy(PAYLOAD)
    payload["items"][1]["benefit"] = "covered"
    response = TestClient(app).post("/api/coverage/candidates", json=payload)
    assert response.status_code == 200
    assert response.json()["items"][1]["coverage"] == "standard"
    assert response.json()["items"][1]["status"] == "candidate"


@pytest.mark.parametrize("location", ["root", "contract", "item", "enum", "amount", "key"])
def test_private_input_is_rejected_without_reflection(location, caplog):
    payload = copy.deepcopy(PAYLOAD)
    if location == "root":
        payload["patient_name"] = MARKER
    elif location == "contract":
        payload["contract"]["policy_number"] = MARKER
    elif location == "item":
        payload["items"][0]["source"] = {"text": MARKER}
    elif location == "enum":
        payload["items"][0]["kind"] = MARKER
    elif location == "amount":
        payload["items"][0]["total_won"] = MARKER
    else:
        payload[MARKER] = MARKER
    response = TestClient(app).post("/api/coverage/candidates", json=payload)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    assert MARKER not in response.text
    assert MARKER not in caplog.text


@pytest.mark.parametrize("change", ["duplicate", "overpayment", "boolean", "too_many", "empty"])
def test_invalid_cost_and_item_sets(change):
    payload = copy.deepcopy(PAYLOAD)
    if change == "duplicate":
        payload["items"][1]["item_id"] = 1
    elif change == "overpayment":
        payload["items"][0]["patient_won"] = 18501
    elif change == "boolean":
        payload["items"][0]["patient_won"] = True
    elif change == "too_many":
        payload["items"] *= 34
    else:
        payload["items"] = []
    assert TestClient(app).post("/api/coverage/candidates", json=payload).status_code == 422


def test_streamed_body_limit_without_content_length():
    chunks = (b" " * 8192 for _ in range(5))
    response = TestClient(app).post(
        "/api/coverage/candidates", content=chunks, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


def test_malformed_json_does_not_echo_body(caplog):
    response = TestClient(app).post(
        "/api/coverage/candidates", content='{"name":"' + MARKER,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert MARKER not in response.text + caplog.text


def test_non_json_and_queries_rejected():
    client = TestClient(app)
    assert client.post("/api/coverage/candidates", content=json.dumps(PAYLOAD)).status_code == 415
    response = client.post("/api/coverage/candidates?unused=trace", json=PAYLOAD)
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


def test_trailing_slash_does_not_redirect_or_reflect_query():
    response = TestClient(app, follow_redirects=False).post(
        f"/api/coverage/candidates/?patient={MARKER}", json=PAYLOAD
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert "location" not in response.headers
    assert MARKER not in response.text


def test_unknown_benefit_cannot_rule_out_coverage_based_on_one_rider():
    payload = copy.deepcopy(PAYLOAD)
    payload["items"][1]["benefit"] = "unknown"
    payload["contract"]["mri"] = "not_enrolled"
    response = TestClient(app).post("/api/coverage/candidates", json=payload)
    assert response.status_code == 200
    assert response.json()["items"][1]["status"] == "missing_information"


@pytest.mark.parametrize("amount", [0, 100_000_000])
def test_money_limits_include_endpoints(amount):
    payload = copy.deepcopy(PAYLOAD)
    payload["items"][0].update(total_won=amount, patient_won=amount)
    assert TestClient(app).post("/api/coverage/candidates", json=payload).status_code == 200


def test_minimal_request_matches_legacy_result():
    client = TestClient(app)
    legacy = copy.deepcopy(PAYLOAD)
    legacy["items"] = legacy["items"][:2]
    minimal = {
        "rule_version": "synthetic-v1",
        "contract": {"standard": "enrolled", "mri": "unknown"},
        "items": [
            {"item_id": 1, "kind": "consultation", "benefit": "covered"},
            {"item_id": 2, "kind": "mri", "benefit": "uncovered"},
        ],
    }
    response = client.post("/api/coverage/candidates", json=minimal)
    assert response.status_code == 200
    assert response.json() == client.post("/api/coverage/candidates", json=legacy).json()
    del minimal["contract"]["mri"]
    assert client.post("/api/coverage/candidates", json=minimal).status_code == 422
    minimal["items"][1]["benefit"] = "unknown"
    assert client.post("/api/coverage/candidates", json=minimal).status_code == 200


def test_legacy_costs_must_be_provided_together():
    payload = copy.deepcopy(PAYLOAD)
    del payload["items"][0]["patient_won"]
    assert TestClient(app).post("/api/coverage/candidates", json=payload).status_code == 422
