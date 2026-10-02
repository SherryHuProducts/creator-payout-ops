"""Lightweight SQLite persistence for the payout lifecycle."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import (
    ApprovalDecision,
    ApprovalRecord,
    ObligationStatus,
    PaymentAttempt,
    PaymentExecutionStatus,
    PaymentFailureType,
    PaymentRecord,
    PaymentStatus,
    PayoutAuditTrail,
    PayoutObligation,
    ReconciliationStatus,
    WebhookEvent,
    WebhookEventType,
    WebhookProcessingResult,
    WebhookProcessingStatus,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS payout_obligations (
    obligation_id TEXT PRIMARY KEY CHECK (length(trim(obligation_id)) > 0),
    creator_id TEXT NOT NULL CHECK (length(trim(creator_id)) > 0),
    payout_cycle_id TEXT NOT NULL CHECK (length(trim(payout_cycle_id)) > 0),
    expected_payout TEXT NOT NULL,
    previously_paid_amount TEXT NOT NULL,
    outstanding_amount TEXT NOT NULL CHECK (CAST(outstanding_amount AS NUMERIC) > 0),
    reconciliation_status TEXT NOT NULL CHECK (
        reconciliation_status IN ('READY_TO_PAY', 'UNDERPAID')
    ),
    status TEXT NOT NULL CHECK (status IN ('OUTSTANDING', 'APPROVED', 'REJECTED')),
    UNIQUE (creator_id, payout_cycle_id)
);

CREATE TABLE IF NOT EXISTS approval_records (
    approval_id TEXT PRIMARY KEY CHECK (length(trim(approval_id)) > 0),
    obligation_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
    approved_at TEXT NOT NULL,
    FOREIGN KEY (obligation_id) REFERENCES payout_obligations(obligation_id)
);

CREATE TABLE IF NOT EXISTS payment_attempts (
    internal_payment_id TEXT PRIMARY KEY CHECK (length(trim(internal_payment_id)) > 0),
    obligation_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    amount TEXT NOT NULL CHECK (CAST(amount AS NUMERIC) > 0),
    currency TEXT NOT NULL CHECK (length(trim(currency)) > 0),
    idempotency_key TEXT NOT NULL CHECK (length(trim(idempotency_key)) > 0),
    status TEXT NOT NULL CHECK (status IN ('CREATED', 'PENDING', 'PAID', 'FAILED')),
    provider_payment_id TEXT UNIQUE,
    failure_type TEXT,
    failure_reason TEXT,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    UNIQUE (idempotency_key, attempt_number),
    FOREIGN KEY (obligation_id) REFERENCES payout_obligations(obligation_id),
    FOREIGN KEY (approval_id) REFERENCES approval_records(approval_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_effective_payment_per_identity
ON payment_attempts(idempotency_key)
WHERE status IN ('PENDING', 'PAID');

CREATE TABLE IF NOT EXISTS processed_webhook_events (
    event_id TEXT PRIMARY KEY CHECK (length(trim(event_id)) > 0),
    event_type TEXT NOT NULL CHECK (
        event_type IN ('PAYMENT_SUCCEEDED', 'PAYMENT_FAILED')
    ),
    provider_payment_id TEXT NOT NULL UNIQUE,
    failure_type TEXT,
    failure_reason TEXT,
    processed_at TEXT NOT NULL,
    FOREIGN KEY (provider_payment_id) REFERENCES payment_attempts(provider_payment_id)
);

CREATE TABLE IF NOT EXISTS payment_records (
    payment_id TEXT PRIMARY KEY,
    source_attempt_id TEXT NOT NULL UNIQUE,
    obligation_id TEXT NOT NULL UNIQUE,
    creator_id TEXT NOT NULL,
    payment_date TEXT NOT NULL,
    amount_paid TEXT NOT NULL CHECK (CAST(amount_paid AS NUMERIC) > 0),
    payment_status TEXT NOT NULL CHECK (payment_status = 'PAID'),
    provider_reference TEXT NOT NULL UNIQUE,
    FOREIGN KEY (source_attempt_id) REFERENCES payment_attempts(internal_payment_id),
    FOREIGN KEY (obligation_id) REFERENCES payout_obligations(obligation_id)
);
"""


def _money(value: Decimal) -> str:
    return format(value, "f")


def _optional_enum(enum_type, value):
    return enum_type(value) if value is not None else None


