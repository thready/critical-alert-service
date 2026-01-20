# DESIGN: critical-alert-service (v1)

## High-level architecture

A single stateless HTTP server process:

- Accepts `POST /v1/alerts` requests containing an alert JSON payload.
- Authenticates the request using either a shared secret header and/or a bearer token.
- Validates the request body against a strict schema.
- Applies best-effort, in-memory policy:
  - dedupe (short window)
  - rate limiting (windowed counter)
- If accepted, performs **exactly one** outbound HTTP request to mailmux.
- Returns a deterministic JSON response, with no hidden retries.

There are **no** databases, files, schedulers, queues, or background workers.

## Request flow (step-by-step)

1. **Read request metadata**
   - Record `request_id` from `X-Request-Id` if present; otherwise generate one.
   - Enforce method and path (`POST /v1/alerts`).
   - Enforce `Content-Type: application/json`.
   - Enforce maximum body size (`CAS_MAX_BODY_BYTES`).

2. **Authenticate**
   - Evaluate authentication per `CAS_AUTH_MODE` (see below).
   - If authentication fails, return `401` with `AUTH_INVALID`.

3. **Parse JSON**
   - If invalid JSON, return `400` with `JSON_INVALID`.

4. **Validate schema (strict)**
   - Validate required fields, types, formats, and allowed values.
   - Reject unknown fields.
   - If validation fails, return `400` with `SCHEMA_INVALID`.

5. **Apply policy (best-effort, in-memory)**
   - Compute dedupe key and rate-limit key.
   - If dedupe hit, return `409` with `DEDUPED`.
   - If rate limit hit, return `429` with `RATE_LIMITED`.

6. **Deliver via mailmux (single attempt)**
   - Build a human-readable email subject + body from the validated alert.
   - Perform **one** HTTP request to mailmux with a fixed timeout.

7. **Return response**
   - On mailmux 2xx: return `202` with `DELIVERED`.
   - On mailmux non-2xx: return `502` with `MAILMUX_FAILED`.
   - On mailmux timeout: return `504` with `MAILMUX_TIMEOUT`.

## Authentication semantics

Authentication supports two credential types:

- **Bearer token**: `Authorization: Bearer <token>`
- **Shared secret**: a configurable header (default `X-Alert-Secret: <secret>`)

`CAS_AUTH_MODE` controls what is accepted:

- `token`
  - Accepted: valid bearer token in `Authorization` header.
  - Rejected: missing/invalid bearer token (even if shared secret is present).

- `secret`
  - Accepted: shared secret header matches exactly.
  - Rejected: missing/invalid secret (even if bearer token is present).

- `either`
  - Accepted: **either** a valid bearer token **or** a valid shared secret.
  - Rejected: neither is valid.

- `both`
  - Accepted: valid bearer token **and** valid shared secret.
  - Rejected: either missing/invalid.

Rejection response:

- Status: `401 Unauthorized`
- Headers:
  - `WWW-Authenticate: Bearer realm="critical-alert-service"` (always present)
  - `X-Request-Id: <id>`
- Body: `error.type=AUTH`, `error.code=AUTH_INVALID`

## Validation rules (strict)

### General

- Request body must be a JSON object.
- Unknown fields are rejected (`additionalProperties: false`).
- Strings are trimmed for policy key computation and email rendering; validation still requires non-empty strings.

### Field-by-field

Required fields:

- `severity` (string)
  - Must be exactly: `"CRITICAL"`.
  - Any other value is rejected.

- `service` (string)
  - 1..80 chars; pattern: `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$`

- `environment` (string)
  - 1..40 chars; recommended values like `prod|staging|dev` but not enforced beyond pattern.
  - pattern: `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,39}$`

- `error_code` (string)
  - 1..80 chars; pattern: `^[A-Z0-9][A-Z0-9_\-]{0,79}$`

- `summary` (string)
  - 1..200 chars

- `details` (string)
  - 0..4000 chars

- `resource` (string)
  - 1..200 chars
  - Intended to identify the failing unit (host/pod/container/etc.).

- `occurred_at` (string)
  - RFC3339 timestamp (e.g. `2026-01-19T22:48:12Z`).

Optional fields:

- `runbook_url` (string)
  - Must be an absolute URL with scheme `http` or `https`.

- `tags` (object)
  - Up to 20 keys; keys 1..40 chars; values 0..200 chars.
  - Unknown nested fields are rejected via schema constraints.

## Policy semantics

### Dedupe

Goal: suppress repeated alerts that are likely the same incident.

- **Best-effort**: in-memory, per-process only.
- **Window**: `CAS_DEDUPE_WINDOW_SECONDS`.

**Dedupe key definition**

