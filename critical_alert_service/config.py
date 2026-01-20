from __future__ import annotations

from dataclasses import dataclass
import os
import re
import sys
from typing import List, Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    port: int
    max_body_bytes: int
    request_id_header: str
    auth_mode: str
    auth_bearer_tokens: List[str]
    auth_secret_header_name: str
    auth_shared_secret: Optional[str]
    dedupe_window_seconds: int
    rate_limit_max: int
    rate_limit_window_seconds: int
    policy_store_max_keys: int
    mailmux_base_url: str
    mailmux_send_path: str
    mailmux_timeout_ms: int
    mailmux_auth_mode: str
    mailmux_bearer_token: Optional[str]
    mailmux_auth_header_name: Optional[str]
    mailmux_auth_header_value: Optional[str]
    mailmux_to: List[str]
    mailmux_from: str
    mailmux_subject_prefix: str


def _fail(msg: str) -> None:
    print(f"CONFIG ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return value


def _parse_int(name: str, default: int, minimum: int, maximum: int, required: bool = False) -> int:
    raw = _get_env(name)
    if raw is None:
        if required:
            _fail(f"{name} is required")
        return default
    try:
        value = int(raw)
    except ValueError:
        _fail(f"{name} must be an integer")
    if value < minimum or value > maximum:
        _fail(f"{name} must be between {minimum} and {maximum}")
    return value


def _parse_list(name: str, required: bool = False) -> List[str]:
    raw = _get_env(name)
    if raw is None:
        if required:
            _fail(f"{name} is required")
        return []
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if required and not items:
        _fail(f"{name} must contain at least one value")
    return items


def _validate_header_name(name: str, value: str) -> None:
    if not value or not value.strip():
        _fail(f"{name} must be a non-empty header name")


def _validate_token_list(tokens: List[str], name: str, min_len: int, max_len: int) -> None:
    for token in tokens:
        if len(token) < min_len or len(token) > max_len:
            _fail(f"{name} tokens must be {min_len}..{max_len} chars")


def _validate_secret(name: str, value: str, min_len: int, max_len: int) -> None:
    if len(value) < min_len or len(value) > max_len:
        _fail(f"{name} must be {min_len}..{max_len} chars")


def _validate_url(name: str, value: str) -> None:
    if value.strip() != value:
        _fail(f"{name} must not contain leading/trailing whitespace")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _fail(f"{name} must be an absolute http/https URL")


def _validate_path(name: str, value: str) -> None:
    if not value.startswith("/"):
        _fail(f"{name} must start with '/' ")


def _validate_emails(name: str, emails: List[str]) -> None:
    if not emails:
        _fail(f"{name} must contain at least one email")
    for email in emails:
        if "@" not in email or len(email) < 3 or len(email) > 320:
            _fail(f"{name} must contain valid email addresses")


def load_config() -> Config:
    port = _parse_int("PORT", 8080, 1, 65535)
    max_body_bytes = _parse_int("CAS_MAX_BODY_BYTES", 16384, 1024, 1048576)
    request_id_header = _get_env("CAS_REQUEST_ID_HEADER", "X-Request-Id") or "X-Request-Id"
    _validate_header_name("CAS_REQUEST_ID_HEADER", request_id_header)

    auth_mode = (_get_env("CAS_AUTH_MODE") or "").strip()
    if not auth_mode:
        _fail("CAS_AUTH_MODE is required")
    if auth_mode not in {"token", "secret", "either", "both"}:
        _fail("CAS_AUTH_MODE must be one of token|secret|either|both")

    auth_tokens = _parse_list("CAS_AUTH_BEARER_TOKENS", required=auth_mode in {"token", "either", "both"})
    if auth_tokens:
        _validate_token_list(auth_tokens, "CAS_AUTH_BEARER_TOKENS", 10, 200)

    auth_secret_header_name = _get_env("CAS_AUTH_SECRET_HEADER_NAME", "X-Alert-Secret") or "X-Alert-Secret"
    _validate_header_name("CAS_AUTH_SECRET_HEADER_NAME", auth_secret_header_name)

    auth_shared_secret = _get_env("CAS_AUTH_SHARED_SECRET")
    if auth_mode in {"secret", "either", "both"}:
        if auth_shared_secret is None:
            _fail("CAS_AUTH_SHARED_SECRET is required")
        _validate_secret("CAS_AUTH_SHARED_SECRET", auth_shared_secret, 10, 200)

    dedupe_window_seconds = _parse_int("CAS_DEDUPE_WINDOW_SECONDS", 120, 0, 86400)
    rate_limit_max = _parse_int("CAS_RATE_LIMIT_MAX", 30, 0, 100000)
    rate_limit_window_seconds = _parse_int("CAS_RATE_LIMIT_WINDOW_SECONDS", 60, 1, 86400)
    policy_store_max_keys = _parse_int("CAS_POLICY_STORE_MAX_KEYS", 10000, 100, 1000000)

    mailmux_base_url = _get_env("CAS_MAILMUX_BASE_URL")
    if mailmux_base_url is None:
        _fail("CAS_MAILMUX_BASE_URL is required")
    _validate_url("CAS_MAILMUX_BASE_URL", mailmux_base_url)

    mailmux_send_path = _get_env("CAS_MAILMUX_SEND_PATH", "/v1/send") or "/v1/send"
    _validate_path("CAS_MAILMUX_SEND_PATH", mailmux_send_path)

    mailmux_timeout_ms = _parse_int("CAS_MAILMUX_TIMEOUT_MS", 5000, 100, 60000)

    mailmux_auth_mode = (_get_env("CAS_MAILMUX_AUTH_MODE", "none") or "none").strip()
    if mailmux_auth_mode not in {"none", "token", "header"}:
        _fail("CAS_MAILMUX_AUTH_MODE must be one of none|token|header")

    mailmux_bearer_token = _get_env("CAS_MAILMUX_BEARER_TOKEN")
    mailmux_auth_header_name = _get_env("CAS_MAILMUX_AUTH_HEADER_NAME")
    mailmux_auth_header_value = _get_env("CAS_MAILMUX_AUTH_HEADER_VALUE")

    if mailmux_auth_mode == "token":
        if mailmux_bearer_token is None:
            _fail("CAS_MAILMUX_BEARER_TOKEN is required for token auth")
        _validate_secret("CAS_MAILMUX_BEARER_TOKEN", mailmux_bearer_token, 10, 500)
    if mailmux_auth_mode == "header":
        if mailmux_auth_header_name is None or mailmux_auth_header_value is None:
            _fail("CAS_MAILMUX_AUTH_HEADER_NAME and CAS_MAILMUX_AUTH_HEADER_VALUE are required for header auth")
        _validate_header_name("CAS_MAILMUX_AUTH_HEADER_NAME", mailmux_auth_header_name)
        if not mailmux_auth_header_value:
            _fail("CAS_MAILMUX_AUTH_HEADER_VALUE must be non-empty")

    mailmux_to = _parse_list("CAS_MAILMUX_TO", required=True)
    _validate_emails("CAS_MAILMUX_TO", mailmux_to)

    mailmux_from = _get_env("CAS_MAILMUX_FROM", "critical-alert-service@localhost") or "critical-alert-service@localhost"
    if not mailmux_from.strip():
        _fail("CAS_MAILMUX_FROM must be non-empty")

    mailmux_subject_prefix = _get_env("CAS_MAILMUX_SUBJECT_PREFIX", "[CRITICAL]") or "[CRITICAL]"
    if not mailmux_subject_prefix.strip():
        _fail("CAS_MAILMUX_SUBJECT_PREFIX must be non-empty")

    return Config(
        port=port,
        max_body_bytes=max_body_bytes,
        request_id_header=request_id_header,
        auth_mode=auth_mode,
        auth_bearer_tokens=auth_tokens,
        auth_secret_header_name=auth_secret_header_name,
        auth_shared_secret=auth_shared_secret,
        dedupe_window_seconds=dedupe_window_seconds,
        rate_limit_max=rate_limit_max,
        rate_limit_window_seconds=rate_limit_window_seconds,
        policy_store_max_keys=policy_store_max_keys,
        mailmux_base_url=mailmux_base_url,
        mailmux_send_path=mailmux_send_path,
        mailmux_timeout_ms=mailmux_timeout_ms,
        mailmux_auth_mode=mailmux_auth_mode,
        mailmux_bearer_token=mailmux_bearer_token,
        mailmux_auth_header_name=mailmux_auth_header_name,
        mailmux_auth_header_value=mailmux_auth_header_value,
        mailmux_to=mailmux_to,
        mailmux_from=mailmux_from,
        mailmux_subject_prefix=mailmux_subject_prefix,
    )
