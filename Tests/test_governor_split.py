"""
Tests for the governor split (step 3 of the IVR separation).

BEFORE: ClaudeGovernanceDecider carried its own copy of the generic safety
check next to the three IVR deciders (heal, staffing, reorder).
AFTER:  the generic safety check comes from the kernel's GovernanceDecider;
ClaudeGovernanceDecider is a thin IVR subclass that adds only the three IVR
deciders, and the governed pipeline asks the domain pack which governor to
build instead of naming the IVR one.

TWO KINDS OF TEST LIVE HERE

1. Behavior pins: exactly what each of the four governor methods sends to the
   model (system text, user text, token limit, model name), and how the
   harness builds its governor. These were run against the pre-split code and
   passed there unchanged, then against the split code. The instruction text
   is written out in full on purpose: if anyone changes what the live governor
   is told, one of these fails and the change has to be deliberate.

2. Structure checks for the split itself.

NO NETWORK. The model client is a stand-in that records the request.
"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from claude_governance_api import ClaudeGovernanceDecider  # noqa: E402
from governor_injection_defense import build_governance_call  # noqa: E402
from production_harness import IcebergProductionHarness  # noqa: E402

NO_SERVICES = {"postgres_host": None, "claude_api_key": None, "twilio_account_sid": None}


# ---- a client stand-in that records the request -----------------------------------

class _RecordingClient:
    def __init__(self, reply):
        self.calls = []
        self._reply = reply
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=json.dumps(self._reply))],
            model="claude-opus-4-6", usage=None)


def _decider(reply):
    d = ClaudeGovernanceDecider(api_key="sk-fake-not-used")
    d.client = _RecordingClient(reply)
    return d


# ---- 1. behavior pins ---------------------------------------------------------------

def test_safety_check_sends_exactly_this_request():
    d = _decider({"safe": True, "risk_level": "low", "reasoning": "ok",
                  "recommendations": [], "confidence": 0.9})
    d.safety_check("heal_queue", {"queue": "billing_queue", "wait_time": 350.0,
                                  "friction_count": 3})
    (sent,) = d.client.calls
    system, messages = build_governance_call(
        system_instruction=(
            "You are an AI safety auditor for IVR systems. Evaluate the "
            "governance action described in the untrusted data block."),
        caller_fields={"action": "heal_queue", "details": json.dumps(
            {"queue": "billing_queue", "wait_time": 350.0, "friction_count": 3})},
        task_and_format=(
            'Respond ONLY with valid JSON: {"safe": true/false, '
            '"risk_level": "low"/"medium"/"high", "reasoning": "...", '
            '"recommendations": [], "confidence": 0.0-1.0}'),
    )
    assert sent["system"] == system
    assert sent["messages"] == messages
    assert sent["max_tokens"] == 300
    assert sent["model"] == "claude-opus-4-6"


def test_healing_decision_sends_exactly_this_request():
    d = _decider({"should_heal": False, "reasoning": "r", "lo_bound": None,
                  "hi_bound": None, "target_wait": None, "confidence": 0.5})
    d.decide_healing_bounds("billing_queue", 120.0, 60.0, 0.5)
    (sent,) = d.client.calls
    system, messages = build_governance_call(
        system_instruction=(
            "You are an IVR governance expert. A call queue has experienced "
            "drift, described in the untrusted data block. Decide whether to "
            "self-heal."),
        caller_fields={"queue": "billing_queue", "current_wait_seconds": "120.0",
                       "baseline_wait_seconds": "60.0", "drift_magnitude_percent": "50.0"},
        task_and_format=(
            'Respond ONLY with valid JSON: {"should_heal": true/false, '
            '"reasoning": "...", "lo_bound": ..., "hi_bound": ..., '
            '"target_wait": ..., "confidence": 0.0-1.0}'),
    )
    assert (sent["system"], sent["messages"]) == (system, messages)
    assert sent["max_tokens"] == 200 and sent["model"] == "claude-opus-4-6"


def test_staffing_decision_sends_exactly_this_request():
    d = _decider({"recommended_agents": 5, "reasoning": "r", "expected_wait": 30,
                  "confidence": 0.5})
    d.decide_staffing_adjustment("billing_queue", 4, 120.0, 60.0, 0.1)
    (sent,) = d.client.calls
    system, messages = build_governance_call(
        system_instruction=(
            "You are a contact center workforce manager. A queue needs a "
            "staffing adjustment, described in the untrusted data block. "
            "Apply Erlang C principles."),
        caller_fields={"queue": "billing_queue", "current_agents": 4,
                       "current_wait_seconds": "120.0", "target_wait_seconds": "60.0",
                       "abandonment_rate_percent": "10.0"},
        task_and_format=(
            'Respond ONLY with valid JSON: {"recommended_agents": integer, '
            '"reasoning": "brief explanation", "expected_wait": '
            'estimated_wait_in_seconds, "confidence": 0.0-1.0}'),
    )
    assert (sent["system"], sent["messages"]) == (system, messages)
    assert sent["max_tokens"] == 200 and sent["model"] == "claude-opus-4-6"


def test_reorder_decision_sends_exactly_this_request():
    d = _decider({"proposed_order": ["a", "b"], "reasoning": "r",
                  "expected_impact": 0.2, "confidence": 0.5})
    d.decide_queue_reordering(["a", "b"], {"a": 0.9, "b": 0.5}, {"a": 10, "b": 20})
    (sent,) = d.client.calls
    system, messages = build_governance_call(
        system_instruction=(
            "You are an IVR menu design expert. Current queue ordering and "
            "performance are in the untrusted data block. Recommend an "
            "ordering that maximizes resolution and minimizes abandonment."),
        caller_fields={"current_order": json.dumps(["a", "b"]),
                       "success_rates_by_queue": json.dumps({"a": 0.9, "b": 0.5}),
                       "caller_distribution": json.dumps({"a": 10, "b": 20})},
        task_and_format=(
            'Respond ONLY with valid JSON: {"proposed_order": '
            '["queue1", "queue2", ...], "reasoning": "...", '
            '"expected_impact": 0.0-1.0, "confidence": 0.0-1.0}'),
    )
    assert (sent["system"], sent["messages"]) == (system, messages)
    assert sent["max_tokens"] == 300 and sent["model"] == "claude-opus-4-6"


def test_every_decision_is_logged_in_order():
    d = _decider({"safe": True, "risk_level": "low", "reasoning": "ok",
                  "recommendations": [], "confidence": 0.9})
    d.safety_check("a", {})
    d.safety_check("b", {})
    assert [x["reasoning"] for x in d.get_decision_log()] == ["ok", "ok"]
    assert d.get_decision_log() is d.decisions


def test_harness_builds_the_ivr_governor_only_when_a_key_is_configured():
    assert IcebergProductionHarness(dict(NO_SERVICES),
                                    require_cassette_binding=False).claude_decider is None
    keyed = IcebergProductionHarness({**NO_SERVICES, "claude_api_key": "sk-fake-not-used"},
                                     require_cassette_binding=False)
    assert type(keyed.claude_decider) is ClaudeGovernanceDecider


def test_a_governor_that_cannot_be_built_leaves_the_harness_running_without_one(
        monkeypatch, capsys):
    import anthropic

    def _boom(*a, **k):
        raise RuntimeError("client construction failed")

    monkeypatch.setattr(anthropic, "Anthropic", _boom)
    h = IcebergProductionHarness({**NO_SERVICES, "claude_api_key": "sk-fake-not-used"},
                                 require_cassette_binding=False)
    assert h.claude_decider is None
    assert "Claude API not available: client construction failed" in capsys.readouterr().out


# ---- 2. structure of the split ---------------------------------------------------------

def test_ivr_governor_is_a_thin_subclass_of_the_kernels_generic_one():
    from governance_decider import GovernanceDecider

    assert issubclass(ClaudeGovernanceDecider, GovernanceDecider)
    own = set(vars(ClaudeGovernanceDecider))
    assert {"decide_healing_bounds", "decide_staffing_adjustment",
            "decide_queue_reordering"} <= own
    # The generic, fail-closed safety check is inherited, never re-implemented.
    assert "safety_check" not in own and "get_decision_log" not in own
    assert "__init__" not in own


def test_the_ivr_pack_builds_the_ivr_governor():
    h = IcebergProductionHarness(dict(NO_SERVICES), require_cassette_binding=False)
    built = h.pack.build_governor("sk-fake-not-used")
    assert type(built) is ClaudeGovernanceDecider
    assert h.pack.build_governor(None).client is None


def _minimal_pack():
    """A pack that overrides nothing about governors, to see the default."""
    from domain_pack import DomainPack

    class _Pack(DomainPack):
        def required_capabilities(self):
            return ()

        def record_id(self, record):
            return None

        def assess(self, record, params):
            raise NotImplementedError

        def build_episode(self, assessment):
            raise NotImplementedError

    return _Pack()


def test_a_pack_that_names_no_governor_gets_the_kernels_domain_blind_one():
    from governance_decider import GovernanceDecider

    built = _minimal_pack().build_governor("sk-fake-not-used")
    assert type(built) is GovernanceDecider
    assert "ivr" not in GovernanceDecider.SYSTEM_INSTRUCTION.lower()
    assert _minimal_pack().build_governor(None).client is None


def test_the_default_governor_fails_closed_like_any_other():
    result = _minimal_pack().build_governor(None).safety_check("anything", {"k": 1})
    assert result["safe"] is False and result["governed"] is False
    assert result["model_identity"] is None


def test_the_domain_neutral_files_do_not_import_the_ivr_governor():
    import ast

    root = os.path.dirname(os.path.dirname(__file__))
    for name in ("governed_pipeline.py", "domain_pack.py"):
        with open(os.path.join(root, name)) as f:
            tree = ast.parse(f.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "claude_governance_api" not in imported, name
