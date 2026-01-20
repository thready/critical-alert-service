# critical-alert-service (v1)

A minimal, opinionated HTTP service that accepts **CRITICAL** operational alerts over HTTP and delivers each accepted alert by making **exactly one** outbound HTTP request to **mailmux**.

This repository contains **design docs only**.

## Purpose

- Provide a single HTTP intake endpoint for **CRITICAL** alerts.
- Enforce **strict validation** so operators can trust alert shape and content.
- Apply best-effort, in-memory **deduplication** and **rate limiting** to reduce noise.
- Deliver alerts via **mailmux only**, with **no hidden retries**.

## Non-goals

- Any severity besides **CRITICAL**.
- Persistence (no database, no disk writes).
- Schedulers, background jobs, queues, async workers.
- Multi-channel delivery (no Slack, SMS, PagerDuty, etc.).
- UI, dashboards, governance workflows.

## Guarantees vs. non-guarantees

### This service guarantees

- **Strict schema**: unknown fields are rejected; required fields must be present and well-typed.
- **Deterministic behavior**:
  - One request in → either a clear success response, or a clear failure response.
  - For each accepted alert, the service makes **exactly one** outbound HTTP call to mailmux.
- **No hidden retries**: if mailmux fails or times out, the caller receives an explicit failure.
- **Human-readable errors**: all failures return a JSON body with a stable `error.code` and a readable `error.message`.

### This service does NOT guarantee

- **No at-least-once delivery**: because there are no retries and no durable state.
- **No exactly-once delivery end-to-end**: mailmux could accept the request but fail later; the service cannot confirm downstream final delivery.
- **Dedupe and rate limit are best-effort only**:
  - They are **in-memory** and reset on process restart.
  - They are **per-instance** and do not coordinate across replicas.
  - They can be bypassed under high concurrency or memory pressure (the service prefers staying responsive and loud over perfect suppression).

## How to run (environment variables only)

The service is configured **only** via environment variables (see CONFIG_SPEC.md for the complete list). A typical run looks like:

```bash
export PORT=8080
export CAS_AUTH_MODE=token
export CAS_AUTH_BEARER_TOKENS="token-prod-1,token-prod-2"

export CAS_MAILMUX_BASE_URL="https://mailmux.example.com"
export CAS_MAILMUX_AUTH_MODE=token
export CAS_MAILMUX_BEARER_TOKEN="mailmux-token"
export CAS_MAILMUX_TO="ops@example.com"

export CAS_DEDUPE_WINDOW_SECONDS=120
export CAS_RATE_LIMIT_MAX=30
export CAS_RATE_LIMIT_WINDOW_SECONDS=60

./critical-alert-service
```

## Example curl requests

### Success

```bash
curl -sS -X POST "http://localhost:8080/v1/alerts" \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer token-prod-1' \
  -d ' {
    "severity": "CRITICAL",
    "service": "payments-api",
    "environment": "prod",
    "error_code": "DB_CONN_POOL_EXHAUSTED",
    "summary": "Database connection pool exhausted",
    "details": "pool=primary, active=200, max=200",
    "resource": "payments-api-7c9d6f7c9b-2k4s2",
    "occurred_at": "2026-01-19T22:48:12Z"
  }'
```

### Shared secret auth

```bash
curl -sS -X POST "http://localhost:8080/v1/alerts" \
  -H 'Content-Type: application/json' \
  -H 'X-Alert-Secret: supersecret' \
  -d '{"severity":"CRITICAL","service":"svc","environment":"prod","error_code":"E","summary":"S","details":"D","resource":"r1","occurred_at":"2026-01-19T22:48:12Z"}'
```

## Example responses

All responses are JSON. All responses include a `request_id` (also returned as `X-Request-Id`).

### Success (mailmux accepted)

HTTP `202`:

```json
{
  "ok": true,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP1",
  "result": "DELIVERED",
  "mailmux": {
    "status": 202
  }
}
```

### Authentication failure

HTTP `401`:

```json
{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP1",
  "error": {
    "type": "AUTH",
    "code": "AUTH_INVALID",
    "message": "Authentication failed: missing or invalid credentials."
  }
}
```

### Validation failure (strict schema)

HTTP `400`:

```json
{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP1",
  "error": {
    "type": "VALIDATION",
    "code": "SCHEMA_INVALID",
    "message": "Request body failed validation.",
    "details": {
      "field_errors": {
        "severity": "must be exactly 'CRITICAL'",
        "occurred_at": "must be RFC3339 timestamp"
      }
    }
  }
}
```

### Policy rejection: deduped

HTTP `409`:

```json
{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP1",
  "error": {
    "type": "POLICY",
    "code": "DEDUPED",
    "message": "Alert suppressed by deduplication window.",
    "details": {
      "dedupe_window_seconds": 120,
      "dedupe_key": "3e6b2d..."
    }
  }
}
```

### Policy rejection: rate limited

HTTP `429`:

```json
{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP1",
  "error": {
    "type": "POLICY",
    "code": "RATE_LIMITED",
    "message": "Rate limit exceeded for service+error_code window.",
    "details": {
      "rate_limit_max": 30,
      "rate_limit_window_seconds": 60,
      "key": "payments-api|DB_CONN_POOL_EXHAUSTED"
    }
  }
}
```

### Mailmux delivery failure (no hidden retries)

HTTP `502`:

```json
{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP1",
  "error": {
    "type": "UPSTREAM",
    "code": "MAILMUX_FAILED",
    "message": "Mailmux returned non-success status.",
    "details": {
      "upstream_status": 500
    }
  }
}
```

## Operational notes (VM and Kubernetes)

- **Stateless**: safe to restart; no recovery of in-flight state.
- **Single-process HTTP server**: run behind a standard L4/L7 load balancer.
- **Multiple replicas** are supported, but policy features are **per-instance** (dedupe/rate-limit will not coordinate across replicas).
- **Resource expectations**: small CPU, modest memory; policy maps are bounded and evict old entries.
- **Timeouts**: set an ingress/client timeout that exceeds `CAS_MAILMUX_TIMEOUT_MS` to ensure callers see deterministic upstream failures.
- **Logging**: write logs to stdout/stderr; prefer log aggregation at the platform level.
