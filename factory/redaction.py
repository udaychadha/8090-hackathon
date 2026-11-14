"""Remove configured credentials at prompt, artifact and display boundaries."""

from __future__ import annotations

import json
import os
import re


def redact(value):
    """Return a JSON-compatible copy with raw and JSON-escaped secrets removed.

    Read the environment at each boundary so keys configured after startup are
    covered too. Longest-first matching prevents a shorter key hiding only part
    of an overlapping credential. This is not a general PII classifier.
    """
    secrets = {
        secret
        for name, secret in os.environ.items()
        if secret and any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    literals = secrets | {
        json.dumps(secret, ensure_ascii=ascii_only)[1:-1]
        for secret in secrets
        for ascii_only in (True, False)
    }
    pattern = (
        re.compile("|".join(re.escape(item) for item in sorted(literals, key=len, reverse=True)))
        if literals
        else None
    )

    def scrub(item):
        if isinstance(item, str):
            return pattern.sub("[REDACTED]", item) if pattern else item
        if isinstance(item, dict):
            return {scrub(str(key)): scrub(val) for key, val in item.items()}
        if isinstance(item, list):
            return [scrub(val) for val in item]
        return item

    return scrub(json.loads(json.dumps(value, allow_nan=False, default=str)))


def redacted_json(value, **kwargs):
    """Serialize after filtering, including before test or alternate LLM clients."""
    return json.dumps(redact(value), **kwargs)
