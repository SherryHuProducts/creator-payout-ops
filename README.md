# Creator Payout Ops

A creator payout and payment integration system that transforms platform earnings into validated creator payouts, reconciles historical payments, safely initiates payment requests, and durably confirms final payment status through webhooks. A thin FastAPI adapter makes the workflow externally demonstrable without duplicating domain logic.

## Problem

Creator agencies may manage earnings, commission agreements, settlements, refunds, and payments across disconnected workflows. Manual payout operations introduce risks including incorrect commission calculations, duplicate or missing payments, uncertain payment states, and reconciliation errors.

## Workflow

```text
Platform Data
    ↓
FastAPI Adapter
    ↓
Validate → Calculate → Reconcile
                         ↓
                   READY_TO_PAY
                         ↓
                 Payout Obligation
                         ↓
                      Approval
                         ↓
                   Payment Service
                         ↓
                   Mock Provider
                         ↓
                       PENDING
                         ↓
                       Webhook
                       ↙       ↘
                    PAID     FAILED
                     ↓
              SQLite Audit Trail
                     ↓
             Final Reconciliation
```

V1 uses entirely synthetic TikTok-style creator-commerce data, a lightweight SQLite lifecycle store, and an in-memory mock payment provider. It does not connect to TikTok or transfer real money.

## Key Features

- CSV ingestion and structured validation for synthetic creator-commerce transactions
- Effective-dated creator agreements with overlap and missing-agreement detection
- `Decimal`-based order payouts with deterministic two-decimal rounding
- Creator-level expected-versus-paid reconciliation across `READY_TO_PAY`, `PAID`, `UNDERPAID`, and `OVERPAID`
- Explicit payout obligations and approval records between reconciliation and payment execution
- SQLite persistence for obligations, approvals, payment attempts, webhook events, and confirmed payments
- Five-endpoint FastAPI workflow with interactive OpenAPI documentation
- Idempotent payment requests, active-pending-payment blocking, and separate attempt history
- Timeout-safe recovery using the same logical payment request and idempotency key
- Webhook-driven `PAID` / `FAILED` confirmation with duplicate-event protection
- Deterministic payout, reconciliation, and exception CSV reports

## Payment Safety

**Approval gate:** Reconciliation identifies an outstanding balance but does not authorize payment. The payment service requires an approved obligation and its matching approval record.

**Request idempotency:** Repeating the same logical request returns the existing provider payment instead of creating another payment.

**Pending-payment protection:** A new payment is blocked when an equivalent payment attempt is already `PENDING`.

**Timeout-safe retry:** A timeout is treated as an uncertain outcome, not proof of failure. Recovery reuses the original idempotency key.

**Webhook idempotency:** Processed provider event IDs are stored in SQLite, so duplicate events cannot apply a second state change or payment record—even after restart.

**Confirmed-payment boundary:** A successful webhook atomically marks the payment attempt `PAID`, records the webhook, and creates the confirmed `PaymentRecord` consumed by final reconciliation.

## Quick Start

```bash
git clone https://github.com/SherryHuProducts/creator-payout-ops.git
cd creator-payout-ops
python3 -m pip install -r requirements.txt
python3 run_reconciliation.py
```

Run the tests:

```bash
PYTHONPATH=src python3 -m pytest
```

Start the API:

```bash
PYTHONPATH=src python3 -m uvicorn creator_payout_ops.api.main:app --reload
```

Open Swagger UI at `http://127.0.0.1:8000/docs`. The walkthrough uses five endpoints:

1. `POST /payout-cycles/reconcile`
2. `POST /obligations/{obligation_id}/approve`
3. `POST /obligations/{obligation_id}/payments`
4. `POST /webhooks/payments`
5. `GET /obligations/{obligation_id}`

The HTTP API and SQLite lifecycle are real. The external payment provider and webhook payload are intentionally simulated. See [`docs/api_workflow.md`](docs/api_workflow.md) for the request sequence.

## Example Output

```text
Initial Reconciliation
CR-A  Expected $168.00  Paid $168.00  PAID
CR-B  Expected $144.69  Paid $152.82  OVERPAID
CR-D  Expected $92.73   Paid $0.00    READY_TO_PAY

Payout Obligation
OBL-2025-Q3-CR-D  Outstanding $92.73  OUTSTANDING

Approval Gate
Payment Before Approval: BLOCKED

Approval
APR-DEMO-0001  OBL-2025-Q3-CR-D  APPROVED

Payment Execution Demo
CR-D  Amount $92.73  PAY-000001  PROV-000001  PENDING

Webhook Confirmation
EVT-DEMO-0001  PENDING → PAID  PROCESSED
Webhook and confirmed payment persisted

Duplicate Webhook After Restart
EVT-DEMO-0001  DUPLICATE  Confirmed payment records: 1

Final Reconciliation
CR-D  Total Paid $92.73  Outstanding $0.00  PAID
```

## Reports

- `data/output/payout_summary.csv` — eligible order counts and expected payout by creator
- `data/output/reconciliation_report.csv` — final expected-versus-paid amounts and reconciliation status, including persisted confirmed payments
- `data/output/exceptions.csv` — validation and payout-processing exceptions requiring review

Reports are regenerated deterministically from synthetic demo data whenever the end-to-end demo runs. The synthetic demo SQLite file is also rebuilt on each run and remains available afterward for audit review.

## Project Structure

```text
src/creator_payout_ops/
├── api/                   # FastAPI adapter & HTTP contracts
├── payout_engine.py       # Commission calculation
├── reconciliation.py      # Expected vs. paid
├── obligations.py         # Obligation creation & approval
├── payment_service.py     # Payment safety & execution
├── payment_provider.py    # Mock provider
├── webhook_handler.py     # Async confirmation
├── repositories/sqlite.py # Durable lifecycle & audit trail
└── reports.py             # Operational reports
```

## Tech

Python 3.11+ · FastAPI · OpenAPI · SQLite · Decimal financial arithmetic · CSV · Payment provider simulation · Pytest

## Tests

99 automated tests cover HTTP integration, data loading and validation, effective-dated payout rules, reconciliation, obligation and approval controls, durable payment and webhook idempotency, SQLite integrity, audit reconstruction, reporting, and the end-to-end workflow.

GitHub Actions runs the complete pytest suite on every push and pull request using Python 3.12.

## Roadmap

**V1 — Creator Payout & Payment Integration:** Complete

**V2 — Multi-Tenant Agency SaaS:** PostgreSQL persistence, authentication, configurable workflows, and operations dashboard.

**V3 — Multi-Platform Creator Finance:** Cross-platform earnings adapters and centralized payout operations.

## Data & Disclaimer

All demo data is synthetic. No proprietary company, creator, customer, banking, or payment data is included.

This project is independent and is not affiliated with TikTok, YouTube, Checkout.com, Stripe, or any payment provider.
