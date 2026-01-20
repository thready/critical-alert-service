from __future__ import annotations

from typing import Any, Dict, Tuple
import requests

from .config import Config


def build_subject(config: Config, alert: Dict[str, Any]) -> str:
    return (
        f"{config.mailmux_subject_prefix} {alert['service']} "
        f"({alert['environment']}) {alert['error_code']}: {alert['summary']}"
    )


def build_text(alert: Dict[str, Any], request_id: str) -> str:
    lines = [
        "Severity: CRITICAL",
        f"Service: {alert['service']}",
        f"Environment: {alert['environment']}",
        f"Error Code: {alert['error_code']}",
        f"Summary: {alert['summary']}",
        f"Details: {alert['details']}",
        f"Resource: {alert['resource']}",
        f"Occurred At: {alert['occurred_at']}",
    ]

    runbook = alert.get("runbook_url")
    if runbook:
        lines.append(f"Runbook URL: {runbook}")

    tags = alert.get("tags") or {}
    if tags:
        lines.append("Tags:")
        for key in sorted(tags.keys()):
            lines.append(f"{key}={tags[key]}")

    lines.append(f"Request ID: {request_id}")
    return "\n".join(lines)


def build_payload(config: Config, alert: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    subject = build_subject(config, alert)
    text = build_text(alert, request_id)
    return {
        "to": config.mailmux_to,
        "from": config.mailmux_from,
        "subject": subject,
        "text": text,
    }


def send_mailmux(config: Config, alert: Dict[str, Any], request_id: str) -> Tuple[int, Dict[str, Any]]:
    url = f"{config.mailmux_base_url}{config.mailmux_send_path}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "critical-alert-service/1",
        "X-Request-Id": request_id,
    }

    if config.mailmux_auth_mode == "token":
        headers["Authorization"] = f"Bearer {config.mailmux_bearer_token}"
    elif config.mailmux_auth_mode == "header":
        headers[config.mailmux_auth_header_name or ""] = config.mailmux_auth_header_value or ""

    payload = build_payload(config, alert, request_id)
    timeout_sec = config.mailmux_timeout_ms / 1000.0

    response = requests.post(url, json=payload, headers=headers, timeout=timeout_sec)
    return response.status_code, payload
