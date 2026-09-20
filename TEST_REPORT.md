# AML Agent Test Report

Date: 2026-09-20

## Result

- Backend: **324 passed, 4 skipped, 1 expected failure**
- Frontend: **29 passed**
- Live API demo queries: **4 opt-in cases**
- Frontend production build: **passed**
- Frontend lint: **passed**
- Deployed AWS browser workflow: **API connected; HI-Small active**
- AWS SAM template: **valid**
- SAML-D validation script: **passed**

## Coverage added

- Pydantic model and request validation
- Deterministic intent extraction and filter parsing
- Planner allow-list validation
- Feature engineering
- Rule engine
- Statistical anomaly scoring
- Isolation Forest output contracts
- Risk scoring and escalation boundaries
- Data-loader and SAML-D contracts
- FastAPI health, stats, query, and response schema
- Full DuckDB-backed pipeline chains
- SAML-D rule validation and BM25 retrieval
- Performance SLA assertions
- Four live demo-query traces
- React execution-trace rendering
- Typed frontend API wrapper
- Bounded customer search, risk filtering, pagination, and profile drill-down
- Parameterized transaction filters, stable evidence IDs, and source-label disclosure
- Self-transfer handling without false self-counterparty relationships
- Concurrent customer/queue reads without request-time DuckDB schema writes
- Dedicated grouped/count threshold aggregation
- Reconciled detector-level risk contributions
- Structured transaction evidence
- Investigation-history browser persistence
- Active model-card API and routed model intelligence page
- Atomic DuckDB investigation and alert-queue persistence
- Queue assignment, analyst notes, disposition, and SLA contracts
- Append-only audit events with policy/model/dataset version metadata
- Public audit and policy write prohibition
- Read-only effective policy and governed dataset APIs
- CSV/XLSX schema inspection, canonical normalization, and invalid-row rejection
- Fingerprint duplicate protection and per-dataset DuckDB schema isolation
- Active dataset switching with immutable investigation dataset attribution
- Dataset upload, activation, and deletion audit records
- Investigation PDF/Markdown/JSON and entity CSV/XLSX/JSON exports
- Reviewer-only SAR drafts, execution traces, model cards, audit, and EDA exports
- Routed review queue, audit, policy, dataset, and server history pages
- Query-selective AML feature families with model-contract completion
- PSI feature-drift monitoring against the exact training baseline
- Ten-chart query-scoped EDA suite and missing-data assessment
- Restricted configurable CORS and dataset-aware readiness probe
- Checksum-verified, atomic production database bootstrap
- Cold-start retries for idempotent reads only
- Lazy-loaded Cartesian Plotly bundle reduced from 4,655 KB to 1,371 KB
- Frontend CI, backend unit CI, Render blueprint, and staged Sites release
- Boto3-backed S3, DynamoDB, and SNS service wrappers with local fallbacks
- Lambda HTTP/S3 event routing, URL-decoded keys, duplicate-event handling, and structured failures
- API Gateway CORS, CloudWatch structured logging, IAM-scoped SAM resources, and frontend deployment

## Performance

| Operation | Observed | Target | Result |
|---|---:|---:|---|
| Filtered data load, 1,000 rows | 0.03 s | < 1.0 s | Pass |
| Feature engineering, 1,000 rows | 0.09 s | < 2.0 s | Pass |
| Rule engine, 1,000 rows | 0.01 s | < 0.5 s | Pass |
| Statistical scoring, 1,000 rows | 0.05 s | < 0.5 s | Pass |
| ML engine, 1,000 rows including initial model load | 1.39 s | < 5.0 s | Pass |
| Full pipeline, 500 rows | 0.16 s | < 10.0 s | Pass |
| Risk scorer and escalation, 1,000 rows | 0.10 s | < 0.2 s | Pass |
| Risk-ranked customer page, 515,080 accounts | 1.96 s | < 3.0 s | Pass |

## SAML-D validation

| Typology | Recall |
|---|---:|
| Structuring | 0.00% |
| Smurfing | 46.89% |
| Cash withdrawal | 70.69% |
| Single large | 100.00% |
| Deposit-send | 16.61% |
| Fan-in | 42.86% |
| Fan-out | 37.13% |

Structuring recall is a known data-retention limitation: the compact SAML-D
table contains positive rows but cannot reconstruct the required three-event
account sequence.

## Expected failure

The plan's example query using "last 30 days" returns no rows because the
   fixed HI-Small dataset ends on 2022-09-18 while the current date is 2026.

## Skipped

Four live-server demo cases are skipped unless `RUN_E2E=1` is explicitly set.
Offline fallback, injected/fake LLM behavior, and in-process API contracts
remain covered.

## Security audit

Passed:

- Query length is constrained to 2,000 characters.
- Unknown planner tools are dropped by the allow-list validator.
- Intent/planner LLM calls require JSON responses.
- User filter values are supplied as DuckDB parameters.
- `.env`, CSV, and DuckDB files are ignored.
- SAML-D remains in a separate table.
- Explanation numbers are checked against grounded feature values.
- No API key is returned in API response models.

Remaining production controls:

1. Demo session authentication is implemented; enterprise IdP integration,
   production RBAC, and maker-checker approval remain deployment controls.
2. The public AWS demonstration uses an S3 website endpoint. A production
   deployment should add an HTTPS CDN and an enterprise identity provider.
3. The 1.37 MB Cartesian-only Plotly bundle is isolated behind a lazy boundary;
   broad EDA loads it on demand while normal investigation routes stay lean.
