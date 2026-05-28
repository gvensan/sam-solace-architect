"""LLM input-size probe — composition breakdown.

The probe measures *where* an outgoing request's bytes come from
(system_instruction vs function_response parts vs history) so we can decide on
evidence whether to cap tool-return sizes / offload to artifacts. These tests
pin the bucketing (text vs function_response vs function_call), the
largest-part tracking, the env toggle, and the fail-safe contract that
measurement never raises into the model call.
"""

from __future__ import annotations

import logging

import solace_architect_core._llm_input_probe as probe


class _State(dict):
    """Dict-like stand-in for ADK ``callback_context.state``."""


class _Ctx:
    def __init__(self, **state) -> None:
        self.state = _State(state)


class _Part:
    """A fake ADK Part carrying exactly one populated field."""

    def __init__(self, text=None, function_response=None, function_call=None):
        self.text = text
        self.function_response = function_response
        self.function_call = function_call
        self.inline_data = None


class _FR:
    def __init__(self, response):
        self.response = response


class _Content:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts


class _Config:
    def __init__(self, system_instruction):
        self.system_instruction = system_instruction


class _Request:
    def __init__(self, system_instruction, contents):
        self.config = _Config(system_instruction)
        self.contents = contents


def test_part_size_buckets_by_field():
    assert probe._part_size(_Part(text="hello")) == ("text", 5)

    fr = _FR({"k": "v"})
    kind, size = probe._part_size(_Part(function_response=fr))
    assert kind == "function_response"
    assert size == len(probe._stringify({"k": "v"}))

    kind, _ = probe._part_size(_Part(function_call=object()))
    assert kind == "function_call"


def test_measure_logs_breakdown_and_largest(caplog):
    # A big tool/artifact read should dominate and surface as `largest`.
    big_payload = {"artifact": "x" * 5000}
    req = _Request(
        system_instruction="SYS" * 100,  # 300 chars
        contents=[
            _Content("user", [_Part(text="question")]),
            _Content("tool", [_Part(function_response=_FR(big_payload))]),
            _Content("model", [_Part(text="answer")]),
        ],
    )
    ctx = _Ctx(engagement_id="eng-1", step_id="integration")

    with caplog.at_level(logging.INFO, logger=probe.__name__):
        probe._measure(ctx, req, agent_name="SADomainAgent")

    line = next(r.getMessage() for r in caplog.records if "[SA input-probe]" in r.getMessage())
    assert "agent=SADomainAgent" in line
    assert "engagement=eng-1" in line
    assert "step=integration" in line
    # The function_response slice (what an artifact-offload cap would shrink)
    # must be the largest part and visible in the by_kind breakdown.
    assert "largest=tool/function_response:" in line
    assert "function_response" in line


def test_measure_never_raises_on_malformed_request(caplog):
    # A request missing config/contents must not blow up the model call.
    class _Bad:
        pass

    with caplog.at_level(logging.DEBUG, logger=probe.__name__):
        probe._measure(_Ctx(), _Bad(), agent_name="x")  # must simply return


def test_env_toggle(monkeypatch):
    monkeypatch.setenv("SA_LLM_INPUT_PROBE", "0")
    assert probe._enabled() is False
    monkeypatch.setenv("SA_LLM_INPUT_PROBE", "1")
    assert probe._enabled() is True
    monkeypatch.delenv("SA_LLM_INPUT_PROBE", raising=False)
    assert probe._enabled() is True  # default on
