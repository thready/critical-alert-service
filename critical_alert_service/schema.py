from __future__ import annotations

from typing import Any, Dict, Tuple
import jsonschema

INCOMING_ALERT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.invalid/schemas/critical-alert-service/incoming-alert.json",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "severity",
        "service",
        "environment",
        "error_code",
        "summary",
        "details",
        "resource",
        "occurred_at",
    ],
    "properties": {
        "severity": {"type": "string", "const": "CRITICAL"},
        "service": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "pattern": "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$",
        },
        "environment": {
            "type": "string",
            "minLength": 1,
            "maxLength": 40,
            "pattern": "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,39}$",
        },
        "error_code": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "pattern": "^[A-Z0-9][A-Z0-9_\-]{0,79}$",
        },
        "summary": {"type": "string", "minLength": 1, "maxLength": 200},
        "details": {"type": "string", "minLength": 0, "maxLength": 4000},
        "resource": {"type": "string", "minLength": 1, "maxLength": 200},
        "occurred_at": {"type": "string", "format": "date-time"},
        "runbook_url": {"type": "string", "format": "uri", "pattern": "^https?://"},
        "tags": {
            "type": "object",
            "additionalProperties": False,
            "maxProperties": 20,
            "patternProperties": {
                "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,39}$": {
                    "type": "string",
                    "maxLength": 200,
                }
            },
        },
    },
}


OUTBOUND_MAILMUX_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.invalid/schemas/critical-alert-service/outbound-mailmux.json",
    "type": "object",
    "additionalProperties": False,
    "required": ["to", "from", "subject", "text"],
    "properties": {
        "to": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": {"type": "string", "minLength": 3, "maxLength": 320},
        },
        "from": {"type": "string", "minLength": 3, "maxLength": 320},
        "subject": {"type": "string", "minLength": 1, "maxLength": 300},
        "text": {"type": "string", "minLength": 1, "maxLength": 20000},
        "headers": {
            "type": "object",
            "additionalProperties": {"type": "string", "maxLength": 2000},
            "maxProperties": 40,
        },
    },
}


def _format_error_message(error: jsonschema.ValidationError) -> str:
    if error.validator == "const" and list(error.path) == ["severity"]:
        return "must be exactly 'CRITICAL'"
    if error.validator == "format" and list(error.path) == ["occurred_at"]:
        return "must be RFC3339 timestamp"
    return error.message


def validate_alert(payload: Any) -> Tuple[bool, Dict[str, str]]:
    validator = jsonschema.Draft202012Validator(INCOMING_ALERT_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    field_errors: Dict[str, str] = {}

    for error in errors:
        if error.validator == "additionalProperties":
            extras = []
            if isinstance(error.params, dict):
                extras = error.params.get("additionalProperties") or []
            elif isinstance(error.params, (list, tuple, set)):
                extras = list(error.params)
            for extra in extras:
                if extra not in field_errors:
                    field_errors[extra] = "unknown field"
            continue

        path = ".".join(str(part) for part in error.path) if error.path else "_"
        if path not in field_errors:
            field_errors[path] = _format_error_message(error)

    return len(field_errors) == 0, field_errors
