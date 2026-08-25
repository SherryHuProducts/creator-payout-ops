# Creator Payout Ops

A creator payout and payment integration system that transforms platform earnings into validated creator payouts, reconciles historical payments, safely initiates payment requests, and confirms final payment status through webhooks.

## Problem

Creator agencies may manage earnings, commission agreements, settlements, refunds, and payments across disconnected workflows. Manual payout operations introduce risks including incorrect commission calculations, duplicate or missing payments, uncertain payment states, and reconciliation errors.

## Workflow

```text
Platform Data
    ↓
Validate → Calculate → Reconcile
                         ↓
                   READY_TO_PAY
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
             Final Reconciliation
```

V1 uses entirely synthetic TikTok-style creator-commerce data and an in-memory mock payment provider. It does not connect to TikTok or transfer real money.

## Key Features

- CSV ingestion and structured validation for synthetic creator-commerce transactions
- Effective-dated creator agreements with overlap and missing-agreement detection
- `Decimal`-based order payouts with deterministic two-decimal rounding
- Creator-level expected-versus-paid reconciliation across `READY_TO_PAY`, `PAID`, `UNDERPAID`, and `OVERPAID`
- Idempotent payment requests, active-pending-payment blocking, and immutable attempt history
- Timeout-safe recovery using the same logical payment request and idempotency key
- Webhook-driven `PAID` / `FAILED` confirmation with duplicate-event protection
- Deterministic payout, reconciliation, and exception CSV reports

## Payment Safety

**Request idempotency:** Repeating the same logical request returns the existing provider payment instead of creating another payment.

**Pending-payment protection:** A new payment is blocked when an equivalent payment attempt is already `PENDING`.

**Timeout-safe retry:** A timeout is treated as an uncertain outcome, not proof of failure. Recovery reuses the original idempotency key.

**Webhook idempotency:** Provider event IDs are recorded after successful processing so duplicate events cannot apply a second state change.

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

## Example Output

```text
Initial Reconciliation
CR-A  Expected $168.00  Paid $168.00  PAID
CR-B  Expected $144.69  Paid $152.82  OVERPAID
CR-D  Expected $92.73   Paid $0.00    READY_TO_PAY

Payment Execution Demo
CR-D  Amount $92.73  PAY-000001  PROV-000001  PENDING

Webhook Confirmation
EVT-DEMO-0001  PENDING → PAID  PROCESSED
Duplicate replay: DUPLICATE; payment state changed: NO

Final Reconciliation
CR-D  Total Paid $92.73  Outstanding $0.00  PAID
```

## Reports

- `data/output/payout_summary.csv` — eligible order counts and expected payout by creator
- `data/output/reconciliation_report.csv` — initial expected-versus-paid amounts and reconciliation status
- `data/output/exceptions.csv` — validation and payout-processing exceptions requiring review

Reports are regenerated deterministically from synthetic demo data whenever the end-to-end demo runs.

## Project Structure

```text
src/creator_payout_ops/
├── payout_engine.py       # Commission calculation
├── reconciliation.py      # Expected vs. paid
├── payment_service.py     # Payment safety & execution
├── payment_provider.py    # Mock provider
├── webhook_handler.py     # Async confirmation
└── reports.py             # Operational reports
```

## Tech

Python 3.11+ · Decimal financial arithmetic · CSV · Payment provider simulation · Webhooks · Pytest

## Tests

60 automated tests cover data loading and validation, effective-dated payout rules, reconciliation, payment eligibility and idempotency, timeout recovery, webhook state transitions, reporting, and the end-to-end workflow.

## Roadmap

**V1 — Creator Payout & Payment Integration:** Complete

**V2 — Multi-Tenant Agency SaaS:** PostgreSQL persistence, authentication, configurable workflows, and operations dashboard.

**V3 — Multi-Platform Creator Finance:** Cross-platform earnings adapters and centralized payout operations.

## Data & Disclaimer

All demo data is synthetic. No proprietary company, creator, customer, banking, or payment data is included.

This project is independent and is not affiliated with TikTok, YouTube, Checkout.com, Stripe, or any payment provider.
