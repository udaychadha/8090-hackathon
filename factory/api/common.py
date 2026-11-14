"""Shared read-only access and redaction at HTTP/export boundaries."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

from factory.agents.records import Records
from factory.redaction import redact

SENSITIVE_FIELDS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "client_secret",
    "secret_key",
    "apca_api_key_id",
    "apca_api_secret_key",
    "openai_api_key",
    "anthropic_api_key",
}
SENSITIVE_QUERY = SENSITIVE_FIELDS | {
    "key",
    "rlkey",
    "sig",
    "signature",
    "x-amz-signature",
    "x-amz-credential",
    "code",
}
URL = re.compile(r"https?://[^\s<>\"']+")


def _safe_url(match):
    text = match.group(0)
    try:
        parts = urlsplit(text)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in SENSITIVE_QUERY
        ]
        return urlunsplit((parts.scheme, host, parts.path, urlencode(query), parts.fragment))
    except ValueError:
        return "[invalid source URL]"


def sanitize(value):
    """Scrub configured secrets, sensitive fields and URL credentials recursively."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    value = redact(value)

    def visit(item):
        if isinstance(item, dict):
            return {
                key: "[REDACTED]" if key.lower() in SENSITIVE_FIELDS else visit(val)
                for key, val in item.items()
            }
        if isinstance(item, list):
            return [visit(val) for val in item]
        if isinstance(item, str):
            return URL.sub(_safe_url, item)
        return item

    return visit(value)


def root_from(request):
    return Path(request.app.state.root)


def get_records(root):
    return Records(Path(root) / "runs", read_only=True)
