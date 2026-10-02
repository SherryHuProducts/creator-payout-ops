# Creator Payout Ops — API Walkthrough

The FastAPI layer is a thin adapter over the existing payout domain and SQLite
lifecycle repository. It does not calculate payouts, authorize payments, or
apply webhook transitions independently.

## Start the API

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=src python3 -m uvicorn creator_payout_ops.api.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive Swagger walkthrough or
`http://127.0.0.1:8000/openapi.json` for the OpenAPI document.

The default SQLite file is `data/output/api_lifecycle.sqlite3`. Set
`CREATOR_PAYOUT_DB_PATH` to use another lifecycle database.

## Five-endpoint workflow

### 1. Reconcile and create the obligation

`POST /payout-cycles/reconcile`

```json
{
  "payout_cycle_id": "2025-Q3",
  "creator_id": "CR-D"
}
```

This runs the existing calculation and reconciliation services against the
bundled synthetic data and persists `OBL-2025-Q3-CR-D` for `$92.73`.

### 2. Demonstrate the approval gate

Call `POST /obligations/OBL-2025-Q3-CR-D/payments` before approval. The domain
payment service returns HTTP `409` with `PAYMENT_APPROVAL_REQUIRED`.

### 3. Approve the obligation

`POST /obligations/OBL-2025-Q3-CR-D/approve`

```json
{
  "approval_id": "APR-DEMO-0001",
  "approved_by": "demo-finance-reviewer"
}
```

The approver is a demonstration input. Authentication and RBAC are not part of
Portfolio V1.1.

### 4. Initiate the simulated payment

`POST /obligations/OBL-2025-Q3-CR-D/payments`

The response contains the internal attempt ID, `$92.73` amount, stable
idempotency key, `PENDING` state, and simulated provider reference.

### 5. Confirm through the webhook

`POST /webhooks/payments`

```json
{
  "event_id": "EVT-DEMO-0001",
  "event_type": "PAYMENT_SUCCEEDED",
  "provider_payment_id": "PROV-000001",
  "payment_date": "2025-09-30"
}
```

Replay the same request to see `DUPLICATE` without another state transition,
payment record, or paid amount.

### 6. Inspect the final state

`GET /obligations/OBL-2025-Q3-CR-D`

The response combines obligation and approval state, the latest payment,
confirmed payment, final reconciliation, and persisted audit counts. The final
financial state is `PAID` with `$0.00` outstanding.

## Scope boundary

The HTTP server, OpenAPI contract, domain controls, SQLite persistence, and
idempotency behavior are implemented. The provider remains an in-memory
simulation; no external payment network or real funds are involved.
