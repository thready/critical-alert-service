# v1 Spec Consistency Audit — critical-alert-service

Date: 2026-01-19

## 1) Schema consistency — PASS

**Confirmations**
- Incoming alert JSON schema is defined in [CONFIG_SPEC.md](CONFIG_SPEC.md) under “Incoming alert payload schema”, and [API_SPEC.md](API_SPEC.md) explicitly states the request body must match that schema.
- Unknown field rejection is stated consistently in [README.md](README.md) (“Strict schema: unknown fields are rejected”), [DESIGN.md](DESIGN.md) (“additionalProperties: false”), and [API_SPEC.md](API_SPEC.md) (“Unknown fields are rejected”).
- CRITICAL-only enforcement is explicit in [README.md](README.md), [DESIGN.md](DESIGN.md), and [API_SPEC.md](API_SPEC.md).

## 2) Status code determinism — FAIL

**Issue 2.1 — Dedupe/rate-limit headers inconsistent across docs**
- **Where**:
  - [DESIGN.md](DESIGN.md) — “Policy semantics → Dedupe → Behavior on dedupe hit” and “Policy semantics → Rate limit → Behavior on rate-limit hit”
  - [API_SPEC.md](API_SPEC.md) — “Policy rejections”
- **Conflict summary**:
  - DESIGN mandates specific headers for dedupe (`X-Dedupe-Key`, `X-Dedupe-Window-Seconds`, `Retry-After`) and rate limit (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`), while API_SPEC only guarantees `X-Policy-Result` plus “best-effort” `Retry-After`/rate-limit headers and does **not** mention the dedupe headers at all. This makes the header contract non-deterministic.
- **Correction recommendation**:
  - Either (a) update API_SPEC to explicitly include **all** dedupe and rate-limit headers listed in DESIGN (and note which are best-effort), or (b) relax DESIGN to match the API_SPEC guarantees. Choose one authoritative header contract and mirror it in both files.

## 3) Auth semantics clarity — PASS

**Confirmations**
- `CAS_AUTH_MODE` and credential requirements are unambiguous in [CONFIG_SPEC.md](CONFIG_SPEC.md) and the full mode semantics and precedence are described in [DESIGN.md](DESIGN.md) (“token/secret/either/both”).
- Required headers are clearly specified in [API_SPEC.md](API_SPEC.md), including examples.
- Failure responses do not expose sensitive configuration or policy details beyond generic auth failure messaging in [README.md](README.md) and [API_SPEC.md](API_SPEC.md).

## 4) Policy semantics correctness — FAIL

**Issue 4.1 — Process-restart behavior not explicitly stated outside README**
- **Where**:
  - [README.md](README.md) — “Guarantees vs. non-guarantees” states policy state resets on process restart.
  - [DESIGN.md](DESIGN.md) — “Policy semantics” does **not** explicitly mention reset-on-restart behavior.
  - [API_SPEC.md](API_SPEC.md) — does **not** mention reset-on-restart behavior.
- **Conflict summary**:
  - The restart/reset behavior is a required operational guarantee but is only explicitly documented in README, not in the design/spec sections that define policy semantics.
- **Correction recommendation**:
  - Add an explicit statement in DESIGN (and optionally API_SPEC) that dedupe/rate-limit state is in-memory and **resets on process restart**, mirroring README language.

## 5) Mailmux contract consistency — FAIL

**Issue 5.1 — Subject prefix configurability missing in mapping rules**
- **Where**:
  - [CONFIG_SPEC.md](CONFIG_SPEC.md) — `CAS_MAILMUX_SUBJECT_PREFIX` (default `[CRITICAL]`).
  - [DESIGN.md](DESIGN.md) — “Mailmux interaction → Mapping alert → email content” hardcodes subject format as `[CRITICAL] ...`.
- **Conflict summary**:
  - CONFIG_SPEC defines a configurable subject prefix, but DESIGN’s mapping rules hardcode `[CRITICAL]` without referencing the config variable.
- **Correction recommendation**:
  - Update DESIGN to define subject as `<CAS_MAILMUX_SUBJECT_PREFIX> <service> (<environment>) <error_code>: <summary>` or align CONFIG_SPEC to remove the configurable prefix.

**Issue 5.2 — Outbound payload schema vs mapping rules incomplete**
- **Where**:
  - [CONFIG_SPEC.md](CONFIG_SPEC.md) — “Outbound mailmux request payload schema” requires `to`, `from`, `subject`, `text` (and optional `headers`).
  - [DESIGN.md](DESIGN.md) — “Mailmux interaction → Mapping alert → email content” describes only subject/body composition, not how `to`, `from`, or optional `headers` are set.
- **Conflict summary**:
  - The mapping rules do not fully cover the required fields of the outbound schema, leaving `to`, `from`, and `headers` under-specified.
- **Correction recommendation**:
  - Extend DESIGN’s mapping rules to explicitly state how `to` and `from` are derived from `CAS_MAILMUX_TO` and `CAS_MAILMUX_FROM`, and whether `headers` are populated (or explicitly left empty).

## 6) Human readability / operability — PASS

**Confirmations**
- Logging strategy is minimal and human-readable in [DESIGN.md](DESIGN.md) (“one line per request, logfmt recommended”) and README’s operational notes avoid metrics systems.
- README run instructions list required environment variables for a valid token-based configuration and include a complete example block in [README.md](README.md).
