"""
Fail-closed tests for the three decider methods that had no failure-path coverage.

test_governor_failclosed.py proves the fail-closed property for safety_check
(and, in one case, decide_healing_bounds). Mutation checking showed the other
failure branches could be flipped to fail-open with every test still green:

  * decide_healing_bounds    (transport error, empty response, non-bool should_heal)
  * decide_staffing_adjustment (no client, bad JSON, empty response, transport error)
  * decide_queue_reordering    (no client, bad JSON, empty response, transport error)

Every case asserts the same contract: when the governor response is missing or
unintelligible, the method returns an ungoverned result with NO actionable
output (no heal, no staffing number, no new order). The anthropic client is
stubbed, so nothing here touches the network.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from claude_governance_api import ClaudeGovernanceDecider

# ---- stubs: a fake Messages API response, no network -------------------------

class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, blocks):
        self.content = blocks


def _returns(text):
    def _create(*args, **kwargs):
        return _FakeMessage([_FakeBlock(text)])
    return _create


def _returns_empty():
    def _create(*args, **kwargs):
        return _FakeMessage([])
    return _create


def _raises(exc):
    def _create(*args, **kwargs):
        raise exc
    return _create


def _decider_with(create_fn):
    d = ClaudeGovernanceDecider(api_key="sk-fake-not-used")
    d.client.messages.create = create_fn
    return d


# ---- one call per method, so each scenario runs against all of them ----------

def _call_healing(d):
    return d.decide_healing_bounds("billing_queue", 100.0, 50.0, 1.0)


def _call_staffing(d):
    return d.decide_staffing_adjustment("billing_queue", 5, 100.0, 60.0, 0.1)


def _call_reordering(d):
    return d.decide_queue_reordering(
        ["billing", "support"], {"billing": 0.4, "support": 0.8},
        {"billing": 0.6, "support": 0.4},
    )


# method name -> (call, the keys that must carry NO actionable value on failure)
METHODS = {
    "healing": (_call_healing, ("should_heal", "target_wait", "lo_bound", "hi_bound")),
    "staffing": (_call_staffing, ("recommended_agents",)),
    "reordering": (_call_reordering, ("proposed_order",)),
}


def _assert_blocked(name, decision):
    _, action_keys = METHODS[name]
    assert decision["governed"] is False, "an unintelligible response must not count as governed"
    for key in action_keys:
        assert not decision[key], f"{name}: {key!r} must carry no actionable value on failure"
    assert decision["confidence"] == 0.0
    assert decision["model_identity"] is None, "no model produced this, so no model identity"


# ---- scenarios ---------------------------------------------------------------

@pytest.mark.parametrize("name", METHODS)
def test_no_client_fails_closed(name):
    call, _ = METHODS[name]
    d = ClaudeGovernanceDecider(api_key=None)
    assert d.client is None
    _assert_blocked(name, call(d))


@pytest.mark.parametrize("name", METHODS)
def test_bad_json_fails_closed(name):
    call, _ = METHODS[name]
    decision = call(_decider_with(_returns("this is not json at all")))
    _assert_blocked(name, decision)
    assert decision["parse_failed"] is True


@pytest.mark.parametrize("name", METHODS)
def test_empty_response_fails_closed(name):
    call, _ = METHODS[name]
    decision = call(_decider_with(_returns_empty()))
    _assert_blocked(name, decision)
    assert decision["parse_failed"] is True


@pytest.mark.parametrize("name", METHODS)
def test_transport_error_fails_closed(name):
    call, _ = METHODS[name]
    decision = call(_decider_with(_raises(RuntimeError("boom"))))
    _assert_blocked(name, decision)
    assert decision["parse_failed"] is True
    assert "boom" in decision["reasoning"], "the error should be captured for the audit trail"


def test_healing_nonbool_should_heal_fails_closed():
    # "yes" is truthy in Python; if it slipped through, a garbled answer would approve a heal.
    d = _decider_with(_returns(json.dumps({"should_heal": "yes", "reasoning": "x"})))
    decision = _call_healing(d)
    _assert_blocked("healing", decision)
    assert decision["parse_failed"] is True


def test_valid_responses_still_pass_through():
    """Guard against over-blocking: a well-formed answer must come back as the model gave it."""
    heal = _call_healing(_decider_with(_returns(json.dumps(
        {"should_heal": True, "lo_bound": 30, "hi_bound": 90, "target_wait": 60,
         "reasoning": "ok", "confidence": 0.8}))))
    assert heal["should_heal"] is True and heal["parse_failed"] is False

    staff = _call_staffing(_decider_with(_returns(json.dumps(
        {"recommended_agents": 7, "reasoning": "ok", "expected_wait": 50, "confidence": 0.7}))))
    assert staff["recommended_agents"] == 7 and staff["parse_failed"] is False

    order = _call_reordering(_decider_with(_returns(json.dumps(
        {"proposed_order": ["support", "billing"], "reasoning": "ok",
         "expected_impact": 0.1, "confidence": 0.6}))))
    assert order["proposed_order"] == ["support", "billing"] and order["parse_failed"] is False


# ---- known gap (tracked, not fixed here) --------------------------------------
# Valid JSON that is not an object (null, [1], 42) escapes the try/except in
# decide_staffing_adjustment and decide_queue_reordering: the dict assignments
# after the try raise TypeError instead of returning a blocked result.
# decide_healing_bounds is unaffected (its checks run inside the try).
# strict=True: when the production code is fixed, these start passing and the
# suite fails until the xfail markers are removed, so the gap cannot be forgotten.

@pytest.mark.xfail(strict=True, raises=TypeError,
                   reason="non-object JSON raises instead of failing closed")
@pytest.mark.parametrize("name", ["staffing", "reordering"])
@pytest.mark.parametrize("payload", ["null", "[1]", "42"])
def test_non_object_json_should_fail_closed(name, payload):
    call, _ = METHODS[name]
    decision = call(_decider_with(_returns(payload)))
    _assert_blocked(name, decision)
