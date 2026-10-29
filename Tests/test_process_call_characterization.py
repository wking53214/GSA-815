"""
Characterization ("golden") tests for IcebergProductionHarness.process_call.

PURPOSE
    These tests pin what process_call does TODAY, so a later refactor (for
    example, separating the IVR-specific parts from the generic governance
    pipeline) can be checked against an exact record of current behavior.
    They are a safety net, not a statement that every pinned value is ideal.

HOW IT WORKS
    A fixed set of scenarios (call shape x governor behavior x ledger behavior)
    is run through process_call. What comes back, and what the ledger was
    asked to record, is compared with Tests/golden/process_call_golden.json.

    Inputs are controlled journeys (explicit node names, waits, outcomes), not
    raw Twilio records, on purpose: the phone-number-based route guess in the
    real parser is a known weak spot and should not be locked in as "correct".

NO DATABASE, NO NETWORK
    The ledger is a stand-in that records what it was given. The governor is a
    stand-in that returns canned answers. The real Postgres path is covered by
    test_production_harness_breakers.py.

WHEN A TEST HERE FAILS
    Behavior changed. If the change was intended, regenerate the file with
        UPDATE_GOLDEN=1 pytest Tests/test_process_call_characterization.py
    and review the diff of the golden file line by line before committing it.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from production_harness import IcebergProductionHarness
from twilio_log_ingestion import IcebergJourney

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden", "process_call_golden.json")


# ---- stand-ins ---------------------------------------------------------------

class _FakeLedger:
    """Records what it is asked to write. Can simulate duplicates and failures."""

    def __init__(self, duplicate=False, fail_on_write=False):
        self.duplicate = duplicate
        self.fail_on_write = fail_on_write
        self.written = []

    def sid_exists(self, sid):
        return self.duplicate

    def append_decision(self, record, governance_params=None, episode=None):
        if self.fail_on_write:
            raise RuntimeError("simulated ledger outage")
        self.written.append(record)


class _FakeGovernor:
    """Stands in for ClaudeGovernanceDecider.safety_check."""

    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []

    def safety_check(self, action, details):
        self.calls.append({"action": action, "details": details})
        if self.behavior == "raises":
            raise RuntimeError("simulated governor crash")
        if self.behavior == "approve":
            return {"safe": True, "governed": True, "parse_failed": False,
                    "reasoning": "stub approve", "risk_level": "low",
                    "confidence": 0.9, "model_identity": None, "cost": None}
        if self.behavior == "refuse":
            return {"safe": False, "governed": True, "parse_failed": False,
                    "reasoning": "stub refuse", "risk_level": "high",
                    "confidence": 0.9, "model_identity": None, "cost": None}
        if self.behavior == "failed_closed":
            return {"safe": False, "governed": False, "parse_failed": True,
                    "reasoning": "stub unintelligible", "confidence": 0.0,
                    "model_identity": None, "cost": None}
        raise AssertionError(f"unknown governor behavior {self.behavior!r}")


# ---- scenario building blocks --------------------------------------------------

def _harness():
    return IcebergProductionHarness(
        {"postgres_host": None, "claude_api_key": None, "twilio_account_sid": None},
        require_cassette_binding=False,
    )


def _journey(waits, resolved=True, friction_count=0, duration=120.0, with_waits=True):
    """A journey whose waits are given relative to the cassette's long-wait line."""
    nodes = ["root", "intent_menu", "billing_queue", "agent_a", "exit"]
    wait_times = dict(zip(nodes[1:4], waits)) if with_waits else {}
    return IcebergJourney(
        caller_id="twilio_GOLD",
        timestamp=0,
        journey=nodes,
        wait_times=wait_times,
        total_duration=duration,
        resolved=resolved,
        friction_count=friction_count,
        abandonment_reason=None if resolved else "caller_hung_up",
    )


def _journeys(long_wait):
    over, under = long_wait + 10.0, max(long_wait - 10.0, 0.0)
    return {
        "no_friction": _journey([under, under, under]),
        "one_friction_below_trigger": _journey([over, under, under]),
        "two_friction_at_trigger": _journey([over, over, under]),
        "three_friction": _journey([over, over, over], duration=350.0),
        "wait_exactly_on_line": _journey([long_wait, long_wait, long_wait]),
        "high_friction_unresolved": _journey([over, over, over], resolved=False, duration=400.0),
        # no measured waits at all: falls back to the ingest-side friction_count
        "no_measured_waits_fallback_high": _journey([], friction_count=5, with_waits=False),
        "no_measured_waits_fallback_low": _journey([], friction_count=0, with_waits=False),
    }


