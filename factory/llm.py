"""Role-configured LLM access. This is the sole SDK import boundary.

Set ROLE_MODEL=provider:model-id. Optional ROLE_INPUT_USD_PER_MTOK and
ROLE_OUTPUT_USD_PER_MTOK supply explicit token rates. Optional CACHE_READ,
CACHE_WRITE and CACHE_WRITE_LONG rates cover cached input. Missing rates
produce an unknown cost, never a misleading zero. Provider errors are sanitized.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

from factory.redaction import redact


class LLMError(RuntimeError):
    """Safe-to-display configuration or provider failure."""


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    wall_seconds: float
    cost_usd: float | None
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    cache_write_long_input_tokens: int = 0


def model_for(role: str) -> tuple[str, str]:
    value = os.environ.get(f"{role.upper()}_MODEL", "")
    provider, separator, model = value.partition(":")
    if not separator or provider not in {"anthropic", "openai"} or not model.strip():
        raise LLMError(f"Set {role.upper()}_MODEL to anthropic:model-id or openai:model-id")
    return provider, model


def _cost(
    role: str, inputs: int, outputs: int, cached: int = 0, writes: int = 0, long_writes: int = 0
) -> float | None:
    # Input totals include all cache categories, which are charged instead of
    # ordinary input, not as a surcharge. Provider differences normalize below.
    counts = {
        "INPUT": inputs - cached - writes - long_writes,
        "OUTPUT": outputs,
        "CACHE_READ": cached,
        "CACHE_WRITE": writes,
        "CACHE_WRITE_LONG": long_writes,
    }
    if any(count < 0 for count in counts.values()):
        return None
    rates = {}
    try:
        for kind in counts:
            raw = os.environ.get(f"{role.upper()}_{kind}_USD_PER_MTOK")
            if raw:
                rates[kind] = float(raw)
                if not math.isfinite(rates[kind]) or rates[kind] < 0:
                    raise ValueError
    except ValueError:
        raise LLMError("Token price settings must be finite nonnegative numbers") from None
    if any(
        kind not in rates for kind, count in counts.items() if count or kind in {"INPUT", "OUTPUT"}
    ):
        return None
    return sum(count * rates.get(kind, 0) for kind, count in counts.items()) / 1_000_000


def _field(value, name):
    return (value.get(name, 0) if isinstance(value, dict) else getattr(value, name, 0)) or 0


def complete(role: str, system: str, user: str, *, max_tokens: int = 8192) -> Completion:
    provider, model = model_for(role)
    if not os.environ.get(f"{provider.upper()}_API_KEY"):
        raise LLMError(f"Missing {provider.upper()}_API_KEY")
    # Validate configured rates before incurring a model call.
    _cost(role, 0, 0)
    system, user = redact(system), redact(user)
    started = time.perf_counter()
    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            with Anthropic(timeout=120, max_retries=0) as client:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
            text = "".join(block.text for block in response.content if block.type == "text")
            inputs, outputs = response.usage.input_tokens, response.usage.output_tokens
            cached = _field(response.usage, "cache_read_input_tokens")
            total_writes = _field(response.usage, "cache_creation_input_tokens")
            creation = getattr(response.usage, "cache_creation", None)
            long_writes = _field(creation, "ephemeral_1h_input_tokens")
            writes = total_writes - long_writes
            # Anthropic reports uncached input separately from cache input.
            inputs += cached + total_writes
            truncated = response.stop_reason == "max_tokens"
        else:
            from openai import OpenAI

            with OpenAI(timeout=120, max_retries=0) as client:
                response = client.responses.create(
                    model=model,
                    instructions=system,
                    input=user,
                    max_output_tokens=max_tokens,
                )
            text = response.output_text
            inputs, outputs = response.usage.input_tokens, response.usage.output_tokens
            details = response.usage.input_tokens_details
            cached = _field(details, "cached_tokens")
            write_details = getattr(details, "cache_write_tokens_details", None)
            long_writes = _field(write_details, "ttl_12h_tokens")
            writes = _field(details, "cache_write_tokens") - long_writes
            truncated = response.status != "completed"
    except ImportError:
        raise LLMError(f"Install the {provider} SDK in the project environment") from None
    except Exception:
        # SDK exception text can contain request headers, response bodies, or credentials.
        raise LLMError(f"{provider} request failed; inspect provider status securely") from None
    if truncated or not text.strip():
        raise LLMError("Model response was incomplete or empty; extraction was not accepted")
    return Completion(
        redact(text),
        f"{provider}:{model}",
        inputs,
        outputs,
        time.perf_counter() - started,
        _cost(role, inputs, outputs, cached, writes, long_writes),
        cached,
        writes,
        long_writes,
    )
