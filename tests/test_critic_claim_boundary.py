"""A model narrative cannot supply the interface's result claims."""

import json

import pytest

from factory.agents import critic
from factory.agents.test_worker import spec
from factory.llm import Completion


@pytest.mark.parametrize(
    "narrative",
    [
        "VERIFIED with Sharpe 3.2.",
        "The strategy passed.",
        "Returns are positive.",
        "It trades on twelve days.",
    ],
)
def test_result_claims_are_not_retained_as_critic_output(monkeypatch, narrative):
    captured = []

    def complete(role, system, user, **kwargs):
        captured.append(json.loads(user))
        return Completion(narrative, "test", 3, 4, 1.0, 0.01)

    monkeypatch.setattr(critic, "complete", complete)
    result = critic.critique(spec(), "A", {"status": "VERIFIED", "verified_sharpe": 3.2})
    assert narrative not in result.text
    assert "omitted" in result.text
    assert result.cost_usd == 0.01 and result.output_tokens == 4
    assert "telemetry" not in captured[0]
    assert "claimed_metrics" not in captured[0]["spec"]


def test_qualitative_topics_render_only_fixed_questions(monkeypatch):
    text = '{"review_topics":["execution_convention"]}'
    monkeypatch.setattr(
        critic, "complete", lambda *a, **kw: Completion(text, "test", 1, 2, 0.1, 0.001)
    )
    result = critic.critique(spec(), "A", {})
    assert critic.TOPICS["execution_convention"] in result.text
    assert "fixed wording" in result.text
    assert result.cost_usd == 0.001