# (governor behavior or None, ledger kind or None)
GOVERNORS = [None, "approve", "refuse", "failed_closed", "raises"]
LEDGERS = [None, "ok", "duplicate", "write_fails"]

# Full cross-product on the one journey where governance matters most; the
# remaining journeys run against the two combinations that expose their logic.
FULL_CROSS_JOURNEY = "three_friction"
OTHER_COMBOS = [(None, None), ("approve", "ok")]


def _scenarios():
    probe = _harness()
    long_wait = probe._params().float_value("long_wait_threshold")
    names = list(_journeys(long_wait))
    out = []
    for name in names:
        combos = [(g, ledger_kind) for g in GOVERNORS for ledger_kind in LEDGERS] if name == FULL_CROSS_JOURNEY else OTHER_COMBOS
        for gov, led in combos:
            out.append((name, gov, led))
    return out


def _scenario_id(name, gov, led):
    return f"{name}|gov={gov}|ledger={led}"


def _ledger_view(ledger):
    """The parts of what the ledger was asked to record that define behavior."""
    rows = []
    for rec in ledger.written:
        rows.append({
            "action_type": rec.action_type,
            "node": rec.node,
            "cassette_version": rec.cassette_version,
            "authorized_by": rec.authorized_by,
            "input_data": json.loads(json.dumps(rec.input_data, sort_keys=True, default=str)),
            "output": rec.output,
            "reasoning": rec.reasoning,
            "parameter_changed": rec.parameter_changed,
        })
    return rows


def _run(name, gov, led):
    h = _harness()
    long_wait = h._params().float_value("long_wait_threshold")
    journey = _journeys(long_wait)[name]
    h.twilio_parser.parse_call_log = lambda rec: journey
    governor = _FakeGovernor(gov) if gov else None
    h.claude_decider = governor
    ledger = None
    if led:
        ledger = _FakeLedger(duplicate=(led == "duplicate"), fail_on_write=(led == "write_fails"))
    h.ledger = ledger
    result = h.process_call({"sid": "CAGOLD", "status": "completed", "duration": "120",
                             "from": "+1", "to": "+2"})
    return {
        "result": json.loads(json.dumps(result, sort_keys=True, default=str)),
        "governor_calls": governor.calls if governor else None,
        "ledger_rows": _ledger_view(ledger) if ledger else None,
    }


def _load_golden():
    with open(GOLDEN_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden():
    if os.environ.get("UPDATE_GOLDEN") == "1":
        data = {_scenario_id(*s): _run(*s) for s in _scenarios()}
        os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
        with open(GOLDEN_PATH, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
    return _load_golden()


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: _scenario_id(*s))
def test_process_call_matches_golden(scenario, golden):
    sid = _scenario_id(*scenario)
    assert sid in golden, f"no golden entry for {sid}; regenerate with UPDATE_GOLDEN=1"
    assert _run(*scenario) == golden[sid]


def test_golden_has_no_stale_entries(golden):
    expected = {_scenario_id(*s) for s in _scenarios()}
    assert set(golden) == expected, "golden file and scenario list disagree"


def test_scenarios_are_deterministic():
    """Same inputs twice must give identical output, or the golden file is meaningless."""
    s = ("three_friction", "approve", "ok")
    assert _run(*s) == _run(*s)


# ---- a few readable invariants, so the golden file is not the only spec ------------

def test_core_invariants_hold_across_all_scenarios():
    for name, gov, led in _scenarios():
        out = _run(name, gov, led)
        r = out["result"]
        if "error" in r:
            continue
        # governed implies a decision is required; approval requires a granted AND recorded decision
        assert r["governed"] == r["governance_required"]
        if r["governance_approved"]:
            assert r["claude_safe"] is True and r["ledger_write_failed"] is False
        # a governed call is never both approved and blocked
        assert not (r["governance_approved"] and r["governance_blocked"])
        # a governed call with no governor is blocked, never silently let through
        if r["governance_required"] and gov is None:
            assert r["governance_blocked"] is True


def test_duplicate_sid_is_rejected_before_any_work():
    out = _run("three_friction", "approve", "duplicate")
    assert out["result"]["error"] == "duplicate_sid"
    assert out["governor_calls"] == [], "a duplicate must not reach the governor"
    assert out["ledger_rows"] == [], "a duplicate must not be written"
