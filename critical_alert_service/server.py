from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from typing import Any, Dict, Optional, Tuple

import requests
import ulid

from .config import Config
from .mailmux import send_mailmux
from .policy import DedupeStore, RateLimiter, dedupe_key, rate_limit_key
from .schema import validate_alert


class Policy:
    def __init__(self, config: Config) -> None:
        self.dedupe = DedupeStore(config.dedupe_window_seconds, config.policy_store_max_keys)
        self.rate_limit = RateLimiter(
            config.rate_limit_max,
            config.rate_limit_window_seconds,
            config.policy_store_max_keys,
        )


def _json_body(ok: bool, request_id: str, result: Optional[str] = None, error: Optional[Dict[str, Any]] = None,
               mailmux_status: Optional[int] = None) -> Dict[str, Any]:
    if ok:
        return {
            "ok": True,
            "request_id": request_id,
            "result": result,
            "mailmux": {"status": mailmux_status},
        }
    return {
        "ok": False,
        "request_id": request_id,
        "error": error or {},
    }


def _error_body(error_type: str, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "type": error_type,
        "code": code,
        "message": message,
    }
    if details:
        body["details"] = details
    return body


def _now_ms() -> int:
    return int(time.time() * 1000)


def _extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def create_server(config: Config) -> ThreadingHTTPServer:
    policy = Policy(config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "critical-alert-service/1"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, status: int, payload: Dict[str, Any], request_id: str,
                       extra_headers: Optional[Dict[str, str]] = None, include_www_auth: bool = False) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Request-Id", request_id)
            if include_www_auth:
                self.send_header("WWW-Authenticate", 'Bearer realm="critical-alert-service"')
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> Tuple[Optional[bytes], Optional[str]]:
            length_header = self.headers.get("Content-Length")
            if length_header:
                try:
                    length = int(length_header)
                except ValueError:
                    return None, "invalid content-length"
                if length > config.max_body_bytes:
                    return None, "too_large"
                data = self.rfile.read(length)
            else:
                data = self.rfile.read(config.max_body_bytes + 1)
            if len(data) > config.max_body_bytes:
                return None, "too_large"
            return data, None

        def _auth_ok(self) -> bool:
            token = _extract_bearer_token(self.headers.get("Authorization"))
            secret_header_value = self.headers.get(config.auth_secret_header_name)

            token_valid = token in config.auth_bearer_tokens if token else False
            secret_valid = secret_header_value == config.auth_shared_secret if secret_header_value else False

            if config.auth_mode == "token":
                return token_valid
            if config.auth_mode == "secret":
                return secret_valid
            if config.auth_mode == "either":
                return token_valid or secret_valid
            if config.auth_mode == "both":
                return token_valid and secret_valid
            return False

        def do_POST(self) -> None:
            start_ms = _now_ms()
            request_id = self.headers.get(config.request_id_header) or str(ulid.new())
            auth_result = "ok"
            validation_result = "ok"
            policy_result = "accepted"
            mailmux_status: Optional[int] = None

            try:
                if self.path != "/v1/alerts":
                    self.send_response(404)
                    self.end_headers()
                    return

                content_type = self.headers.get("Content-Type", "")
                if not content_type.lower().startswith("application/json"):
                    validation_result = "fail"
                    error = _error_body(
                        "VALIDATION",
                        "UNSUPPORTED_MEDIA_TYPE",
                        "Content-Type must be application/json.",
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(415, payload, request_id)
                    return

                if not self._auth_ok():
                    auth_result = "fail"
                    error = _error_body(
                        "AUTH",
                        "AUTH_INVALID",
                        "Authentication failed: missing or invalid credentials.",
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(401, payload, request_id, include_www_auth=True)
                    return

                body, body_err = self._read_body()
                if body_err == "too_large":
                    validation_result = "fail"
                    error = _error_body(
                        "VALIDATION",
                        "PAYLOAD_TOO_LARGE",
                        "Request body exceeded maximum size.",
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(413, payload, request_id)
                    return
                if body_err:
                    validation_result = "fail"
                    error = _error_body(
                        "VALIDATION",
                        "JSON_INVALID",
                        "Request body is not valid JSON.",
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(400, payload, request_id)
                    return

                try:
                    payload_json = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    validation_result = "fail"
                    error = _error_body(
                        "VALIDATION",
                        "JSON_INVALID",
                        "Request body is not valid JSON.",
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(400, payload, request_id)
                    return

                valid, field_errors = validate_alert(payload_json)
                if not valid:
                    validation_result = "fail"
                    error = _error_body(
                        "VALIDATION",
                        "SCHEMA_INVALID",
                        "Request body failed validation.",
                        {"field_errors": field_errors},
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(400, payload, request_id)
                    return

                dkey = dedupe_key(payload_json)
                dedupe_result = policy.dedupe.check(dkey)
                if dedupe_result.deduped:
                    policy_result = "deduped"
                    headers = {
                        "X-Policy-Result": "deduped",
                        "X-Dedupe-Key": dedupe_result.dedupe_key,
                        "X-Dedupe-Window-Seconds": str(config.dedupe_window_seconds),
                    }
                    if dedupe_result.retry_after is not None:
                        headers["Retry-After"] = str(dedupe_result.retry_after)
                    error = _error_body(
                        "POLICY",
                        "DEDUPED",
                        "Alert suppressed by deduplication window.",
                        {
                            "dedupe_window_seconds": config.dedupe_window_seconds,
                            "dedupe_key": dedupe_result.dedupe_key,
                        },
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(409, payload, request_id, extra_headers=headers)
                    return

                rkey = rate_limit_key(payload_json)
                rate_result = policy.rate_limit.check(rkey)
                if rate_result.rate_limited:
                    policy_result = "rate_limited"
                    headers = {
                        "X-Policy-Result": "rate_limited",
                        "X-RateLimit-Limit": str(config.rate_limit_max),
                        "X-RateLimit-Remaining": "0",
                    }
                    if rate_result.reset_at is not None:
                        headers["X-RateLimit-Reset"] = str(rate_result.reset_at)
                    if rate_result.retry_after is not None:
                        headers["Retry-After"] = str(rate_result.retry_after)
                    error = _error_body(
                        "POLICY",
                        "RATE_LIMITED",
                        "Rate limit exceeded for service+error_code window.",
                        {
                            "rate_limit_max": config.rate_limit_max,
                            "rate_limit_window_seconds": config.rate_limit_window_seconds,
                            "key": rkey,
                        },
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(429, payload, request_id, extra_headers=headers)
                    return

                try:
                    status, _ = send_mailmux(config, payload_json, request_id)
                    mailmux_status = status
                except requests.Timeout:
                    error = _error_body(
                        "UPSTREAM",
                        "MAILMUX_TIMEOUT",
                        "Mailmux request timed out; no retry was attempted.",
                        {"timeout_ms": config.mailmux_timeout_ms},
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(504, payload, request_id)
                    return
                except requests.RequestException:
                    error = _error_body(
                        "UPSTREAM",
                        "MAILMUX_FAILED",
                        "Mailmux returned non-success status.",
                        {"upstream_status": 0},
                    )
                    payload = _json_body(False, request_id, error=error)
                    self._send_json(502, payload, request_id)
                    return

                if 200 <= mailmux_status < 300:
                    payload = _json_body(True, request_id, result="DELIVERED", mailmux_status=mailmux_status)
                    self._send_json(202, payload, request_id)
                    return

                error = _error_body(
                    "UPSTREAM",
                    "MAILMUX_FAILED",
                    "Mailmux returned non-success status.",
                    {"upstream_status": mailmux_status},
                )
                payload = _json_body(False, request_id, error=error)
                self._send_json(502, payload, request_id)

            except Exception:
                error = _error_body(
                    "INTERNAL",
                    "INTERNAL",
                    "Unexpected server error.",
                )
                payload = _json_body(False, request_id, error=error)
                self._send_json(500, payload, request_id)
            finally:
                latency_ms = _now_ms() - start_ms
                print(
                    f"timestamp={int(time.time())} request_id={request_id} method={self.command} "
                    f"path={self.path} auth_result={auth_result} validation_result={validation_result} "
                    f"policy_result={policy_result} mailmux_status={mailmux_status} latency_ms={latency_ms}",
                    flush=True,
                )

        def do_GET(self) -> None:
            self.send_response(404)
            self.end_headers()

    return ThreadingHTTPServer(("0.0.0.0", config.port), Handler)
