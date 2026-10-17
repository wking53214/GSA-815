"""
Tests for the domain pack split (step 2 of the IVR separation).

TWO KINDS OF TEST LIVE HERE

1. Behavior pins for paths that moved in step 2 and that no earlier test
   covered: an unreadable record, cassette swap and refusal, batch processing,
   the order of metrics versus the governor, and the Twilio adapter hook.
   These describe what the harness did BEFORE the split. They were run against
   the pre-split code and passed there unchanged, then against the split code.

2. Structure checks for the split itself: the IVR pack satisfies the contract,
   and the generic core mentions nothing about phone calls.

NO DATABASE, NO NETWORK. Stand-ins only.
"""

import ast
import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import cassette_capabilities  # noqa: E402
from cassette_capabilities import CapabilityError  # noqa: E402
from cassette_loader import CassetteLoader  # noqa: E402
from production_harness import IcebergProductionHarness  # noqa: E402
from twilio_log_ingestion import IcebergJourney, TwilioStreamAdapter  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
NO_SERVICES = {"postgres_host": None, "claude_api_key": None, "twilio_account_sid": None}
RECORD = {"sid": "CAPACK", "status": "completed", "duration": "120", "from": "+1", "to": "+2"}


# ---- stand-ins -----------------------------------------------------------------

class _FakeLedger:
    def __init__(self):
        self.written = []

    def sid_exists(self, sid):
        return False

    def append_decision(self, record, governance_params=None):
        self.written.append(record)


class _FakeGovernor:
    """Approves, and notes how many calls the metrics had counted when asked."""

    def __init__(self, harness):
        self.harness = harness
        self.calls = []
        self.calls_counted_when_asked = []

    def safety_check(self, action, details):
        self.calls.append((action, details))
        self.calls_counted_when_asked.append(
            self.harness.metrics.get_summary()["calls_total"])
        return {"safe": True, "governed": True, "parse_failed": False,
                "reasoning": "stub approve", "risk_level": "low",
                "confidence": 0.9, "model_identity": None, "cost": None}


def _harness(config=None):
    return IcebergProductionHarness(dict(config or NO_SERVICES),
                                    require_cassette_binding=False)


def _frictionful_journey(h):
    long_wait = h._params().float_value("long_wait_threshold")
    over = long_wait + 10.0
    nodes = ["root", "intent_menu", "billing_queue", "agent_a", "exit"]
    return IcebergJourney(
        caller_id="twilio_PACK", timestamp=0, journey=nodes,
        wait_times=dict(zip(nodes[1:4], [over, over, over])),
        total_duration=350.0, resolved=True, friction_count=0,
        abandonment_reason=None)


