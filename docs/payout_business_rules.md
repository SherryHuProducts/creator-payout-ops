# Creator Payout Ops — Payout Business Rules

**Version:** V1.0
**Scope:** TikTok-style MCN creator payout workflow

## 1. Purpose

This document defines the business rules used to determine whether a platform transaction is eligible for creator payout and how the expected payout amount is calculated.

The payout engine answers one primary question:

> **How much should each creator receive?**

Payment execution and payment reconciliation are handled separately.

---

## 2. Payout Eligibility

Only transactions with a `SETTLED` settlement status are eligible for payout.

| Settlement Status | Payout Treatment                  |
| ----------------- | --------------------------------- |
| `SETTLED`         | Eligible for payout calculation   |
| `PENDING`         | Hold until settlement is complete |
| `CANCELLED`       | Excluded from payout              |
| `REFUNDED`        | Excluded from new payout          |

A pending transaction is not considered invalid. It is simply not yet eligible for payment.

---

## 3. Effective-Dated Creator Agreements

Each eligible transaction must be matched to the creator agreement that was effective on the transaction's `order_date`.

An agreement is applicable when:

```text
active = true

AND

effective_date <= order_date

AND

(end_date is blank OR order_date <= end_date)
```

Example:

```text
Creator A

Agreement 1
2026-01-01 → 2026-06-30
Creator Share: 70%

Agreement 2
2026-07-01 → No End Date
Creator Share: 75%
```

A June 28 order uses the 70% agreement.

A July 3 order uses the 75% agreement.

### Agreement Exceptions

```text
0 matching agreements
→ MISSING_AGREEMENT

1 matching agreement
→ Valid

2+ matching agreements
→ INVALID_AGREEMENT
```

Overlapping agreements must not be resolved automatically because they represent a configuration issue requiring review.

---

## 4. Expected Payout Calculation

For an eligible transaction:

```text
Expected Creator Payout
=
Actual Commission × Creator Share Rate
```

Example:

```text
Actual Commission:    $1,000.00
Creator Share Rate:          70%

Expected Payout:        $700.00
```

All monetary calculations must use `Decimal` rather than floating-point arithmetic.

---

## 5. Refund Treatment

For V1, `actual_commission` represents the platform-confirmed final commission amount.

Therefore, `refund_amount` must not be deducted again during payout calculation.

This prevents refunds from being counted twice.

---

## 6. Duplicate Transactions

Duplicate `order_id` records must not enter payout calculation.

They are classified as:

```text
DUPLICATE_ORDER
```

Duplicate records require review rather than automatic deletion because a duplicate-looking record may represent a legitimate adjustment or source-system issue.

---

## 7. Invalid Records

Transactions containing invalid financial or required data must not enter payout calculation.

Examples include:

* Missing `order_id`
* Missing `creator_id`
* Negative `gross_sales`
* Negative `actual_commission`
* Invalid dates
* Invalid status values

These records are classified as:

```text
INVALID_RECORD
```

---

## 8. Agreement Validation

`creator_share_rate` must be between `0` and `1`, inclusive.

Examples:

```text
0.70 → Valid
1.00 → Valid
-0.10 → Invalid
1.20 → Invalid
```

Agreement date ranges must also be valid.

Invalid rates, invalid date ranges, or overlapping effective agreements are classified as:

```text
INVALID_AGREEMENT
```

---

## 9. One Payout Obligation per Order

Each eligible platform order may generate only one payout obligation.

`order_id` acts as the source transaction identifier and must remain unique throughout payout processing.

Payment execution will introduce separate idempotency controls in the payment layer.

---

## 10. Creator-Level Aggregation

Eligible order-level payouts are aggregated by creator.

Example:

```text
Creator A

Order 101      $70.00
Order 102     $140.00
Order 103      $35.00
---------------------
Expected      $245.00
```

The aggregated expected payout becomes the input to the reconciliation workflow.

---

## 11. Separation of Responsibilities

The system separates payout calculation, payment execution, and reconciliation.

```text
Payout Engine
    ↓
How much SHOULD be paid?
    ↓
Payment Layer
    ↓
Send the payment
    ↓
Reconciliation Engine
    ↓
Was the correct amount actually paid?
```

The payout engine must not directly execute payments.

This separation allows payment providers and payment workflows to change without modifying the core payout calculation rules.

---

## 12. Payout and Exception Statuses

V1 uses the following statuses:

```text
READY_TO_PAY
PAID
UNDERPAID
OVERPAID
PENDING_SETTLEMENT
MISSING_AGREEMENT
DUPLICATE_ORDER
INVALID_RECORD
INVALID_AGREEMENT
```

These statuses provide a consistent foundation for payout processing, exception handling, reconciliation, and future payment integrations.
