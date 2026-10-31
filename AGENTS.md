# Project Instructions

## Project Overview

This is a full-stack web application.

- Backend: Python, FastAPI
- Frontend: React, JavaScript, Vite
- Database: PostgreSQL
- Infrastructure: Docker and Docker Compose

## General Rules

- Always inspect the existing project structure before making changes.
- Follow the existing architecture and coding conventions.
- Do not rewrite existing modules unless explicitly requested.
- Do not introduce unnecessary dependencies.
- Do not duplicate existing functionality.
- Keep changes focused on the requested task.
- Explain important architectural decisions.
- Do not make assumptions about existing functionality. Inspect the code first.

## Backend

- Use Python and FastAPI.
- Follow the existing application structure.
- Keep API routes, business logic, database models and schemas separated according to the existing architecture.
- Follow existing database access patterns.
- Handle errors explicitly.
- Validate incoming data.
- Do not introduce breaking API changes without approval.

## Frontend

- Use React and JavaScript.
- Do not use TypeScript.
- Follow the existing component structure and naming conventions.
- Reuse existing components and hooks where possible.
- Avoid unnecessary re-renders.
- Keep API communication consistent with existing services.
- Do not introduce a new state management library without approval.

## Database

- Use PostgreSQL.
- Preserve existing database conventions.
- Review the impact of schema changes before implementing them.
- Never drop tables, delete data or reset the database without explicit approval.
- Create or update migrations when required.

## Docker

- Inspect the existing Dockerfiles and Docker Compose configuration before changing them.
- Do not change service names, ports, volumes or environment variables without a clear reason.
- Never remove persistent database volumes.
- Do not run destructive Docker commands without approval.

## Security

- Never expose secrets, passwords, tokens or API keys.
- Never commit `.env` files or credentials.
- Do not weaken authentication or authorization.
- Do not disable security checks to make tests pass.

## Git

- Do not commit or push changes unless explicitly requested.
- Do not overwrite unrelated user changes.
- Review the final diff after implementation.

## Workflow

For every task:

1. Inspect the relevant code and understand the existing implementation.
2. Explain the proposed approach for non-trivial changes.
3. Implement only the requested functionality.
4. Run relevant tests, linting or validation commands.
5. Report changed files and verification results.
6. Mention any remaining risks or issues.