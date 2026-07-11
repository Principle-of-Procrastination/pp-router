# Production Hardening Design

> The session-auth design below is historical and is superseded by `../public-access-refresh/design.md` from 0.3.0 onward.

## Architecture

- `security.py` owns access-key exchange, signed sessions, rate limiting, and
  concurrency admission.
- `config.py` validates runtime settings and contains only non-secret defaults.
- `history.py` exposes a small store interface with CloudBase NoSQL and local
  SQLite implementations. Production selects NoSQL when its server API key exists.
- `api.py` authenticates protected routes, applies limits, keeps one pending stream
  read across heartbeats, and logs internal errors by request ID.
- The React client exchanges an access key for an expiring bearer session kept in
  `sessionStorage`, detects incomplete SSE streams, and supports cancellation.

## Security

- Exact CORS origins; no wildcard credentials.
- Constant-time access-key and signature checks.
- Short-lived HMAC-signed session tokens.
- Login and chat sliding-window limits plus a global upstream concurrency gate.
- CloudBase history collection is `ADMINONLY`; its API key exists only in CloudRun.
- Public health endpoint contains no configuration details.

## Data

`pprouter_history` stores ISO timestamp, a bounded query preview, model, tier,
forced flag, score, and nested token usage. A descending timestamp index supports
recent history and a model index supports aggregation. The backend uses the NoSQL
REST OpenAPI with strict status and shape checks.

## Deployment

The repository root is the CloudRun build context. A root Dockerfile copies only
`pprouter/`; `.dockerignore` excludes the frontend, tests, Git data, and generated
files. Secrets are supplied through CloudRun `EnvParams`. The static frontend keeps
the existing independent CloudBase app and backend URL injection.

## Testing

- Table-driven classifier and follow-up routing tests.
- Session, rate limit, request validation, history, and SSE timeout tests.
- Frontend tests for auth headers, complete streams, truncated streams, and aborts.
- Production build, dependency audit, browser login/error-flow smoke test, and
  deployed endpoint verification.
