# GitHub Copilot Instructions

## Project stack and architecture

- Backend: Python, FastAPI, SQLAlchemy 2.x with async APIs, Pydantic 2, Alembic, and HTTPX.
- Frontend: React, JavaScript, and Vite. Do not use TypeScript.
- Database: PostgreSQL.
- Infrastructure: Docker Compose.
- Architecture: modular monolith with a separate background worker process.
- Keep business logic out of HTTP endpoints. Put workflows in services and persistence access in repositories.
- Integrate external APIs through separate adapters in `backend/app/integrations`; keep provider-specific wire formats out of services and routes.

## Configuration and external services

- Load application settings from environment variables, following the existing settings pattern in `backend/app/core/config.py` and Compose configuration.
- Never put secrets in source code, examples, logs, or committed configuration. Read secret values from the environment.
- Do not invent external API endpoints, request or response fields, authentication schemes, or other provider contracts. Verify contracts against authoritative documentation and preserve the behavior already documented in the project.
- Do not add Redis, Celery, Kafka, Kubernetes, automated tests, or CI/CD unless specifically requested.

## Change guidelines

- Before changing a file, inspect its existing implementation and the related models, field names, API contracts, and directory structure.
- Preserve existing models, field names, API contracts, and project structure unless a requested change requires otherwise.
- Avoid unnecessary dependencies, duplicated code, and premature abstractions. Prefer existing project patterns and helpers.
- Keep changes within the requested scope; do not change business logic when creating or editing instructions.
- After making changes, report the files created or changed, the checks performed, and any remaining limitations.

## Project layout

- `backend/app/api/routes`: FastAPI endpoints.
- `backend/app/core`: configuration and logging.
- `backend/app/db`, `models`, `schemas`: database setup, persistence models, and API schemas.
- `backend/app/repositories`: persistence access.
- `backend/app/services`: business workflows.
- `backend/app/integrations`: external API adapters and normalized provider interfaces.
- `backend/app/workers`: separate worker process entry point.
- `backend/alembic`: database migrations.
- `frontend/src`: React application, written in JavaScript/JSX.
