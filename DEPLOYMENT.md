# Sentinel AML production handoff

The React release is saved in the existing Sites project but must not be
activated until the API is reachable. The frontend worker intentionally returns
HTTP 503 when `API_BASE_URL` is absent.

## Backend

1. Upload a sanitized copy of `dataset/aml.duckdb` to private object storage.
2. Calculate its SHA-256 and configure `DATA_BUNDLE_URL` and
   `DATA_BUNDLE_SHA256` as secret Render values.
3. Deploy with `render.yaml`. The bootstrap process installs the database only
   when the persistent disk is empty, verifies its checksum and required tables,
   and then starts FastAPI.
4. Confirm `GET /ready` returns HTTP 200.
5. Set `ALLOWED_ORIGINS` to the exact deployed Sites origin.

## Frontend

1. Set the Sites runtime value `API_BASE_URL` to the deployed FastAPI origin.
2. Deploy the already saved Sites version.
3. Verify health, query execution, investigation persistence, review queue
   mutations, audit events, policy, datasets, model card, and drift monitoring.

Never publish raw transaction CSVs or expose the private database bundle URL.
