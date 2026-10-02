"""HTTP integration tests for the thin FastAPI lifecycle adapter."""

import pytest
from fastapi.testclient import TestClient

from creator_payout_ops.api import create_app

OBLIGATION_ID = "OBL-2025-Q3-CR-D"


@pytest.fixture
def api(tmp_path):
    app = create_app(database_path=tmp_path / "api.sqlite3")
    with TestClient(app) as client:
        yield client, app


def reconcile(client: TestClient):
    return client.post(
        "/payout-cycles/reconcile",
        json={"payout_cycle_id": "2025-Q3", "creator_id": "CR-D"},
    )


def approve(client: TestClient):
    return client.post(
        f"/obligations/{OBLIGATION_ID}/approve",
        json={
            "approval_id": "APR-DEMO-0001",
            "approved_by": "demo-finance-reviewer",
        },
    )


def initiate(client: TestClient):
    return client.post(f"/obligations/{OBLIGATION_ID}/payments")


def webhook(client: TestClient, provider_id: str, event_id="EVT-DEMO-0001"):
    return client.post(
        "/webhooks/payments",
        json={
            "event_id": event_id,
            "event_type": "PAYMENT_SUCCEEDED",
            "provider_payment_id": provider_id,
            "payment_date": "2025-09-30",
        },
    )


def test_reconciliation_creates_persisted_obligation_with_string_money(api):
    client, _app = api
    response = reconcile(client)

    assert response.status_code == 201
    assert response.json() == {
        "obligation_id": OBLIGATION_ID,
        "creator_id": "CR-D",
        "payout_cycle_id": "2025-Q3",
        "expected_payout": "92.73",
        "previously_paid": "0.00",
        "outstanding": "92.73",
        "reconciliation_status": "READY_TO_PAY",
        "obligation_status": "OUTSTANDING",
    }
    inspected = client.get(f"/obligations/{OBLIGATION_ID}")
    assert inspected.status_code == 200
    assert inspected.json()["lifecycle_status"] == "READY_TO_PAY"


def test_payment_before_approval_is_rejected_by_domain_gate(api):
    client, app = api
    assert reconcile(client).status_code == 201

    response = initiate(client)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PAYMENT_APPROVAL_REQUIRED"
    assert app.state.lifecycle_application.provider.created_payment_count == 0


def test_approval_and_approved_payment_initiation_succeed(api):
    client, _app = api
    reconcile(client)

    approval = approve(client)
    payment = initiate(client)

    assert approval.status_code == 200
    assert approval.json()["decision"] == "APPROVED"
    assert approval.json()["obligation_status"] == "APPROVED"
    assert approval.json()["approved_by"] == "demo-finance-reviewer"
    assert approval.json()["approved_at"].endswith("Z")
    assert payment.status_code == 201
    assert payment.json()["obligation_id"] == OBLIGATION_ID
    assert payment.json()["amount"] == "92.73"
    assert payment.json()["status"] == "PENDING"
    assert payment.json()["provider_reference"] == "PROV-000001"


def test_success_and_duplicate_webhooks_close_financial_loop_once(api):
    client, _app = api
    reconcile(client)
    approve(client)
    payment = initiate(client).json()

    confirmed = webhook(client, payment["provider_reference"])
    duplicate = webhook(client, payment["provider_reference"])
    final = client.get(f"/obligations/{OBLIGATION_ID}")

    assert confirmed.status_code == 200
    assert confirmed.json()["processing_status"] == "PROCESSED"
    assert confirmed.json()["new_payment_status"] == "PAID"
    assert duplicate.status_code == 200
    assert duplicate.json()["processing_status"] == "DUPLICATE"
    assert final.status_code == 200
    body = final.json()
    assert body["lifecycle_status"] == "PAID"
    assert body["latest_payment"]["status"] == "PAID"
    assert body["confirmed_payment"]["amount"] == "92.73"
    assert body["final_reconciliation"] == {
        "expected_payout": "92.73",
        "amount_paid": "92.73",
        "outstanding": "0.00",
        "status": "PAID",
    }
    assert body["audit_trail"] == {
        "approval_records": 1,
        "payment_attempts": 1,
        "webhook_events": 1,
        "confirmed_payments": 1,
    }


def test_duplicate_payment_request_is_blocked_before_provider_call(api):
    client, app = api
    reconcile(client)
    approve(client)
    first = initiate(client)

    duplicate = initiate(client)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "PAYMENT_ALREADY_PENDING"
    assert app.state.lifecycle_application.provider.created_payment_count == 1


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/obligations/OBL-UNKNOWN", None),
        (
            "post",
            "/obligations/OBL-UNKNOWN/approve",
            {"approval_id": "APR-X", "approved_by": "reviewer"},
        ),
        ("post", "/obligations/OBL-UNKNOWN/payments", None),
    ],
)
def test_invalid_obligation_ids_return_not_found(api, method, path, json_body):
    client, _app = api
    response = client.request(method, path, json=json_body)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_unknown_and_invalid_webhook_transitions_are_mapped(api):
    client, _app = api
    unknown = webhook(client, "PROV-UNKNOWN")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "WEBHOOK_REJECTED"

    reconcile(client)
    approve(client)
    payment = initiate(client).json()
    webhook(client, payment["provider_reference"])
    invalid = webhook(client, payment["provider_reference"], "EVT-SECOND")
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "WEBHOOK_REJECTED"
    assert "Invalid payment transition" in invalid.json()["detail"]["message"]


def test_duplicate_reconciliation_is_a_conflict_and_openapi_has_five_routes(api):
    client, _app = api
    assert reconcile(client).status_code == 201
    duplicate = reconcile(client)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "OBLIGATION_ALREADY_EXISTS"

    workflow_paths = {
        path for path in client.get("/openapi.json").json()["paths"]
    }
    assert workflow_paths == {
        "/payout-cycles/reconcile",
        "/obligations/{obligation_id}/approve",
        "/obligations/{obligation_id}/payments",
        "/webhooks/payments",
        "/obligations/{obligation_id}",
    }