1. Normalize:
   - `service`, `environment`, `error_code`, `resource`: trim, lower-case.
   - `summary`: trim; collapse internal whitespace.
2. Concatenate with `|` separators:

`k = service|environment|error_code|resource|summary`

3. Dedupe key is `sha256_hex(k)`.

**Time window behavior**

- First occurrence of a dedupe key within the window is accepted.
- Subsequent occurrences within the window are rejected as deduped.
- The dedupe store is bounded; evictions may cause duplicates to pass through.

**Behavior on dedupe hit**

- Status: `409 Conflict`
- Headers:
  - `X-Policy-Result: deduped`
  - `X-Dedupe-Key: <hex>`
  - `X-Dedupe-Window-Seconds: <int>`
  - `Retry-After: <seconds>` (best-effort remaining window)
- Body:
  - `error.type=POLICY`, `error.code=DEDUPED`

### Rate limit

Goal: prevent runaway alert storms.

- **Best-effort**: in-memory, per-process only.
- **Window**: fixed window of `CAS_RATE_LIMIT_WINDOW_SECONDS`.
- **Max**: `CAS_RATE_LIMIT_MAX` accepted alerts per key per window.

**Rate limit key definition**

- `key = service|error_code` (after trim + lower-case)

**Window behavior**

- A key has a window start time; counts increment per accepted alert.
- When count exceeds max, requests are rejected.
- Store is bounded; evictions may reduce enforcement.

**Behavior on rate-limit hit**

- Status: `429 Too Many Requests`
- Headers (best-effort):
  - `X-Policy-Result: rate_limited`
  - `X-RateLimit-Limit: <int>`
  - `X-RateLimit-Remaining: 0`
  - `X-RateLimit-Reset: <unix_seconds>`
  - `Retry-After: <seconds>`
- Body:
  - `error.type=POLICY`, `error.code=RATE_LIMITED`

## Mailmux interaction

### Outbound request

- Exactly **one** outbound HTTP request per accepted alert.
- Method: `POST`
- URL: `CAS_MAILMUX_BASE_URL` + `CAS_MAILMUX_SEND_PATH` (default `/v1/send`)
- Timeout: `CAS_MAILMUX_TIMEOUT_MS` total (no retries).

Required headers:

- `Content-Type: application/json`
- `User-Agent: critical-alert-service/1`
- `X-Request-Id: <request_id>`

Optional auth headers:

- If `CAS_MAILMUX_AUTH_MODE=token`: `Authorization: Bearer <CAS_MAILMUX_BEARER_TOKEN>`
- If `CAS_MAILMUX_AUTH_MODE=header`: `<CAS_MAILMUX_AUTH_HEADER_NAME>: <CAS_MAILMUX_AUTH_HEADER_VALUE>`

### Mapping alert → email content

Subject (deterministic):

`[CRITICAL] <service> (<environment>) <error_code>: <summary>`

Plain-text body:

- Severity: `CRITICAL`
- Service, environment, error_code
- Summary + details
- Resource
- Occurred at
- Runbook URL (if present)
- Tags rendered as `key=value` lines (sorted by key)
- Request ID

### Mailmux response handling

- If mailmux returns any `2xx`, treat as delivered and return `202`.
- If mailmux returns non-2xx, return `502` with `MAILMUX_FAILED` and include `upstream_status`.
- If mailmux times out, return `504` with `MAILMUX_TIMEOUT`.

No retry logic exists anywhere in the service.

## Failure modes (surface to caller)

All failures return JSON with:

- `ok: false`
- `request_id`
- `error: { type, code, message, details? }`

Failure classes:

- `400 JSON_INVALID`: body is not valid JSON.
- `400 SCHEMA_INVALID`: JSON is valid but violates strict schema.
- `401 AUTH_INVALID`: missing/invalid auth.
- `413 PAYLOAD_TOO_LARGE`: body exceeds `CAS_MAX_BODY_BYTES`.
- `415 UNSUPPORTED_MEDIA_TYPE`: missing/incorrect `Content-Type`.
- `409 DEDUPED`: suppressed by dedupe policy.
- `429 RATE_LIMITED`: rejected by rate limit policy.
- `502 MAILMUX_FAILED`: mailmux returned non-2xx.
- `504 MAILMUX_TIMEOUT`: mailmux timed out.
- `500 INTERNAL`: unexpected server error (includes request_id).

## Logging strategy

- Log to stdout/stderr only.
- One line per request, human-readable (logfmt recommended), including:
  - timestamp, request_id, method, path
  - auth_result (ok/fail)
  - validation_result (ok/fail)
  - policy_result (accepted/deduped/rate_limited)
  - mailmux_status (if called)
  - latency_ms
- Do not emit metrics or traces in v1.
