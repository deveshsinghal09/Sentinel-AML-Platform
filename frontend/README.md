# Sentinel AML frontend

This directory contains the React and TypeScript analyst workspace for
Sentinel AML. It is owned by Mayank Gupta and developed on the `mayank`
branch.

## Ownership boundary

Mayank owns:

- pages, components, navigation, dashboard, and UI/UX
- frontend authentication and route guards
- charts and reviewer visualizations
- frontend API clients and TypeScript response contracts
- presentation-focused agents and API route modules assigned by the workflow
- frontend tests, build configuration, and deployment assets

Backend services, databases, core AML agents, and backend authentication
belong to Devesh and must be committed on the `devesh` branch.

## Local development

```bash
npm ci
npm run dev
```

The application is available at `http://127.0.0.1:5173`. During development,
Vite proxies `/api` requests to the local FastAPI service.

## Quality checks

Run all frontend checks before completing a phase:

```bash
npm run lint
npm run test
npm run build
```

## Environment

Copy `.env.production.example` only when preparing a hosted build. Do not
commit local `.env` files or credentials.

## Git workflow

Frontend changes are committed only on `mayank`. Commits remain small and
phase-specific. The branch is pushed only after the complete phase passes its
quality checks; it is never merged into `main` without explicit approval.
