# Git development workflow

This document defines the mandatory collaboration workflow for Sentinel AML.

## Permitted branches

The repository contains exactly three development branches:

| Branch | Owner | Purpose |
|---|---|---|
| `main` | Mayank Gupta | Protected, production-ready integration branch |
| `mayank` | Mayank Gupta | Frontend, UI/UX, presentation agents and assigned APIs |
| `devesh` | Devesh Raj | Backend, database, core AML agents and assigned APIs |

Do not create, rename, delete, rebase, squash, or force-push branches without
explicit approval. Never develop directly on `main`.

## Ownership boundaries

Mayank owns:

- `frontend/**`
- frontend tests and CI
- dashboard, pages, components, charts, and authentication UI
- query clarification, evidence narration, visualization, and report agents
- dashboard, dataset, investigation, chart, and export API route modules
- general project and demo documentation

Devesh owns:

- backend application, database, services, runtime configuration, and tests
- authentication, query, evidence, workflow, and governance API route modules
- dynamic planning, AML detection, risk decision, and knowledge/RAG agents
- rules, statistics, ML, graphs, escalation, and LLM integration
- backend CI, security, API, model, and data documentation

Cross-functional work must be separated into branch-owned commits. A
contributor must not commit another contributor's implementation.

## Balanced agent and API allocation

Each contributor owns four primary agent modules and their supporting tests.
API ownership is split across five route modules per contributor. Shared
registration uses modular discovery so contributors do not need to edit one
central routing file.

## Eight development phases

Development is divided into exactly eight phases:

1. Project structure and governance
2. Frontend and backend foundations
3. Authentication and initial APIs
4. Dashboard and database workflows
5. AI-agent implementation
6. Remaining product workflows
7. Testing, fixes, and optimization
8. Documentation and production readiness

Each phase uses small, professional commits. Mayank and Devesh each receive
two planned commits per phase, for sixteen implementation commits per
contributor.

## Commit checkpoint

Before a task:

1. Verify the current branch.
2. Announce the owner, files, and expected commit.
3. Work only within the announced ownership boundary.

After every individual commit:

1. Stop development.
2. Run `git status --short --branch`.
3. Run `git log --oneline -5`.
4. Report tests and changed files.
5. Wait for the next instruction.

Do not combine multiple planned commits into one execution checkpoint.

## Push policy

No push is automatic.

- Mayank pushes only `mayank`.
- Devesh pushes only `devesh`.
- `main` is pushed only after an explicitly approved merge.

## Merge policy

The only merge authorizations are explicit instructions equivalent to:

- `Merge mayank into main`
- `Merge devesh into main`
- `Merge both branches into main`

Merging does not imply permission to push. Before an approved merge, confirm
clean working trees, review pending commits, and run branch-appropriate
tests.

## Secret and data safety

Never commit:

- `.env` or API keys
- private transaction/customer datasets
- DuckDB databases
- uploaded analyst files
- model caches
- generated reports or temporary exports
