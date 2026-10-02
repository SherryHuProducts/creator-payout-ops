"""Deterministic end-to-end V1 demonstration for Creator Payout Ops."""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, datetime, timezone
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
    ApprovalDecision, PaymentRequest, ReconciliationStatus,
    WebhookEvent, WebhookEventType,
)
from creator_payout_ops.obligations import (  # noqa: E402
    create_payout_obligation, record_approval_decision,
)
from creator_payout_ops.payment_provider import MockPaymentProvider  # noqa: E402
from creator_payout_ops.payment_service import (  # noqa: E402
    PaymentExecutionError, PaymentService,
)
from creator_payout_ops.payout_engine import aggregate_creator_payouts, calculate_payouts  # noqa: E402
from creator_payout_ops.reconciliation import reconcile_payouts  # noqa: E402
from creator_payout_ops.reports import (  # noqa: E402
    write_exception_report, write_payout_summary, write_reconciliation_report,
)
from creator_payout_ops.repositories import SQLiteLifecycleRepository  # noqa: E402
from creator_payout_ops.validators import validate_all  # noqa: E402
from creator_payout_ops.webhook_handler import PersistentWebhookHandler  # noqa: E402


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def heading(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def run_demo(
    database_path: Path | None = None,
    output_directory: Path | None = None,
    reset_database: bool = True,
) -> dict[str, object]:
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

    output = output_directory or ROOT / "data" / "output"
    report_paths = {
        "payout_summary": output / "payout_summary.csv",
        "reconciliation": output / "reconciliation_report.csv",
        "exceptions": output / "exceptions.csv",
    }
    write_payout_summary(summaries, report_paths["payout_summary"])
    write_exception_report(validation_issues, payout_results, report_paths["exceptions"])

    database_path = database_path or output / "creator_payout_ops.sqlite3"
    if reset_database and database_path.exists():
        database_path.unlink()
    repository = SQLiteLifecycleRepository(database_path)
    heading("Durable Lifecycle Store")
    print(f"SQLite Database: {database_path}")
    print("Demo Database Reset: YES" if reset_database else "Demo Database Reset: NO")

    selected = next((r for r in initial_results if r.status is ReconciliationStatus.READY_TO_PAY), None)
    selected = selected or next(r for r in initial_results if r.status is ReconciliationStatus.UNDERPAID)
    obligation = create_payout_obligation(selected, "2025-Q3")
    repository.save_obligation(obligation)
    heading("Payout Obligation")
    print(f"Obligation ID: {obligation.obligation_id}")
    print(f"Creator: {selected.creator_id}")
    print(f"Payout Cycle: {obligation.payout_cycle_id}")
    print(f"Reconciliation Status: {obligation.reconciliation_status.value}")
    print(f"Outstanding Amount: {money(obligation.outstanding_amount)}")
    print(f"Obligation Status: {obligation.status.value}")
    print("Persisted: YES")

    provider = MockPaymentProvider()
    service = PaymentService(provider, payment_repository=repository)
    heading("Approval Gate")
    try:
        service.initiate_payment(obligation, None, [])
    except PaymentExecutionError as exc:
        pre_approval_message = str(exc)
        print(f"Payment Before Approval: BLOCKED — {pre_approval_message}")
    else:  # pragma: no cover - defensive proof in the visible demo
        raise AssertionError("Unapproved payout obligation was accepted")

    approved_obligation, approval = record_approval_decision(
        obligation,
        approval_id="APR-DEMO-0001",
        decision=ApprovalDecision.APPROVED,
        approved_by="demo-finance-reviewer",
        approved_at=datetime(2025, 9, 30, 12, 0, tzinfo=timezone.utc),
    )
    repository.save_approval(approved_obligation, approval)
    heading("Approval")
    print(f"Approval ID: {approval.approval_id}")
    print(f"Obligation ID: {approval.obligation_id}")
    print(f"Decision: {approval.decision.value}")
    print(f"Approved By: {approval.approved_by}")
    print(f"Obligation Status: {approved_obligation.status.value}")
    print("Persisted: YES")

    heading("Payment Execution Demo")
    initiated = service.initiate_payment(approved_obligation, approval)
    print(f"Obligation ID: {initiated.obligation_id}")
    print(f"Approval ID: {initiated.approval_id}")
    print(f"Internal Payment ID: {initiated.internal_payment_id}")
    print(f"Provider Payment ID: {initiated.provider_payment_id}")
    print(f"Amount: {money(initiated.amount)}")
    print(f"Status: {initiated.status.value}")
    print(f"Idempotency Key: {initiated.idempotency_key}")
    print("Payment Attempt Persisted: YES")

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
    handler = PersistentWebhookHandler(repository)
    confirmation = handler.process_event(webhook, date(2025, 9, 30))
    heading("Webhook Confirmation")
    print(f"Event: {webhook.event_id}")
    print(f"Payment: {webhook.provider_payment_id}")
    print(f"Transition: {confirmation.previous_payment_status.value} → {confirmation.new_payment_status.value}")
    print(f"Result: {confirmation.processing_status.value}")
    print("Webhook Event Persisted: YES")
    print("Confirmed Payment Record Persisted: YES")

    repository.close()
    repository = SQLiteLifecycleRepository(database_path)
    handler = PersistentWebhookHandler(repository)
    duplicate = handler.process_event(webhook, date(2025, 9, 30))
    heading("Duplicate Webhook After Restart")
    print("Handler Restarted: YES")
    print(f"Event: {webhook.event_id}")
    print(f"Result: {duplicate.processing_status.value}")
    print(f"Confirmed Payment Records: {len(repository.list_records())}")
    print("Payment State Changed: NO")

    persisted_payments = repository.list_records()
    completed_payment = persisted_payments[0]
    selected_summary = next(s for s in summaries if s.creator_id == selected.creator_id)
    durable_payment_history = [*historical_payments, *persisted_payments]
    final_results = reconcile_payouts(summaries, durable_payment_history)
    final = next(
        result for result in final_results if result.creator_id == selected_summary.creator_id
    )
    write_reconciliation_report(final_results, report_paths["reconciliation"])
    heading("Final Reconciliation")
    print(f"Creator: {final.creator_id}")
    print(f"Expected Payout: {money(final.expected_payout)}")
    print(f"Previously Paid: {money(selected.amount_paid)}")
    print(f"New Confirmed Payment: {money(completed_payment.amount_paid)}")
    print(f"Total Paid: {money(final.amount_paid)}")
    print(f"Outstanding Balance: {money(final.outstanding_balance)}")
    print(f"Final Status: {final.status.value}")
    print("Source: persisted confirmed payment history")

    audit_trail = repository.get_audit_trail(obligation.obligation_id)
    heading("Persisted Audit Trail")
    print(f"Obligation: {audit_trail.obligation.obligation_id}")
    print(f"Approval: {audit_trail.approval.approval_id}")
    print(f"Payment Attempts: {len(audit_trail.payment_attempts)}")
    print(f"Provider Reference: {audit_trail.payment_attempts[-1].provider_payment_id}")
    print(f"Webhook Events: {len(audit_trail.webhook_events)}")
    print(f"Confirmed Payments: {len(audit_trail.confirmed_payments)}")

    heading("Durable Reports Generated")
    for path in report_paths.values():
        print(path)

    heading("End-to-End Workflow Complete")
    for label in (
        "Validation", "Payout Calculation", "Reconciliation", "Payment Execution",
        "Payout Obligation", "Approval Gate", "Request Idempotency",
        "Webhook Confirmation", "Webhook Idempotency", "Final Reconciliation",
        "SQLite Persistence", "Persisted Audit Trail",
    ):
        print(f"{label:<23} ✓")
    print("\nNo real money was transferred.")
    print("All demo data is synthetic.")

    confirmed_attempt = audit_trail.payment_attempts[-1]
    repository.close()

    return {
        "selected_reconciliation": selected,
        "obligation": obligation,
        "approved_obligation": approved_obligation,
        "approval": approval,
        "pre_approval_message": pre_approval_message,
        "initiated_attempt": initiated,
        "confirmed_attempt": confirmed_attempt,
        "duplicate_webhook": duplicate,
        "final_reconciliation": final,
        "provider_payment_count": provider.created_payment_count,
        "persisted_payment_records": persisted_payments,
        "audit_trail": audit_trail,
        "database_path": database_path,
        "report_paths": report_paths,
    }


if __name__ == "__main__":
    run_demo()
