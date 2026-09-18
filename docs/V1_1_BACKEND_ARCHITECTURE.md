# V1.1 Backend Architecture Preparation

V1.1 introduces architectural boundaries around the working V1 domain. It
does not change payout, reconciliation, payment, idempotency, webhook,
reporting, or end-to-end behavior.

## Planned request flow

```text
Client
  -> FastAPI (planned)
  -> Application Services
  -> Domain Logic
  -> Repository Layer
  -> PostgreSQL (planned)
```

Application services coordinate use cases and delegate all business decisions
to the existing domain modules. Repository protocols define persistence ports
using existing domain models; database adapters are not implemented yet.

## Planned infrastructure

```text
Docker (planned)
  -> GitHub Actions (planned)
  -> AWS ECS Fargate (planned)
  -> RDS PostgreSQL (planned)
  -> CloudWatch (planned)
```

FastAPI, SQLAlchemy, Alembic, PostgreSQL, containerization, CI/CD, AWS
deployment, and structured observability remain future milestones.
