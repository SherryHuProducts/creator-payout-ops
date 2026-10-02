# Creator Payout & Reconciliation System

**A controlled financial workflow for payout calculation → reconciliation → approval → payment → confirmation.**

[![Tests](https://github.com/SherryHuProducts/creator-payout-ops/actions/workflows/tests.yml/badge.svg)](https://github.com/SherryHuProducts/creator-payout-ops/actions/workflows/tests.yml)

This portfolio case study shows how creator earnings can move from raw transaction data to an approved, traceable, and reconciled payment outcome.

| In 30 seconds | What this project demonstrates |
|---|---|
| **Business problem** | Creator payouts depend on transaction quality, changing agreements, prior payments, and payment-provider outcomes. Manual handling creates risk of incorrect, missing, or duplicate payments. |
| **Money movement** | Orders are validated, payout rules are applied, outstanding balances are reconciled, obligations are approved, payments are initiated, and webhooks confirm the result. |
| **Financial controls** | Exact money calculations, reconciliation, explicit approval, payment and webhook idempotency, state-transition rules, SQLite constraints, and final reconciliation. |
| **What I built** | The payout domain, control workflow, five-endpoint REST API, simulated provider boundary, durable SQLite audit trail, CSV reporting, and automated test suite. |
| **Scope** | The workflow, API, controls, persistence, and tests are implemented. The payment provider and webhook delivery are simulated; all business data is synthetic. |

> ▶ **Watch the 3–4 Minute Project Walkthrough** — coming soon

## Payout lifecycle

**Orders → Rules → Reconciliation → Obligation → Approval → Payment → Webhook → Final Reconciliation**

1. Validate settled orders and select the effective creator agreement.
2. Calculate expected payouts with exact decimal arithmetic.
3. Reconcile expected payouts against completed payment history.
4. Create an obligation only when an eligible balance remains outstanding.
5. Require approval before payment execution.
6. Send an idempotent request to the simulated provider.
7. Confirm the result through a durable webhook workflow.
8. Reconcile again using the persisted confirmed payment.

<!-- VISUAL PLACEHOLDER 1: End-to-end payout lifecycle. -->

## Worked financial example: CR-D

The complete system can be understood through one verified payout.

### Initial reconciliation

| Financial state | Amount / status |
|---|---:|
| Expected payout | **$92.73** |
| Previously paid | **$0.00** |
| Outstanding | **$92.73** |
| Reconciliation status | **READY_TO_PAY** |

### Controlled execution

~~~text
OBL-2025-Q3-CR-D created for $92.73
        ↓
Payment before approval: BLOCKED
        ↓
APR-DEMO-0001 recorded: APPROVED
        ↓
PAY-000001 submitted with obligation-based idempotency
        ↓
PROV-000001 returned by the simulated provider
        ↓
EVT-DEMO-0001 confirms payment: PENDING → PAID
        ↓
Same webhook replayed: DUPLICATE, no second financial effect
~~~

### Final reconciliation

| Financial state | Amount / status |
|---|---:|
| Expected payout | **$92.73** |
| Paid | **$92.73** |
| Outstanding | **$0.00** |
| Final status | **PAID** |

The primary reconciliation report is regenerated from persisted confirmed payment history, so it reflects the completed financial state rather than stopping at the pre-payment view.

<!-- VISUAL PLACEHOLDER 3: CR-D $92.73 reconciliation before/after. -->

## Financial controls

| Control | Why it exists | How this project implements it |
|---|---|---|
| Effective-dated agreements | A creator's payout rate may change over time. | Agreement selection uses each order's date and detects missing or overlapping agreement coverage. |
| Transaction validation | Bad or duplicate source records can distort payouts. | Structured validators identify duplicate order IDs and invalid order, agreement, and payment data before payout processing. |
| Reconciliation | A correct calculation does not prove that the correct amount has been paid. | Expected payout is compared with completed payment history to classify balances as ready, paid, underpaid, or overpaid. |
| Explicit approval gate | An outstanding balance should not authorize its own disbursement. | Reconciliation creates an obligation; a separate approval record is required before the payment service will proceed. |
| Exact money arithmetic | Binary floating point can introduce financial rounding errors. | Monetary values use Python <code>Decimal</code> with deterministic cent-level rounding. |
| Payment idempotency | Retries or duplicate submissions must not create duplicate effective payments. | The stable identity <code>payout-{obligation_id}-{currency}</code> is persisted and protected by application checks and SQLite constraints. |
| Webhook idempotency | Providers may deliver the same event more than once. | Processed event IDs are persisted; replay returns <code>DUPLICATE</code> without another transition, payment record, or paid amount. |
| State-transition controls | Out-of-order events can corrupt financial status. | Only defined obligation and payment transitions are accepted; invalid transitions are rejected. |
| Durable audit trail | Finance and operations teams need evidence linking authorization to outcome. | SQLite relates the obligation, approval, attempts, provider reference, webhook event, and confirmed payment. |
| Final reconciliation | Initiating a payment is not proof of settlement. | Only webhook-confirmed <code>PAID</code> records count as paid, and reconciliation runs again after confirmation. |

These controls demonstrate system-enforced workflow separation. The project does **not** claim authenticated human segregation of duties, RBAC, or production payment-provider controls.

## Architecture

~~~text
FastAPI / HTTP
      ↓
Application orchestration
      ↓
Existing domain services
      ├── Calculation, reconciliation, approval, payment rules
      ├── SQLite lifecycle repository (real, durable)
      └── Mock payment provider (simulated external boundary)
                    ↓
          Simulated provider webhook
                    ↓
       Durable confirmation + final reconciliation
~~~

The API translates HTTP requests and domain failures. Business rules remain in the tested domain services, and SQLite supplies persistence and financial traceability without an ORM.

### Implementation boundaries

| Boundary | Status |
|---|---|
| REST API and OpenAPI contract | **Implemented** |
| Calculation, reconciliation, approval, and payment rules | **Implemented** |
| SQLite persistence and database constraints | **Implemented** |
| Payment and webhook idempotency | **Implemented** |
| Automated tests and GitHub Actions CI | **Implemented** |
| External payment provider | **Simulated** |
| Provider webhook delivery | **Simulated** |
| Creator, order, agreement, and historical payment data | **Synthetic** |

## Portfolio API

The FastAPI adapter exposes only the five operations needed to demonstrate the financial lifecycle.

| Endpoint | Business purpose |
|---|---|
| <code>POST /payout-cycles/reconcile</code> | Calculate and reconcile the selected creator's synthetic payout, then persist an eligible obligation. |
| <code>POST /obligations/{id}/approve</code> | Record authorization for an outstanding obligation. |
| <code>POST /obligations/{id}/payments</code> | Initiate the approved payout through the existing idempotent payment service. |
| <code>POST /webhooks/payments</code> | Deliver a simulated provider result through the durable webhook workflow. |
| <code>GET /obligations/{id}</code> | Review obligation, approval, payment, confirmation, final reconciliation, and audit counts. |

Swagger UI is available at <code>/docs</code>. Detailed request examples are in [the API walkthrough](docs/api_workflow.md).

## Payment safety and idempotency

### What happens if the payment request is submitted twice?

The payment identity is based on the obligation, not on an individual HTTP request:

~~~text
payout-OBL-2025-Q3-CR-D-USD
~~~

Before contacting the provider, the payment service loads persisted attempts. If the same identity is already <code>PENDING</code> or <code>PAID</code>, another effective payment is blocked. SQLite also enforces one effective <code>PENDING</code> or <code>PAID</code> attempt for that identity.

The mock provider separately returns the same simulated provider payment for a repeated request using the same key and parameters. In a real integration, provider-side guarantees would depend on the selected provider honoring the submitted idempotency key.

### What happens if the webhook is delivered twice?

The first valid success event atomically:

1. changes the attempt from <code>PENDING</code> to <code>PAID</code>;
2. stores the processed event ID; and
3. creates the confirmed payment record.

The same event after restart returns <code>DUPLICATE</code>. It does not create another payment record or increase the paid amount again.

<!-- VISUAL PLACEHOLDER 2: Payment state + idempotency model. -->

## Audit trail

For one payout obligation, the system can reconstruct:

**Obligation → Approval → Payment Attempt → Provider Reference → Webhook Event → Confirmed Payment → Final Reconciliation**

This matters because finance and operations reviewers need to answer more than “was a request sent?” They need to trace why money was owed, who or what authorized the workflow, which provider reference was involved, which event confirmed the outcome, and whether the final ledger view reconciles.

## Tests and CI

**Verified result: 99 tests passing.**

The suite covers:

- payout rules, agreement selection, validation, and reconciliation;
- obligation creation and approval controls;
- payment eligibility, retry identity, and duplicate prevention;
- durable SQLite persistence and database integrity;
- webhook transitions, restart-safe replay protection, and confirmed payments;
- final reconciliation and reports; and
- the five-endpoint HTTP workflow and error mapping.

GitHub Actions installs the pinned application dependencies and runs the complete pytest suite on every push and pull request.

## Real, simulated, and synthetic

| Category | Included |
|---|---|
| **Real implementation** | FastAPI HTTP layer, financial workflow and domain logic, approval control, reconciliation, SQLite persistence, idempotency mechanisms, CSV reporting, automated tests, and CI. |
| **Simulated boundary** | External payment provider behavior and provider webhook delivery. |
| **Synthetic inputs** | Creator, order, agreement, and historical payment data. |
| **Not implemented** | Real money movement, authentication, RBAC, webhook signatures, production provider integration, and production concurrency hardening. |

No proprietary business, creator, customer, banking, or payment data is included. The project is independent and is not affiliated with TikTok, YouTube, Stripe, Checkout.com, or another payment provider.

## Design decisions

- **<code>Decimal</code> instead of <code>float</code>:** keeps financial arithmetic exact and rounding explicit.
- **Approval separate from reconciliation:** distinguishes “money is outstanding” from “payment is authorized.”
- **Obligation-based payment identity:** gives retries a stable business key across application restarts.
- **Webhook confirmation before completion:** a submitted or pending request is never counted as paid.
- **SQLite for portfolio-scale durability:** provides inspectable constraints and auditability without turning the project into a database-platform exercise.

## Project structure

~~~text
src/creator_payout_ops/
├── api/
│   ├── app.py                  # FastAPI routes and HTTP error mapping
│   ├── application.py          # HTTP-to-domain orchestration
│   └── schemas.py              # Request and response contracts
├── payout_engine.py            # Commission calculation
├── reconciliation.py           # Expected-versus-paid logic
├── obligations.py              # Obligation creation and approval
├── payment_service.py          # Approval gate and payment idempotency
├── payment_provider.py         # Simulated external provider
├── webhook_handler.py          # Payment confirmation workflow
├── repositories/
│   └── sqlite.py               # Durable lifecycle and audit trail
└── reports.py                  # Finance-facing CSV outputs
~~~

## Run locally

Requires Python 3.11 or newer.

~~~bash
git clone https://github.com/SherryHuProducts/creator-payout-ops.git
cd creator-payout-ops
python3 -m pip install -r requirements.txt
~~~

Run the deterministic CLI case study:

~~~bash
python3 run_reconciliation.py
~~~

Start the API:

~~~bash
PYTHONPATH=src python3 -m uvicorn creator_payout_ops.api.main:app --reload
~~~

Then open <code>http://127.0.0.1:8000/docs</code>.

Run all tests:

~~~bash
PYTHONPATH=src python3 -m pytest
~~~

## Documentation

- [API walkthrough](docs/api_workflow.md)
- [Payment workflow and controls](docs/payment_workflow.md)
- [Payout business rules](docs/payout_business_rules.md)
- [Backend architecture](docs/V1_1_BACKEND_ARCHITECTURE.md)

## Limitations and scope

Creator Payout Portfolio V1.1 is a controlled, portfolio-scale financial workflow—not a production payment platform.

- The API currently operates on the bundled synthetic dataset.
- The external provider and webhook delivery are simulations.
- Approval captures a reviewer identifier but does not authenticate a human user.
- Webhook signatures, secrets, authentication, RBAC, production concurrency controls, deployment infrastructure, and real payment credentials are intentionally out of scope.
- The synthetic CLI and API SQLite files are suitable for demonstration and audit inspection, not production transaction processing.

Application functionality is feature frozen for Portfolio V1.1 unless a verified defect prevents the demonstration.
