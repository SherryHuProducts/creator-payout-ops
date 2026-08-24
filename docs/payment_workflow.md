# Creator Payout Ops — Payment Workflow

**Version:** V1.0  
**Scope:** Payment execution, transaction state management, idempotency, and retry behavior

## 1. Purpose

This document defines how Creator Payout Ops safely executes creator payments after payout calculation and reconciliation.

The payment layer answers one primary question:

> **How can an approved payout be executed safely without creating duplicate payments?**

Payment execution is separate from payout calculation and reconciliation.

```text
Payout Engine
    ↓
Expected Payout
    ↓
Reconciliation
    ↓
READY_TO_PAY
    ↓
Payment Service
    ↓
Payment Provider
    ↓
PENDING
    ↓
Webhook Confirmation
    ↓
PAID / FAILED
```

---

## 2. Payment Eligibility

A payment may only be initiated when reconciliation determines that money is still owed.

Eligible reconciliation states:

| Reconciliation Status | Payment Action |
|---|---|
| `READY_TO_PAY` | Payment may be created |
| `UNDERPAID` | Outstanding balance may be paid |
| `PAID` | No payment |
| `OVERPAID` | No payment; requires review |

The amount submitted to the payment provider must equal the outstanding balance, not the original expected payout.

Example:

```text
Expected Payout:       $700.00
Already Paid:          $500.00
Outstanding Balance:   $200.00

New Payment Amount:    $200.00
```

---

## 3. Active Payment Check

Before creating a new payment, the system must check whether an active payment already exists for the same payout obligation.

An active payment is a payment with status:

```text
PENDING
```

If an active payment already exists:

```text
DO NOT create another payment.
```

Example:

```text
Expected Payout:       $700.00
Completed Payments:      $0.00
Pending Payment:       $700.00

Reconciliation:
READY_TO_PAY

Payment Execution:
BLOCKED — PAYMENT_ALREADY_PENDING
```

This prevents reconciliation from accidentally triggering duplicate payments while a provider is still processing an earlier request.

---

## 4. Payment Request

A payment request must contain enough information to uniquely identify and trace the payout.

Example:

```json
{
  "creator_id": "C001",
  "amount": "700.00",
  "currency": "USD",
  "idempotency_key": "creator-C001-payout-2026-08"
}
```

The system should maintain both:

```text
internal_payment_id
provider_payment_id
```

The internal ID identifies the payment inside Creator Payout Ops.

The provider ID identifies the corresponding transaction at the external payment provider.

---

## 5. Idempotency

Every payment request must include an idempotency key.

The purpose of idempotency is:

> Repeating the same logical payment request must not create multiple payments.

Example:

```text
Request 1
Idempotency-Key: creator-C001-payout-2026-08
        ↓
Payment created
Provider Payment ID: PAY-123

Request 2
Idempotency-Key: creator-C001-payout-2026-08
        ↓
Same logical request detected
        ↓
Return existing PAY-123
```

The second request must not create another payment.

### Idempotency Key Requirements

An idempotency key must:

- identify one logical payout obligation
- remain stable across retries
- not be reused for a different payment
- be stored with the payment record

A retry of the same payment must reuse the original idempotency key.

---

## 6. Payment States

V1 uses the following payment lifecycle:

```text
CREATED
   ↓
PENDING
   ↓
┌─────────┐
↓         ↓
PAID    FAILED
```

Optional future state:

```text
REFUNDED
```

### `CREATED`

The internal payment request has been created but has not yet been accepted by the provider.

### `PENDING`

The provider accepted the request, but the final outcome is not yet confirmed.

### `PAID`

The provider confirmed successful payment.

This is a terminal successful state.

### `FAILED`

The provider confirmed that the payment failed.

A failed payment may require retry or manual review depending on the failure type.

### `REFUNDED`

A previously completed payment was reversed or refunded.

Refund handling is outside the core V1 payment execution flow.

---

## 7. Payment State Transitions

Valid state transitions:

```text
CREATED → PENDING
PENDING → PAID
PENDING → FAILED
```

Future:

```text
PAID → REFUNDED
```

Invalid transitions must be rejected.

Examples:

```text
PAID → PENDING       INVALID
FAILED → PAID        INVALID without a new payment attempt
PAID → CREATED       INVALID
```

A retry after a confirmed failure should create a new payment attempt rather than rewriting the history of the failed attempt.

---

## 8. API Timeout Handling

A timeout does not mean the payment failed.

Example:

```text
Creator Payout Ops
      ↓
POST /payments
      ↓
Payment Provider
      ↓
Payment created successfully
      ↓
Network timeout
      ↓
Creator Payout Ops receives no response
```

The system cannot safely assume:

```text
"No response = no payment"
```

Immediately creating another payment could result in duplicate payment.

Instead:

```text
Timeout
   ↓
Payment outcome UNKNOWN
   ↓
Retry using SAME idempotency key
   ↓
Provider returns existing payment
```

