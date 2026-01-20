# API_SPEC: critical-alert-service (v1)

## Endpoint

- Method: `POST`
- Path: `/v1/alerts`

### Required headers

- `Content-Type: application/json`
- Authentication (see below):
  - `Authorization: Bearer <token>` and/or
  - `X-Alert-Secret: <secret>` (header name configurable)

### Optional headers

- `X-Request-Id: <client-generated-id>`
  - If provided, echoed back in response header and body.

## Request body schema (strict)

Request body must match the “Incoming alert payload schema” in CONFIG_SPEC.md.

Important invariants:

- `severity` must be exactly `"CRITICAL"`.
- Unknown fields are rejected.

## Response contract

### Common response headers

- `Content-Type: application/json`
- `X-Request-Id: <id>`

### Common response body shapes

Success:

```json
{
  "ok": true,
  "request_id": "<id>",
  "result": "DELIVERED",
  "mailmux": { "status": 202 }
}
```

Failure:

```json
{
  "ok": false,
  "request_id": "<id>",
  "error": {
    "type": "AUTH|VALIDATION|POLICY|UPSTREAM|INTERNAL",
    "code": "<STABLE_CODE>",
    "message": "<HUMAN_READABLE>",
    "details": { }
  }
}
```

### Success response

- Status: `202 Accepted`
- When: request authenticated, validated, not blocked by policy, and mailmux returned 2xx.

### Validation failures

- `400 Bad Request`
  - `JSON_INVALID`: invalid JSON
  - `SCHEMA_INVALID`: schema mismatch, including unknown fields
- `413 Payload Too Large`
  - `PAYLOAD_TOO_LARGE`
- `415 Unsupported Media Type`
  - `UNSUPPORTED_MEDIA_TYPE`

### Authentication failures

- `401 Unauthorized`
  - `AUTH_INVALID`
  - Includes `WWW-Authenticate: Bearer realm="critical-alert-service"`

### Policy rejections

- `409 Conflict`
  - `DEDUPED`
  - Headers include `X-Policy-Result: deduped` and best-effort `Retry-After`

- `429 Too Many Requests`
  - `RATE_LIMITED`
  - Headers include `X-Policy-Result: rate_limited` and best-effort rate limit headers

### Mailmux delivery failure (explicit)

- `502 Bad Gateway`
  - `MAILMUX_FAILED` when mailmux returns non-2xx
- `504 Gateway Timeout`
  - `MAILMUX_TIMEOUT` when the mailmux request times out

No retries are performed.

## Concrete examples (request/response pairs)

Notes:

- Example `request_id` values are illustrative.
- Auth examples assume `CAS_AUTH_MODE=token` and `CAS_AUTH_BEARER_TOKENS` contains `token-prod-1`.

### 1) Delivered (success)

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer token-prod-1
X-Request-Id: req-001

{
  "severity": "CRITICAL",
  "service": "payments-api",
  "environment": "prod",
  "error_code": "DB_CONN_POOL_EXHAUSTED",
  "summary": "Database connection pool exhausted",
  "details": "pool=primary, active=200, max=200",
  "resource": "payments-api-7c9d6f7c9b-2k4s2",
  "occurred_at": "2026-01-19T22:48:12Z",
  "runbook_url": "https://runbooks.example.com/payments/db",
  "tags": {"region": "us-east-1", "cluster": "prod-1"}
}
```

Response:

```http
HTTP/1.1 202 Accepted
Content-Type: application/json
X-Request-Id: req-001

{
  "ok": true,
  "request_id": "req-001",
  "result": "DELIVERED",
  "mailmux": { "status": 202 }
}
```

### 2) Authentication missing

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json

{"severity":"CRITICAL","service":"svc","environment":"prod","error_code":"E","summary":"S","details":"D","resource":"r1","occurred_at":"2026-01-19T22:48:12Z"}
```

Response:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json
WWW-Authenticate: Bearer realm="critical-alert-service"
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP1

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

