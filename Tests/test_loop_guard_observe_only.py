"""The loop guard records a repeated governor text; it does not deny on it.

governance_loop_guard flags any reasoning text it has already seen among its
last 1000. A healthy governor gives the same short verdict to many different
calls, so denying on a flag refused healthy calls (the second call with the
same wording was blocked, and so was every later one). The harness now records
the repeat (a counter, a trace attribute and a log line) and leaves the
decision alone. The anthropic client is stubbed; nothing here uses the network.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from test_governor_failclosed import (  # noqa: E402
    _decider_with, _harness, _high_friction_journey, _returns,
)

ROUTINE = {
    "safe": True, "risk_level": "low",
    "reasoning": "Queue wait is within normal bounds. No action needed.",
    "recommendations": [], "confidence": 0.9,
}


def _governed_call(h, sid):
    h.twilio_parser.parse_call_log = lambda rec: _high_friction_journey()
    return h.process_call({"sid": sid, "status": "completed", "duration": 350,
                           "from": "+1111", "to": "+billing"})


def test_two_healthy_calls_with_the_same_wording_are_both_approved():
    h = _harness()
    h.claude_decider = _decider_with(_returns(json.dumps(ROUTINE)))
    for sid in ("CALOOP01", "CALOOP02", "CALOOP03"):
        result = _governed_call(h, sid)
        assert result["governance_approved"] is True, sid
        assert result["governance_blocked"] is False, sid
        assert result["claude_safe"] is True, sid


def test_the_repeat_is_recorded_not_enforced():
    h = _harness()
    h.claude_decider = _decider_with(_returns(json.dumps(ROUTINE)))
    assert h.loop_repeats_seen == 0
    _governed_call(h, "CALOOP04")
    assert h.loop_repeats_seen == 0
    _governed_call(h, "CALOOP05")
    assert h.loop_repeats_seen == 1
    _governed_call(h, "CALOOP06")
    assert h.loop_repeats_seen == 2


def test_distinct_wording_records_nothing():
    h = _harness()
    h.claude_decider = _decider_with(_returns(json.dumps(ROUTINE)))
    _governed_call(h, "CALOOP07")
    other = dict(ROUTINE, reasoning="Wait is elevated but recoverable.")
    h.claude_decider = _decider_with(_returns(json.dumps(other)))
    result = _governed_call(h, "CALOOP08")
    assert result["governance_approved"] is True
    assert h.loop_repeats_seen == 0


def test_fixed_fail_closed_text_is_not_counted_as_a_repeat():
    """No client configured: the same non-decision text every time, by design.
    The harness skips the guard for these (no model_identity), so it must not
    count them either."""
    h = _harness()
    for sid in ("CALOOP09", "CALOOP10"):
        result = _governed_call(h, sid)
        assert result["governance_approved"] is False
    assert h.loop_repeats_seen == 0
