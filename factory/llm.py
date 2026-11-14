"""Role-configured LLM access. This is the sole SDK import boundary.

Set ROLE_MODEL=provider:model-id. Optional ROLE_INPUT_USD_PER_MTOK and
ROLE_OUTPUT_USD_PER_MTOK supply explicit uncached token rates. Missing rates
produce an unknown cost, never a misleading zero. Provider errors are sanitized.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass


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


def model_for(role: str) -> tuple[str, str]:
    value = os.environ.get(f"{role.upper()}_MODEL", "")
    provider, separator, model = value.partition(":")
    if not separator or provider not in {"anthropic", "openai"} or not model.strip():
        raise LLMError(f"Set {role.upper()}_MODEL to anthropic:model-id or openai:model-id")
    return provider, model


def _cost(role: str, inputs: int, outputs: int, cached: int = 0) -> float | None:
    # Cached pricing varies by provider; do not guess an exact charge.
    if cached:
        return None
    names = [f"{role.upper()}_{kind}_USD_PER_MTOK" for kind in ("INPUT", "OUTPUT")]
    if any(not os.environ.get(name) for name in names):
        return None
    try:
        rates = [float(os.environ[name]) for name in names]
        if any(not math.isfinite(rate) or rate < 0 for rate in rates):
            raise ValueError
    except ValueError:
        raise LLMError("Token price settings must be finite nonnegative numbers") from None
    return (inputs * rates[0] + outputs * rates[1]) / 1_000_000


def complete(role: str, system: str, user: str, *, max_tokens: int = 8192) -> Completion:
    provider, model = model_for(role)
    if not os.environ.get(f"{provider.upper()}_API_KEY"):
        raise LLMError(f"Missing {provider.upper()}_API_KEY")
    # Validate configured rates before incurring a model call.
    _cost(role, 0, 0)
    started = time.perf_counter()
    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            with Anthropic(timeout=120, max_retries=0) as client:
                response = client.messages.create(
                    model=model, max_tokens=max_tokens, system=system,
                    messages=[{"role": "user", "content": user}],
                )
            text = "".join(block.text for block in response.content if block.type == "text")
            inputs, outputs = response.usage.input_tokens, response.usage.output_tokens
            cached = (getattr(response.usage, "cache_read_input_tokens", 0) or 0) + (
                getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            )
            truncated = response.stop_reason == "max_tokens"
        else:
            from openai import OpenAI

            with OpenAI(timeout=120, max_retries=0) as client:
                response = client.responses.create(
                    model=model, instructions=system, input=user, max_output_tokens=max_tokens,
                )
            text = response.output_text
            inputs, outputs = response.usage.input_tokens, response.usage.output_tokens
            cached = getattr(response.usage.input_tokens_details, "cached_tokens", 0) or 0
            truncated = response.status != "completed"
    except ImportError:
        raise LLMError(f"Install the {provider} SDK in the project environment") from None
    except Exception:
        # SDK exception text can contain request headers, response bodies, or credentials.
        raise LLMError(f"{provider} request failed; inspect provider status securely") from None
    if truncated or not text.strip():
        raise LLMError("Model response was incomplete or empty; extraction was not accepted")
    return Completion(
        text, f"{provider}:{model}", inputs, outputs,
        time.perf_counter() - started, _cost(role, inputs, outputs, cached),
    )