### 3) Authentication invalid bearer token

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer wrong

{"severity":"CRITICAL","service":"svc","environment":"prod","error_code":"E","summary":"S","details":"D","resource":"r1","occurred_at":"2026-01-19T22:48:12Z"}
```

Response:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json
WWW-Authenticate: Bearer realm="critical-alert-service"
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP2

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP2",
  "error": {
    "type": "AUTH",
    "code": "AUTH_INVALID",
    "message": "Authentication failed: missing or invalid credentials."
  }
}
```

### 4) Invalid JSON

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer token-prod-1

{"severity":"CRITICAL",,
```

Response:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP3

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP3",
  "error": {
    "type": "VALIDATION",
    "code": "JSON_INVALID",
    "message": "Request body is not valid JSON."
  }
}
```

### 5) Schema invalid (unknown field)

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer token-prod-1

{
  "severity": "CRITICAL",
  "service": "svc",
  "environment": "prod",
  "error_code": "E",
  "summary": "S",
  "details": "D",
  "resource": "r1",
  "occurred_at": "2026-01-19T22:48:12Z",
  "unexpected": "nope"
}
```

Response:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP4

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP4",
  "error": {
    "type": "VALIDATION",
    "code": "SCHEMA_INVALID",
    "message": "Request body failed validation.",
    "details": {
      "field_errors": {
        "unexpected": "unknown field"
      }
    }
  }
}
```

### 6) Schema invalid (severity not CRITICAL)

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer token-prod-1

{"severity":"HIGH","service":"svc","environment":"prod","error_code":"E","summary":"S","details":"D","resource":"r1","occurred_at":"2026-01-19T22:48:12Z"}
```

Response:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP5

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP5",
  "error": {
    "type": "VALIDATION",
    "code": "SCHEMA_INVALID",
    "message": "Request body failed validation.",
    "details": {
      "field_errors": {
        "severity": "must be exactly 'CRITICAL'"
      }
    }
  }
}
```

### 7) Policy rejection: deduped

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer token-prod-1

{"severity":"CRITICAL","service":"svc","environment":"prod","error_code":"E","summary":"S","details":"D","resource":"r1","occurred_at":"2026-01-19T22:48:12Z"}
```

Response:

```http
HTTP/1.1 409 Conflict
Content-Type: application/json
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP6
X-Policy-Result: deduped
X-Dedupe-Window-Seconds: 120
X-Dedupe-Key: 3e6b2d...
Retry-After: 118

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP6",
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

### 8) Policy rejection: rate limited

Request:

```http
POST /v1/alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer token-prod-1

{"severity":"CRITICAL","service":"svc","environment":"prod","error_code":"E","summary":"S","details":"D","resource":"r2","occurred_at":"2026-01-19T22:48:12Z"}
```

Response:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP7
X-Policy-Result: rate_limited
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1768862952
Retry-After: 42

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP7",
  "error": {
    "type": "POLICY",
    "code": "RATE_LIMITED",
    "message": "Rate limit exceeded for service+error_code window.",
    "details": {
      "rate_limit_max": 30,
      "rate_limit_window_seconds": 60,
      "key": "svc|E"
    }
  }
}
```

### 9) Mailmux failure (non-2xx)

Response:

```http
HTTP/1.1 502 Bad Gateway
Content-Type: application/json
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP8

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP8",
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

### 10) Mailmux timeout

Response:

```http
HTTP/1.1 504 Gateway Timeout
Content-Type: application/json
X-Request-Id: 01JH8K9N9G5Y4B3VZ9P5W0FZP9

{
  "ok": false,
  "request_id": "01JH8K9N9G5Y4B3VZ9P5W0FZP9",
  "error": {
    "type": "UPSTREAM",
    "code": "MAILMUX_TIMEOUT",
    "message": "Mailmux request timed out; no retry was attempted.",
    "details": {
      "timeout_ms": 5000
    }
  }
}
```
