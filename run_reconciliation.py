"""Deterministic end-to-end V1 demonstration for Creator Payout Ops."""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from creator_payout_ops.loaders import (  # noqa: E402
    load_creator_agreements, load_payment_records, load_platform_orders,
)
from creator_payout_ops.models import (  # noqa: E402
    PaymentRecord, PaymentRequest, PaymentStatus, ReconciliationStatus,
    WebhookEvent, WebhookEventType,
)
from creator_payout_ops.payment_provider import MockPaymentProvider  # noqa: E402
from creator_payout_ops.payment_service import PaymentService  # noqa: E402
from creator_payout_ops.payout_engine import aggregate_creator_payouts, calculate_payouts  # noqa: E402
from creator_payout_ops.reconciliation import reconcile_creator_payout, reconcile_payouts  # noqa: E402
from creator_payout_ops.reports import (  # noqa: E402
    write_exception_report, write_payout_summary, write_reconciliation_report,
)
from creator_payout_ops.validators import validate_all  # noqa: E402
from creator_payout_ops.webhook_handler import WebhookHandler  # noqa: E402


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def heading(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def run_demo() -> dict[str, object]:
    """Run and print the complete demo, returning key objects for smoke tests."""

    demo = ROOT / "data" / "demo"
    orders = load_platform_orders(demo / "platform_orders.csv")
    agreements = load_creator_agreements(demo / "creator_agreements.csv")
    historical_payments = load_payment_records(demo / "payment_records.csv")

    print("Creator Payout Ops — V1 End-to-End Demo")
    print("\nLoaded:")
    print(f"- {len(orders)} platform orders")
    print(f"- {len(agreements)} creator agreement records")
    print(f"- {len(historical_payments)} historical payment records")

    validation_issues = validate_all(orders, agreements, historical_payments)
    heading("Validation")
    print(f"Total validation issues: {len(validation_issues)}")
    for issue_type, count in sorted(Counter(i.issue_type for i in validation_issues).items()):
        print(f"{issue_type.upper()}: {count}")

    payout_results = calculate_payouts(orders, agreements)
    payout_counts = Counter(result.status for result in payout_results)
    summaries = aggregate_creator_payouts(payout_results)
    heading("Payout Calculation")
    print(f"Orders processed: {len(payout_results)}")
    print(f"Eligible orders: {payout_counts[ReconciliationStatus.ELIGIBLE]}")
    print(f"Pending settlements: {payout_counts[ReconciliationStatus.PENDING_SETTLEMENT]}")
    print(f"Duplicate orders: {payout_counts[ReconciliationStatus.DUPLICATE_ORDER]}")
    print(f"Missing agreements: {payout_counts[ReconciliationStatus.MISSING_AGREEMENT]}")
    print(f"Invalid agreements: {payout_counts[ReconciliationStatus.INVALID_AGREEMENT]}")
    excluded = payout_counts[ReconciliationStatus.CANCELLED] + payout_counts[ReconciliationStatus.REFUNDED]
    print(f"Excluded cancelled/refunded orders: {excluded}")
    print("\nCreator   Eligible Orders   Expected Payout")
    for summary in summaries:
        print(f"{summary.creator_id:<9} {summary.eligible_order_count:<17} {money(summary.expected_payout)}")

    initial_results = reconcile_payouts(summaries, historical_payments)
    heading("Initial Reconciliation")
    print("Creator   Expected    Paid        Outstanding   Status")
    for result in initial_results:
        print(f"{result.creator_id:<9} {money(result.expected_payout):<11} {money(result.amount_paid):<11} {money(result.outstanding_balance):<13} {result.status.value}")

    output = ROOT / "data" / "output"
    report_paths = {
        "payout_summary": output / "payout_summary.csv",
        "reconciliation": output / "reconciliation_report.csv",
        "exceptions": output / "exceptions.csv",
    }
    write_payout_summary(summaries, report_paths["payout_summary"])
    write_reconciliation_report(initial_results, report_paths["reconciliation"])
    write_exception_report(validation_issues, payout_results, report_paths["exceptions"])
    heading("Reports Generated")
    for path in report_paths.values():
        print(path.relative_to(ROOT))

    selected = next((r for r in initial_results if r.status is ReconciliationStatus.READY_TO_PAY), None)
    selected = selected or next(r for r in initial_results if r.status is ReconciliationStatus.UNDERPAID)
    heading("Payment Execution Demo")
    print(f"Creator: {selected.creator_id}")
    print(f"Status: {selected.status.value}")
    print(f"Outstanding Balance: {money(selected.outstanding_balance)}")

    provider = MockPaymentProvider()
    service = PaymentService(provider)
    attempts = [service.initiate_payment(selected, [])]
    initiated = attempts[0]
    print(f"Internal Payment ID: {initiated.internal_payment_id}")
    print(f"Provider Payment ID: {initiated.provider_payment_id}")
    print(f"Amount: {money(initiated.amount)}")
    print(f"Status: {initiated.status.value}")
    print(f"Idempotency Key: {initiated.idempotency_key}")

    repeated = provider.create_payment(PaymentRequest(
        initiated.creator_id, initiated.amount, initiated.currency, initiated.idempotency_key,
    ))
    heading("Payment Idempotency")
    print(f"Original Provider Payment: {initiated.provider_payment_id}")
    print(f"Repeated Same Request: {repeated.provider_payment_id}")
    print(f"Duplicate Provider Payment Created: {'NO' if provider.created_payment_count == 1 else 'YES'}")

    webhook = WebhookEvent(
        "EVT-DEMO-0001", WebhookEventType.PAYMENT_SUCCEEDED,
        initiated.provider_payment_id or "", None, None,
    )
    handler = WebhookHandler()
    confirmation = handler.process_event(webhook, attempts)
    heading("Webhook Confirmation")
    print(f"Event: {webhook.event_id}")
    print(f"Payment: {webhook.provider_payment_id}")
    print(f"Transition: {confirmation.previous_payment_status.value} → {confirmation.new_payment_status.value}")
    print(f"Result: {confirmation.processing_status.value}")

    confirmed_attempt = attempts[0]
    duplicate = handler.process_event(webhook, attempts)
    heading("Duplicate Webhook")
    print(f"Event: {webhook.event_id}")
    print(f"Result: {duplicate.processing_status.value}")
    print(f"Payment State Changed: {'NO' if attempts[0] is confirmed_attempt else 'YES'}")

    # The reconciliation boundary consumes PaymentRecord. Map the confirmed
    # attempt in memory; no source CSV is changed.
    completed_payment = PaymentRecord(
        confirmed_attempt.internal_payment_id, confirmed_attempt.creator_id,
        date(2025, 9, 30), confirmed_attempt.amount, PaymentStatus.PAID,
        confirmed_attempt.provider_payment_id,
    )
    selected_summary = next(s for s in summaries if s.creator_id == selected.creator_id)
    final = reconcile_creator_payout(selected_summary, [*historical_payments, completed_payment])
    heading("Final Reconciliation")
    print(f"Creator: {final.creator_id}")
    print(f"Expected Payout: {money(final.expected_payout)}")
    print(f"Previously Paid: {money(selected.amount_paid)}")
    print(f"New Confirmed Payment: {money(completed_payment.amount_paid)}")
    print(f"Total Paid: {money(final.amount_paid)}")
    print(f"Outstanding Balance: {money(final.outstanding_balance)}")
    print(f"Final Status: {final.status.value}")

    heading("End-to-End Workflow Complete")
    for label in (
        "Validation", "Payout Calculation", "Reconciliation", "Payment Execution",
        "Request Idempotency", "Webhook Confirmation", "Webhook Idempotency",
        "Final Reconciliation",
    ):
        print(f"{label:<23} ✓")
    print("\nNo real money was transferred.")
    print("All demo data is synthetic.")

    return {
        "selected_reconciliation": selected,
        "initiated_attempt": initiated,
        "confirmed_attempt": confirmed_attempt,
        "duplicate_webhook": duplicate,
        "final_reconciliation": final,
        "provider_payment_count": provider.created_payment_count,
        "report_paths": report_paths,
    }


if __name__ == "__main__":
    run_demo()