The same logical payment must never receive a new idempotency key simply because the original request timed out.

---

## 9. Retry Rules

Retries must distinguish between uncertain requests, retryable failures, and confirmed non-retryable failures.

### Network / Timeout Failure

```text
Request outcome uncertain
→ Retry allowed
→ Reuse SAME idempotency key
```

### Temporary Provider Failure

Examples:

```text
HTTP 429
HTTP 500
HTTP 502
HTTP 503
```

Treatment:

```text
Retry allowed
→ Reuse SAME idempotency key
→ Apply bounded retry / backoff
```

### Confirmed Payment Failure

Example:

```text
payment.failed webhook received
```

The original payment attempt is now confirmed as failed.

If business rules allow another attempt:

```text
Original attempt → FAILED
New attempt      → new internal payment ID
                 → new idempotency key
```

The failed payment record must not be overwritten.

### Non-Retryable Failure

Examples may include:

```text
invalid recipient
invalid payment configuration
unsupported currency
invalid account
```

Treatment:

```text
Do not automatically retry
→ Manual review required
```

---

## 10. Payment Attempts

One payout obligation may have multiple payment attempts over time.

Example:

```text
Payout Obligation
Creator C001
Outstanding: $700

        ↓

Attempt 1
PAY-001
FAILED

        ↓

Attempt 2
PAY-002
PAID
```

Payment attempts must remain separate records so the complete transaction history can be audited.

---

## 11. Webhook Confirmation

A successful API response does not necessarily mean the creator has been paid.

Example:

```text
POST /payments
      ↓
Provider accepts request
      ↓
PENDING
```

Final payment status is confirmed asynchronously:

```text
Payment Provider
      ↓
Webhook
      ↓
payment.succeeded
or
payment.failed
```

Webhook processing is responsible for updating the internal payment state.

Detailed webhook handling is implemented in the Confirm stage.

---

## 12. Duplicate Webhook Events

Payment providers may deliver the same webhook event more than once.

Example:

```text
payment.succeeded
event_id = EVT-1001

payment.succeeded
event_id = EVT-1001
```

The system must process the event only once.

Webhook event IDs must therefore be stored and checked before processing.

```text
Webhook Received
      ↓
Event ID already processed?
      │
   ┌──┴──┐
  Yes    No
   ↓      ↓
Ignore   Process
```

Duplicate webhook delivery must never create duplicate financial effects.

---

## 13. Reconciliation After Payment

Payment execution does not replace reconciliation.

After a payment reaches `PAID`, reconciliation should be run again.

Example:

```text
Before Payment

Expected:     $700
Paid:           $0
Status: READY_TO_PAY

        ↓

Payment Provider
$700 → PAID

        ↓

Reconciliation Again

Expected:     $700
Paid:         $700
Status: PAID
```

This ensures the system verifies the actual financial outcome rather than assuming execution was successful.

---

## 14. Separation of Responsibilities

The system separates four responsibilities:

```text
Payout Engine
    ↓
How much should be paid?

Reconciliation Engine
    ↓
How much is still owed?

Payment Service
    ↓
Can and should a payment be initiated?

Webhook Handler
    ↓
What actually happened at the provider?
```

This separation prevents provider-specific behavior from becoming coupled to payout calculation rules.

---

## 15. V1 Payment Safety Principles

Creator Payout Ops follows these payment safety principles:

1. Never send money directly from the payout calculation layer.
2. Never treat `PENDING` as successfully paid.
3. Never create another payment while an equivalent payment is still pending.
4. Every payment request must have an idempotency key.
5. Retries of uncertain requests must reuse the same idempotency key.
6. A timeout must never be treated as proof of failure.
7. Confirmed failed attempts must remain in payment history.
8. Duplicate webhook events must be processed only once.
9. Only confirmed `PAID` payments count during reconciliation.
10. Reconciliation must run again after payment completion.

---

## 16. V1 Payment Flow

```text
Reconciliation Result
        ↓
READY_TO_PAY / UNDERPAID
        ↓
Check Existing Pending Payment
        ↓
┌───────────────────────┐
│ Pending exists?       │
└───────────┬───────────┘
        Yes │ No
            │
   BLOCK    ↓
      Create Payment Request
            ↓
      Generate / Reuse
      Idempotency Key
            ↓
       Payment Provider
            ↓
          PENDING
            ↓
     Webhook Confirmation
        ┌───┴────┐
        ↓        ↓
      PAID     FAILED
        ↓        ↓
 Reconcile   Retry / Review
```

---

## 17. V1 Scope Boundary

V1 will simulate an external payment provider rather than transfer real money.

The implementation should demonstrate:

- payment request creation
- provider references
- payment state transitions
- duplicate-payment prevention
- idempotent requests
- timeout handling
- retry behavior
- webhook-driven confirmation
- duplicate webhook protection
- post-payment reconciliation

Real payment credentials, bank accounts, creator financial information, and production payment-provider integrations are outside V1 scope.