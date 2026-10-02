"""FastAPI adapter for the Creator Payout Ops lifecycle."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from fastapi import FastAPI, HTTPException, status

from ..models import (
    ApprovalRecord,
    PaymentAttempt,
    PaymentRecord,
    PayoutObligation,
    WebhookEvent,
    WebhookProcessingStatus,
)
from ..obligations import ObligationCreationError, ObligationTransitionError
from ..payment_provider import IdempotencyConflictError, MockPaymentProvider
from ..payment_service import (
    PaymentAlreadyCompletedError,
    PaymentAlreadyPendingError,
    PaymentExecutionError,
)
from ..repositories import SQLiteLifecycleRepository
from .application import (
    LifecycleConflict,
    LifecycleProjection,
    PayoutLifecycleApplication,
    ResourceNotFound,
)
from .schemas import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalView,
    AuditSummary,
    ConfirmedPaymentView,
    ObligationLifecycleResponse,
    ObligationResponse,
    PaymentResponse,
    ReconcileRequest,
    ReconciliationView,
    WebhookRequest,
    WebhookResponse,
)

CENT = Decimal("0.01")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def _obligation(item: PayoutObligation) -> ObligationResponse:
    return ObligationResponse(
        obligation_id=item.obligation_id,
        creator_id=item.creator_id,
        payout_cycle_id=item.payout_cycle_id,
        expected_payout=_money(item.expected_payout),
        previously_paid=_money(item.previously_paid_amount),
        outstanding=_money(item.outstanding_amount),
        reconciliation_status=item.reconciliation_status.value,
        obligation_status=item.status.value,
    )


def _payment(item: PaymentAttempt) -> PaymentResponse:
    return PaymentResponse(
        payment_attempt_id=item.internal_payment_id,
        obligation_id=item.obligation_id,
        amount=_money(item.amount),
        currency=item.currency,
        status=item.status.value,
        provider_reference=item.provider_payment_id,
        idempotency_key=item.idempotency_key,
    )


def _approval(item: ApprovalRecord) -> ApprovalView:
    return ApprovalView(
        approval_id=item.approval_id,
        decision=item.decision.value,
        approved_by=item.approved_by,
        approved_at=item.approved_at,
    )


def _confirmed_payment(item: PaymentRecord) -> ConfirmedPaymentView:
    return ConfirmedPaymentView(
        payment_id=item.payment_id,
        payment_date=item.payment_date,
        amount=_money(item.amount_paid),
        status=item.payment_status.value,
        provider_reference=item.provider_reference,
    )


def _lifecycle(view: LifecycleProjection) -> ObligationLifecycleResponse:
    trail = view.audit_trail
    latest_attempt = trail.payment_attempts[-1] if trail.payment_attempts else None
    confirmed = trail.confirmed_payments[-1] if trail.confirmed_payments else None
    return ObligationLifecycleResponse(
        lifecycle_status=view.reconciliation.status.value,
        obligation=_obligation(trail.obligation),
        approval=_approval(trail.approval) if trail.approval else None,
        latest_payment=_payment(latest_attempt) if latest_attempt else None,
        confirmed_payment=_confirmed_payment(confirmed) if confirmed else None,
        final_reconciliation=ReconciliationView(
            expected_payout=_money(view.reconciliation.expected_payout),
            amount_paid=_money(view.reconciliation.amount_paid),
            outstanding=_money(view.reconciliation.outstanding_balance),
            status=view.reconciliation.status.value,
        ),
        audit_trail=AuditSummary(
            approval_records=1 if trail.approval else 0,
            payment_attempts=len(trail.payment_attempts),
            webhook_events=len(trail.webhook_events),
            confirmed_payments=len(trail.confirmed_payments),
        ),
    )


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _payment_error(exc: PaymentExecutionError) -> HTTPException:
    if isinstance(exc, PaymentAlreadyPendingError):
        code = exc.code
    elif isinstance(exc, PaymentAlreadyCompletedError):
        code = exc.code
    elif "not approved" in str(exc).lower() or "approval record" in str(exc).lower():
        code = "PAYMENT_APPROVAL_REQUIRED"
    elif "rejected" in str(exc).lower():
        code = "PAYMENT_OBLIGATION_REJECTED"
    else:
        code = "PAYMENT_NOT_ALLOWED"
    return _error(status.HTTP_409_CONFLICT, code, str(exc))


def create_app(
    database_path: Path | str | None = None,
    demo_data_directory: Path | str | None = None,
    provider: MockPaymentProvider | None = None,
) -> FastAPI:
    """Create an API instance with injectable storage for integration tests."""

    database = Path(database_path or REPOSITORY_ROOT / "data/output/api_lifecycle.sqlite3")
    demo_data = Path(demo_data_directory or REPOSITORY_ROOT / "data/demo")
    application = PayoutLifecycleApplication(
        SQLiteLifecycleRepository(database), demo_data, provider
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        application.close()

    app = FastAPI(
        title="Creator Payout Ops API",
        version="1.1.0",
        description=(
            "A thin HTTP adapter demonstrating reconciliation, payout approval, "
            "idempotent payment execution, durable webhook confirmation, and "
            "final financial reconciliation. The payment provider is simulated."
        ),
        lifespan=lifespan,
    )
    app.state.lifecycle_application = application

    @app.post(
        "/payout-cycles/reconcile",
        response_model=ObligationResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Reconcile creator payout and create an obligation",
        description=(
            "Runs the existing payout and reconciliation domain services against "
            "the bundled synthetic data, then persists an eligible obligation."
        ),
        tags=["Payout lifecycle"],
    )
    async def reconcile(request: ReconcileRequest) -> ObligationResponse:
        try:
            item = application.reconcile_cycle(
                request.payout_cycle_id, request.creator_id
            )
        except ResourceNotFound as exc:
            raise _error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc)) from exc
        except LifecycleConflict as exc:
            raise _error(
                status.HTTP_409_CONFLICT, "OBLIGATION_ALREADY_EXISTS", str(exc)
            ) from exc
        except ObligationCreationError as exc:
            raise _error(
                status.HTTP_409_CONFLICT, "RECONCILIATION_NOT_PAYABLE", str(exc)
            ) from exc
        except sqlite3.IntegrityError as exc:
            raise _error(
                status.HTTP_409_CONFLICT,
                "PERSISTENCE_CONFLICT",
                "The payout obligation conflicts with persisted financial state",
            ) from exc
        return _obligation(item)

    @app.post(
        "/obligations/{obligation_id}/approve",
        response_model=ApprovalResponse,
        summary="Approve an outstanding payout obligation",
        description=(
            "Uses the existing approval transition and stores its audit record. "
            "The approver is a demo input; authentication is out of scope."
        ),
        tags=["Payout lifecycle"],
    )
    async def approve(
        obligation_id: str, request: ApprovalRequest
    ) -> ApprovalResponse:
        try:
            obligation, record = application.approve(
                obligation_id, request.approval_id, request.approved_by
            )
        except ResourceNotFound as exc:
            raise _error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc)) from exc
        except (ObligationTransitionError, ValueError) as exc:
            raise _error(
                status.HTTP_409_CONFLICT, "INVALID_APPROVAL_TRANSITION", str(exc)
            ) from exc
        except sqlite3.IntegrityError as exc:
            raise _error(
                status.HTTP_409_CONFLICT,
                "APPROVAL_CONFLICT",
                "The approval conflicts with persisted financial state",
            ) from exc
        return ApprovalResponse(
            approval_id=record.approval_id,
            obligation_id=record.obligation_id,
            decision=record.decision.value,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            obligation_status=obligation.status.value,
        )

    @app.post(
        "/obligations/{obligation_id}/payments",
        response_model=PaymentResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Initiate an approved payout",
        description=(
            "Delegates to the approval-gated, idempotent payment service and "
            "persists the resulting attempt. The provider remains simulated."
        ),
        tags=["Payout lifecycle"],
    )
    async def initiate_payment(obligation_id: str) -> PaymentResponse:
        try:
            attempt = application.initiate_payment(obligation_id)
        except ResourceNotFound as exc:
            raise _error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc)) from exc
        except PaymentExecutionError as exc:
            raise _payment_error(exc) from exc
        except IdempotencyConflictError as exc:
            raise _error(
                status.HTTP_409_CONFLICT, "IDEMPOTENCY_CONFLICT", str(exc)
            ) from exc
        except sqlite3.IntegrityError as exc:
            raise _error(
                status.HTTP_409_CONFLICT,
                "PAYMENT_PERSISTENCE_CONFLICT",
                "The payment conflicts with persisted financial state",
            ) from exc
        return _payment(attempt)

    @app.post(
        "/webhooks/payments",
        response_model=WebhookResponse,
        summary="Deliver a simulated provider webhook",
        description=(
            "Processes a simulated provider event through the durable webhook "
            "workflow. Replaying a processed event is safe."
        ),
        tags=["Payout lifecycle"],
    )
    async def payment_webhook(request: WebhookRequest) -> WebhookResponse:
        event = WebhookEvent(
            request.event_id,
            request.event_type,
            request.provider_payment_id,
            request.failure_type,
            request.failure_reason,
        )
        try:
            result = application.process_webhook(event, request.payment_date)
        except sqlite3.IntegrityError as exc:
            raise _error(
                status.HTTP_409_CONFLICT,
                "WEBHOOK_PERSISTENCE_CONFLICT",
                "The webhook conflicts with persisted financial state",
            ) from exc
        if result.processing_status is WebhookProcessingStatus.REJECTED:
            status_code = (
                status.HTTP_404_NOT_FOUND
                if result.message == "UNKNOWN_PROVIDER_PAYMENT"
                else status.HTTP_409_CONFLICT
            )
            raise _error(status_code, "WEBHOOK_REJECTED", result.message)
        return WebhookResponse(
            event_id=result.event_id,
            provider_payment_id=result.provider_payment_id,
            processing_status=result.processing_status.value,
            previous_payment_status=(
                result.previous_payment_status.value
                if result.previous_payment_status
                else None
            ),
            new_payment_status=(
                result.new_payment_status.value
                if result.new_payment_status
                else None
            ),
            message=result.message,
        )

    @app.get(
        "/obligations/{obligation_id}",
        response_model=ObligationLifecycleResponse,
        summary="Inspect final financial and audit state",
        description=(
            "Returns the obligation, approval, latest payment, confirmed payment, "
            "final reconciliation, and concise persisted audit summary."
        ),
        tags=["Payout lifecycle"],
    )
    async def get_obligation(obligation_id: str) -> ObligationLifecycleResponse:
        try:
            return _lifecycle(application.lifecycle(obligation_id))
        except ResourceNotFound as exc:
            raise _error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc)) from exc

    return app