class SQLiteLifecycleRepository:
    """Persist the minimum records needed for a reproducible payout audit trail."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteLifecycleRepository":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    @staticmethod
    def _obligation(row: sqlite3.Row) -> PayoutObligation:
        return PayoutObligation(
            obligation_id=row["obligation_id"],
            creator_id=row["creator_id"],
            payout_cycle_id=row["payout_cycle_id"],
            expected_payout=Decimal(row["expected_payout"]),
            previously_paid_amount=Decimal(row["previously_paid_amount"]),
            outstanding_amount=Decimal(row["outstanding_amount"]),
            reconciliation_status=ReconciliationStatus(row["reconciliation_status"]),
            status=ObligationStatus(row["status"]),
        )

    @staticmethod
    def _approval(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row["approval_id"],
            obligation_id=row["obligation_id"],
            decision=ApprovalDecision(row["decision"]),
            approved_by=row["approved_by"],
            approved_at=datetime.fromisoformat(row["approved_at"]),
        )

    @staticmethod
    def _attempt(row: sqlite3.Row) -> PaymentAttempt:
        return PaymentAttempt(
            internal_payment_id=row["internal_payment_id"],
            obligation_id=row["obligation_id"],
            approval_id=row["approval_id"],
            creator_id=row["creator_id"],
            amount=Decimal(row["amount"]),
            currency=row["currency"],
            idempotency_key=row["idempotency_key"],
            status=PaymentExecutionStatus(row["status"]),
            provider_payment_id=row["provider_payment_id"],
            failure_type=_optional_enum(PaymentFailureType, row["failure_type"]),
            failure_reason=row["failure_reason"],
            attempt_number=row["attempt_number"],
        )

    @staticmethod
    def _payment_record(row: sqlite3.Row) -> PaymentRecord:
        return PaymentRecord(
            payment_id=row["payment_id"],
            creator_id=row["creator_id"],
            payment_date=date.fromisoformat(row["payment_date"]),
            amount_paid=Decimal(row["amount_paid"]),
            payment_status=PaymentStatus(row["payment_status"]),
            provider_reference=row["provider_reference"],
        )

    @staticmethod
    def _webhook(row: sqlite3.Row) -> WebhookEvent:
        return WebhookEvent(
            event_id=row["event_id"],
            event_type=WebhookEventType(row["event_type"]),
            provider_payment_id=row["provider_payment_id"],
            failure_type=_optional_enum(PaymentFailureType, row["failure_type"]),
            failure_reason=row["failure_reason"],
        )

    def save_obligation(self, obligation: PayoutObligation) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO payout_obligations VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obligation.obligation_id,
                    obligation.creator_id,
                    obligation.payout_cycle_id,
                    _money(obligation.expected_payout),
                    _money(obligation.previously_paid_amount),
                    _money(obligation.outstanding_amount),
                    obligation.reconciliation_status.value,
                    obligation.status.value,
                ),
            )

    def get_obligation(self, obligation_id: str) -> PayoutObligation | None:
        row = self._connection.execute(
            "SELECT * FROM payout_obligations WHERE obligation_id = ?",
            (obligation_id,),
        ).fetchone()
        return self._obligation(row) if row else None

    def save_approval(
        self, obligation: PayoutObligation, approval: ApprovalRecord
    ) -> None:
        expected_status = (
            ObligationStatus.APPROVED
            if approval.decision is ApprovalDecision.APPROVED
            else ObligationStatus.REJECTED
        )
        if approval.obligation_id != obligation.obligation_id:
            raise ValueError("Approval does not reference the supplied obligation")
        if obligation.status is not expected_status:
            raise ValueError("Obligation status does not match approval decision")

        with self._connection:
            updated = self._connection.execute(
                """
                UPDATE payout_obligations
                SET status = ?
                WHERE obligation_id = ? AND status = 'OUTSTANDING'
                """,
                (obligation.status.value, obligation.obligation_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Stored obligation is missing or already decided")
            self._connection.execute(
                """
                INSERT INTO approval_records VALUES (?, ?, ?, ?, ?)
                """,
                (
                    approval.approval_id,
                    approval.obligation_id,
                    approval.decision.value,
                    approval.approved_by,
                    approval.approved_at.isoformat(),
                ),
            )

    def get_approval(self, obligation_id: str) -> ApprovalRecord | None:
        row = self._connection.execute(
            "SELECT * FROM approval_records WHERE obligation_id = ?",
            (obligation_id,),
        ).fetchone()
        return self._approval(row) if row else None

    def list_records(self) -> list[PaymentRecord]:
        rows = self._connection.execute(
            "SELECT * FROM payment_records ORDER BY payment_date, payment_id"
        ).fetchall()
        return [self._payment_record(row) for row in rows]

    def list_attempts(self, creator_id: str) -> list[PaymentAttempt]:
        rows = self._connection.execute(
            """
            SELECT * FROM payment_attempts
            WHERE creator_id = ?
            ORDER BY idempotency_key, attempt_number, internal_payment_id
            """,
            (creator_id,),
        ).fetchall()
        return [self._attempt(row) for row in rows]

    def save_attempt(self, attempt: PaymentAttempt) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO payment_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.internal_payment_id,
                    attempt.obligation_id,
                    attempt.approval_id,
                    attempt.creator_id,
                    _money(attempt.amount),
                    attempt.currency,
                    attempt.idempotency_key,
                    attempt.status.value,
                    attempt.provider_payment_id,
                    attempt.failure_type.value if attempt.failure_type else None,
                    attempt.failure_reason,
                    attempt.attempt_number,
                ),
            )

    def next_internal_payment_sequence(self) -> int:
        row = self._connection.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTR(internal_payment_id, 5) AS INTEGER)), 0) + 1
            AS next_sequence
            FROM payment_attempts
            WHERE internal_payment_id GLOB 'PAY-[0-9]*'
            """
        ).fetchone()
        return int(row["next_sequence"])

    def has_processed(self, event_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM processed_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return row is not None

    def mark_processed(self, event: WebhookEvent) -> None:
        with self._connection:
            self._insert_webhook(event)

    def _insert_webhook(self, event: WebhookEvent) -> None:
        self._connection.execute(
            """
            INSERT INTO processed_webhook_events VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type.value,
                event.provider_payment_id,
                event.failure_type.value if event.failure_type else None,
                event.failure_reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def process_webhook_event(
        self, event: WebhookEvent, payment_date: date
    ) -> WebhookProcessingResult:
        """Apply one provider event and persist its financial effect atomically."""

        from ..webhook_handler import transition_payment_attempt

        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            if self.has_processed(event.event_id):
                connection.commit()
                return WebhookProcessingResult(
                    event.event_id,
                    event.provider_payment_id,
                    WebhookProcessingStatus.DUPLICATE,
                    None,
                    None,
                    "Webhook event ID was already processed; no state change",
                )

            row = connection.execute(
                "SELECT * FROM payment_attempts WHERE provider_payment_id = ?",
                (event.provider_payment_id,),
            ).fetchone()
            if row is None:
                connection.commit()
                return WebhookProcessingResult(
                    event.event_id,
                    event.provider_payment_id,
                    WebhookProcessingStatus.REJECTED,
                    None,
                    None,
                    "UNKNOWN_PROVIDER_PAYMENT",
                )

            attempt = self._attempt(row)
            result, updated = transition_payment_attempt(event, attempt)
            if updated is None:
                connection.commit()
                return result

            connection.execute(
                """
                UPDATE payment_attempts
                SET status = ?, failure_type = ?, failure_reason = ?
                WHERE internal_payment_id = ?
                """,
                (
                    updated.status.value,
                    updated.failure_type.value if updated.failure_type else None,
                    updated.failure_reason,
                    updated.internal_payment_id,
                ),
            )
            self._insert_webhook(event)

            if updated.status is PaymentExecutionStatus.PAID:
                connection.execute(
                    """
                    INSERT INTO payment_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        updated.internal_payment_id,
                        updated.internal_payment_id,
                        updated.obligation_id,
                        updated.creator_id,
                        payment_date.isoformat(),
                        _money(updated.amount),
                        PaymentStatus.PAID.value,
                        updated.provider_payment_id,
                    ),
                )

            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise

    def get_audit_trail(self, obligation_id: str) -> PayoutAuditTrail:
        obligation = self.get_obligation(obligation_id)
        if obligation is None:
            raise KeyError(f"Unknown payout obligation: {obligation_id}")
        approval = self.get_approval(obligation_id)
        attempt_rows = self._connection.execute(
            """
            SELECT * FROM payment_attempts
            WHERE obligation_id = ?
            ORDER BY attempt_number, internal_payment_id
            """,
            (obligation_id,),
        ).fetchall()
        webhook_rows = self._connection.execute(
            """
            SELECT event.*
            FROM processed_webhook_events AS event
            JOIN payment_attempts AS attempt
              ON attempt.provider_payment_id = event.provider_payment_id
            WHERE attempt.obligation_id = ?
            ORDER BY event.processed_at, event.event_id
            """,
            (obligation_id,),
        ).fetchall()
        payment_rows = self._connection.execute(
            """
            SELECT * FROM payment_records
            WHERE obligation_id = ?
            ORDER BY payment_date, payment_id
            """,
            (obligation_id,),
        ).fetchall()
        return PayoutAuditTrail(
            obligation=obligation,
            approval=approval,
            payment_attempts=tuple(self._attempt(row) for row in attempt_rows),
            webhook_events=tuple(self._webhook(row) for row in webhook_rows),
            confirmed_payments=tuple(
                self._payment_record(row) for row in payment_rows
            ),
        )