def _non_ivr_cassette():
    """The kernel's own banking cassette: a real domain with no telephony."""
    kernel_dir = os.path.dirname(cassette_capabilities.__file__)
    path = os.path.join(kernel_dir, "cassettes", "banking_cassette.py")
    spec = importlib.util.spec_from_file_location("kernel_banking_cassette_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BankingCassette()


# ---- 1. behavior pins ----------------------------------------------------------

def test_unreadable_record_is_returned_plainly_and_does_no_work():
    h = _harness()
    h.twilio_parser.parse_call_log = lambda rec: None
    governor, ledger = _FakeGovernor(h), _FakeLedger()
    h.claude_decider, h.ledger = governor, ledger
    before = h.metrics.get_summary()["calls_total"]

    result = h.process_call(RECORD)

    assert result == {"error": "Failed to parse call"}
    assert governor.calls == [], "an unreadable record must not reach the governor"
    assert ledger.written == [], "an unreadable record must not be written"
    assert h.metrics.get_summary()["calls_total"] == before, "no metrics for an unreadable record"


def test_metrics_are_recorded_before_the_governor_is_asked():
    h = _harness()
    journey = _frictionful_journey(h)
    h.twilio_parser.parse_call_log = lambda rec: journey
    governor = _FakeGovernor(h)
    h.claude_decider, h.ledger = governor, _FakeLedger()
    before = h.metrics.get_summary()["calls_total"]

    result = h.process_call(RECORD)

    assert result["governance_required"] is True
    assert governor.calls_counted_when_asked == [before + 1]
    assert h.metrics.get_summary()["calls_total"] == before + 1


def test_batch_counts_this_batch_only_and_returns_every_result():
    h = _harness()
    journey = _frictionful_journey(h)
    h.twilio_parser.parse_call_log = lambda rec: journey
    h.process_call(RECORD)  # an earlier call must not leak into the batch figures

    summary = h.process_batch([RECORD, RECORD])

    assert summary["calls_processed"] == 2
    assert summary["calls_total"] == 2
    assert len(summary["results"]) == 2


def test_cassette_swap_repoints_the_ivr_parts_and_the_next_call_runs():
    h = _harness()
    old_sentinel = h.sentinel
    new_cassette = CassetteLoader().load_cassette("ivr")
    assert new_cassette is not h.cassette

    h.swap_cassette(new_cassette)

    assert h.cassette is new_cassette
    assert h.twilio_parser.cassette is new_cassette
    assert h.sentinel is not old_sentinel
    journey = _frictionful_journey(h)
    h.twilio_parser.parse_call_log = lambda rec: journey
    assert "error" not in h.process_call(RECORD)


def test_a_cassette_without_phone_capabilities_is_refused_at_swap_and_nothing_changes():
    h = _harness()
    kept, kept_sentinel = h.cassette, h.sentinel

    with pytest.raises(CapabilityError) as err:
        h.swap_cassette(_non_ivr_cassette())

    assert "IcebergProductionHarness.swap_cassette" in str(err.value)
    assert "telephony_ingest" in str(err.value)
    assert h.cassette is kept and h.sentinel is kept_sentinel


def test_a_cassette_without_phone_capabilities_is_refused_at_startup():
    with pytest.raises(CapabilityError) as err:
        IcebergProductionHarness(dict(NO_SERVICES), cassette=_non_ivr_cassette(),
                                 require_cassette_binding=False)
    assert str(err.value).startswith("IcebergProductionHarness requires capabilities")


def test_a_kernel_verdict_that_disagrees_with_legacy_scoring_is_recorded_not_hidden(caplog):
    """The kernel and the old call scoring are meant to agree. When they do
    not, the call must carry on using the old score, the disagreement must be
    on the ledger row, and a warning must be logged."""
    class _Verdict:
        tier = "tier_that_never_matches"
        score = 0.5

    ivr_cassette_class = type(CassetteLoader().load_cassette("ivr"))

    class _Disagrees(ivr_cassette_class):
        def judge(self, episode):
            return _Verdict()

    h = IcebergProductionHarness(dict(NO_SERVICES), cassette=_Disagrees(),
                                 require_cassette_binding=False)
    journey = _frictionful_journey(h)
    h.twilio_parser.parse_call_log = lambda rec: journey
    ledger = _FakeLedger()
    h.claude_decider, h.ledger = _FakeGovernor(h), ledger

    with caplog.at_level("WARNING"):
        result = h.process_call(RECORD)

    assert "error" not in result
    kernel = ledger.written[0].input_data["kernel"]
    assert kernel["agrees_with_legacy_scoring"] is False
    assert kernel["tier"] == "tier_that_never_matches"
    warnings = [r for r in caplog.records
                if "kernel judgment disagrees with legacy scoring" in r.message]
    assert warnings, "a disagreement must be logged"
    legacy_tier = warnings[0].extra_data["legacy_tier"]
    assert result["quality"] == legacy_tier != kernel["tier"], \
        "the call keeps acting on the legacy score"


def test_twilio_adapter_is_built_only_when_credentials_are_configured():
    assert _harness().twilio_adapter is None
    configured = _harness({**NO_SERVICES, "twilio_account_sid": "ACtest",
                           "twilio_api_key": "k", "twilio_api_secret": "s"})
    assert isinstance(configured.twilio_adapter, TwilioStreamAdapter)


# ---- 2. structure of the split --------------------------------------------------

def test_ivr_pack_satisfies_the_contract():
    from domain_pack import DomainPack
    from ivr_pack import IvrPack

    h = _harness()
    assert isinstance(h.pack, IvrPack) and isinstance(h.pack, DomainPack)
    assert set(h.pack.required_capabilities()) == {
        "telephony_ingest", "routing_topology", "self_healing"}
    assert h.pack.default_cassette_domain == "ivr"
    assert h.pack.record_id({"sid": "CAX"}) == "CAX"
    assert h.pack.record_id({}) is None


# The generic core must stay free of phone-call vocabulary and of every module
# that carries it. If this fails, domain logic has leaked back into the core.
_FORBIDDEN_MODULES = {
    "twilio_log_ingestion", "observe_perceive_core", "sentinel_core",
    "metrics_prometheus", "queue_staffing_bayes_integration", "ivr_pack",
    "production_harness", "governance.friction_core",
}
_FORBIDDEN_WORDS = ("twilio", "friction", "emotion", "bayes", "metrics",
                    "queue", "journey", "ivr")


def _core_tree():
    with open(os.path.join(REPO_ROOT, "governed_pipeline.py")) as f:
        return ast.parse(f.read())


def test_generic_core_imports_nothing_from_the_ivr_side():
    imported = set()
    for node in ast.walk(_core_tree()):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not imported & _FORBIDDEN_MODULES, imported & _FORBIDDEN_MODULES


def test_generic_core_uses_no_phone_call_names():
    offenders = set()
    for node in ast.walk(_core_tree()):
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        for name in names:
            if any(word in name.lower() for word in _FORBIDDEN_WORDS):
                offenders.add(name)
    assert not offenders, offenders
