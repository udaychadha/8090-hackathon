"""Exercise the real provider SDKs with offline HTTP transports and fake keys."""

import json

import httpx
import pytest

from factory import llm
from factory.redaction import redact


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("cache_used", [False, True])
def test_sdk_filters_credentials_from_both_prompts_and_response(monkeypatch, provider, cache_used):
    sentinel = 'fake-credential-"quoted"-é'
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", sentinel)
    monkeypatch.setenv("WORKER_MODEL", f"{provider}:offline-fixture")
    for kind, rate in {
        "INPUT": "2",
        "OUTPUT": "10",
        "CACHE_READ": "0.1",
        "CACHE_WRITE": "2.5",
        "CACHE_WRITE_LONG": "5",
    }.items():
        monkeypatch.setenv(f"WORKER_{kind}_USD_PER_MTOK", rate)
    seen = []

    def handle(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert sentinel not in str(payload)
        assert "[REDACTED]" in str(payload)
        if provider == "openai":
            body = {
                "id": "resp_fixture",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "offline-fixture",
                "output": [
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": sentinel, "annotations": []}],
                    }
                ],
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 0},
                },
            }
        else:
            body = {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "offline-fixture",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "content": [{"type": "text", "text": sentinel}],
                "usage": {"input_tokens": 7, "output_tokens": 3},
            }
        if cache_used:
            if provider == "openai":
                body["usage"]["input_tokens_details"].update(
                    cached_tokens=2,
                    cache_write_tokens=3,
                    cache_write_tokens_details={"ttl_30m_tokens": 1, "ttl_12h_tokens": 2},
                )
            else:
                body["usage"].update(
                    input_tokens=2,
                    cache_read_input_tokens=2,
                    cache_creation_input_tokens=3,
                    cache_creation={"ephemeral_5m_input_tokens": 1, "ephemeral_1h_input_tokens": 2},
                )
        return httpx.Response(200, json=body)

    module = __import__(provider)
    name = "OpenAI" if provider == "openai" else "Anthropic"
    sdk = getattr(module, name)

    def client(**kwargs):
        # An ASCII fake key for the auth header; the configured secret still
        # appears in the payload to test our filtering, not the provider's.
        return sdk(
            api_key="offline-test-key",
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
            **kwargs,
        )

    monkeypatch.setattr(module, name, client)
    result = llm.complete("worker", "System: " + sentinel, json.dumps({"paper": sentinel}))
    assert len(seen) == 1
    assert result.text == "[REDACTED]"
    assert result.input_tokens == 7 and result.output_tokens == 3
    assert result.cost_usd == pytest.approx(0.0000467 if cache_used else 0.000044)
    assert result.cached_input_tokens == (2 if cache_used else 0)
    assert result.cache_write_long_input_tokens == (2 if cache_used else 0)


def test_overlapping_credentials_and_late_configuration(monkeypatch):
    monkeypatch.setenv("ONE_API_KEY", "fake-short-key")
    monkeypatch.setenv("TWO_API_KEY", "fake-short-key-with-long-suffix")
    assert redact("fake-short-key-with-long-suffix") == "[REDACTED]"
    monkeypatch.setenv("DB_PASSWORD", "fake-password")
    assert redact({"fake-password": ("fake-password",)}) == {"[REDACTED]": ["[REDACTED]"]}


def test_cached_cost_uses_disjoint_categories(monkeypatch):
    for kind, rate in {
        "INPUT": "10",
        "OUTPUT": "50",
        "CACHE_READ": "1",
        "CACHE_WRITE": "12.5",
        "CACHE_WRITE_LONG": "25",
    }.items():
        monkeypatch.setenv(f"WORKER_{kind}_USD_PER_MTOK", rate)
    # 1,000 ordinary + 4,000 reads + 5,000 short writes + 2,000 long writes.
    assert llm._cost("worker", 12000, 100, 4000, 5000, 2000) == pytest.approx(0.1315)
    monkeypatch.delenv("WORKER_CACHE_WRITE_LONG_USD_PER_MTOK")
    assert llm._cost("worker", 12000, 100, 4000, 5000, 2000) is None
