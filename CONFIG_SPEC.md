# CONFIG_SPEC: critical-alert-service (v1)

Configuration is **environment variables only**.

All variables are validated at startup; invalid configuration must fail fast with a clear error to stderr.

## Environment variables

### Server

- `PORT`
  - Required: no
  - Default: `8080`
  - Validation: integer `1..65535`

- `CAS_MAX_BODY_BYTES`
  - Required: no
  - Default: `16384` (16 KiB)
  - Validation: integer `1024..1048576`

- `CAS_REQUEST_ID_HEADER`
  - Required: no
  - Default: `X-Request-Id`
  - Validation: non-empty header name

### Authentication

- `CAS_AUTH_MODE`
  - Required: yes
  - Allowed: `token | secret | either | both`

Bearer token auth:

- `CAS_AUTH_BEARER_TOKENS`
  - Required: yes if `CAS_AUTH_MODE` is `token`, `either`, or `both`
  - Default: none
  - Format: comma-separated tokens
  - Validation: each token 10..200 chars; whitespace around tokens is ignored

Shared secret auth:

- `CAS_AUTH_SECRET_HEADER_NAME`
  - Required: no
  - Default: `X-Alert-Secret`
  - Validation: non-empty header name

- `CAS_AUTH_SHARED_SECRET`
  - Required: yes if `CAS_AUTH_MODE` is `secret`, `either`, or `both`
  - Default: none
  - Validation: 10..200 chars

### Policy

- `CAS_DEDUPE_WINDOW_SECONDS`
  - Required: no
  - Default: `120`
  - Validation: integer `0..86400`
  - Notes: `0` disables dedupe.

- `CAS_RATE_LIMIT_MAX`
  - Required: no
  - Default: `30`
  - Validation: integer `0..100000`
  - Notes: `0` disables rate limiting.

- `CAS_RATE_LIMIT_WINDOW_SECONDS`
  - Required: no
  - Default: `60`
  - Validation: integer `1..86400`

- `CAS_POLICY_STORE_MAX_KEYS`
  - Required: no
  - Default: `10000`
  - Validation: integer `100..1000000`
  - Notes: bounding the in-memory maps makes behavior predictable under load.

### Mailmux

- `CAS_MAILMUX_BASE_URL`
  - Required: yes
  - Default: none
  - Validation: absolute URL, scheme `http` or `https`, no trailing whitespace

- `CAS_MAILMUX_SEND_PATH`
  - Required: no
  - Default: `/v1/send`
  - Validation: must start with `/`

- `CAS_MAILMUX_TIMEOUT_MS`
  - Required: no
  - Default: `5000`
  - Validation: integer `100..60000`

- `CAS_MAILMUX_AUTH_MODE`
  - Required: no
  - Default: `none`
  - Allowed: `none | token | header`

- `CAS_MAILMUX_BEARER_TOKEN`
  - Required: yes if `CAS_MAILMUX_AUTH_MODE=token`
  - Default: none
  - Validation: 10..500 chars

- `CAS_MAILMUX_AUTH_HEADER_NAME`
  - Required: yes if `CAS_MAILMUX_AUTH_MODE=header`
  - Default: none
  - Validation: non-empty header name

- `CAS_MAILMUX_AUTH_HEADER_VALUE`
  - Required: yes if `CAS_MAILMUX_AUTH_MODE=header`
  - Default: none
  - Validation: non-empty

Recipients:

- `CAS_MAILMUX_TO`
  - Required: yes
  - Default: none
  - Format: comma-separated email addresses
  - Validation: each address contains `@` and has length `3..320`

- `CAS_MAILMUX_FROM`
  - Required: no
  - Default: `critical-alert-service@localhost`
  - Validation: non-empty

- `CAS_MAILMUX_SUBJECT_PREFIX`
  - Required: no
  - Default: `[CRITICAL]`
  - Validation: non-empty

## JSON Schemas

These schemas define the strict contract for:

1) Incoming alert payload
2) Outbound mailmux request payload

### Incoming alert payload schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.invalid/schemas/critical-alert-service/incoming-alert.json",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "severity",
    "service",
    "environment",
    "error_code",
    "summary",
    "details",
    "resource",
    "occurred_at"
  ],
  "properties": {
    "severity": {
      "type": "string",
      "const": "CRITICAL"
    },
    "service": {
      "type": "string",
      "minLength": 1,
      "maxLength": 80,
      "pattern": "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$"
    },
    "environment": {
      "type": "string",
      "minLength": 1,
      "maxLength": 40,
      "pattern": "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,39}$"
    },
    "error_code": {
      "type": "string",
      "minLength": 1,
      "maxLength": 80,
      "pattern": "^[A-Z0-9][A-Z0-9_\\-]{0,79}$"
    },
    "summary": {
      "type": "string",
      "minLength": 1,
      "maxLength": 200
    },
    "details": {
      "type": "string",
      "minLength": 0,
      "maxLength": 4000
    },
    "resource": {
      "type": "string",
      "minLength": 1,
      "maxLength": 200
    },
    "occurred_at": {
      "type": "string",
      "format": "date-time"
    },
    "runbook_url": {
      "type": "string",
      "format": "uri",
      "pattern": "^https?://"
    },
    "tags": {
      "type": "object",
      "additionalProperties": false,
      "maxProperties": 20,
      "patternProperties": {
        "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,39}$": {
          "type": "string",
          "maxLength": 200
        }
      }
    }
  }
}
```

### Outbound mailmux request payload schema

This service assumes mailmux accepts a JSON request shaped as follows.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.invalid/schemas/critical-alert-service/outbound-mailmux.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["to", "from", "subject", "text"],
  "properties": {
    "to": {
      "type": "array",
      "minItems": 1,
      "maxItems": 50,
      "items": {
        "type": "string",
        "minLength": 3,
        "maxLength": 320
      }
    },
    "from": {
      "type": "string",
      "minLength": 3,
      "maxLength": 320
    },
    "subject": {
      "type": "string",
      "minLength": 1,
      "maxLength": 300
    },
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 20000
    },
    "headers": {
      "type": "object",
      "additionalProperties": {
        "type": "string",
        "maxLength": 2000
      },
      "maxProperties": 40
    }
  }
}
```
