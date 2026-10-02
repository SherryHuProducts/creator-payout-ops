# V1.1 Backend Architecture

V1.1 introduces architectural boundaries and lightweight durable persistence
around the working V1 domain. Payout calculation remains unchanged; SQLite
closes the audit loop from obligation through confirmed payment and final
reconciliation.

## Current workflow boundary

```text
HTTP / Swagger -> FastAPI Adapter ─┐
CLI Demo ──────────────────────────┴→ Application Orchestration
  -> Domain Logic
  -> Repository Protocols
  -> sqlite3 Lifecycle Adapter
  -> Final Reconciliation / CSV Report
```

FastAPI provides five business workflow endpoints and maps HTTP requests,
responses, and errors. Domain services retain calculation, obligation,
approval, payment, and webhook rules. Repository protocols define persistence
ports using the existing domain models. `SQLiteLifecycleRepository` implements
the obligation, approval, payment, webhook, and audit-trail boundaries without
an ORM.

SQLite persists payout obligations, approval records, payment attempts,
processed webhook events, and confirmed payment records. The mock payment
provider remains in memory and no real payment service is connected.

## Planned infrastructure

```text
Docker (planned)
  -> GitHub Actions (test workflow implemented)
  -> AWS ECS Fargate (planned)
  -> RDS PostgreSQL (planned)
  -> CloudWatch (planned)
```

SQLAlchemy, Alembic, PostgreSQL, containerization, AWS deployment, and
structured observability remain future milestones. GitHub Actions currently
runs the complete pytest suite; it does not deploy the application.
