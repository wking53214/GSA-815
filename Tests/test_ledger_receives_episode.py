"""The governed pipeline hands the ledger the episode it judged.

The ledger verifies every decision against the episode it was judged from
(the conservation boundary) and refuses to record one that arrives without
it. These tests hold the pipeline to its half of that rule.

NO DATABASE, NO NETWORK. Stand-ins only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from episode import EpisodeIntegrityError  # noqa: E402
from production_harness import IcebergProductionHarness  # noqa: E402
from twilio_log_ingestion import IcebergJourney  # noqa: E402

NO_SERVICES = {"postgres_host": None, "claude_api_key": None, "twilio_account_sid": None}
RECORD = {"sid": "CAEPISODE", "status": "completed", "duration": "120", "from": "+1", "to": "+2"}


class _RecordingLedger:
    def __init__(self):
        self.written = []
        self.episodes = []
        self.observed = []

    def sid_exists(self, sid):
        return False

    def append_decision(self, record, governance_params=None, episode=None, observed_events=None):
        self.written.append(record)
        self.episodes.append(episode)
        self.observed.append(observed_events)


class _Approves:
    def safety_check(self, action, details):
        return {"safe": True, "governed": True, "parse_failed": False,
                "reasoning": "stub approve", "risk_level": "low",
                "confidence": 0.9, "model_identity": None, "cost": None}


def _wired_harness():
    h = IcebergProductionHarness(dict(NO_SERVICES), require_cassette_binding=False)
    long_wait = h._params().float_value("long_wait_threshold")
    over = long_wait + 10.0
    nodes = ["root", "intent_menu", "billing_queue", "agent_a", "exit"]
    journey = IcebergJourney(
        caller_id="twilio_EPISODE", timestamp=0, journey=nodes,
        wait_times=dict(zip(nodes[1:4], [over, over, over])),
        total_duration=350.0, resolved=True, friction_count=0,
        abandonment_reason=None)
    h.twilio_parser.parse_call_log = lambda rec: journey
    ledger = _RecordingLedger()
    h.claude_decider, h.ledger = _Approves(), ledger
    return h, ledger


def test_the_ledger_is_handed_the_episode_the_pack_built():
    h, ledger = _wired_harness()
    built = []
    original = h.pack.build_episode

    def _spy(assessment):
        assembly = original(assessment)
        built.append(assembly.episode)
        return assembly

    h.pack.build_episode = _spy

    result = h.process_call(RECORD)

    assert "error" not in result
    assert len(ledger.written) == 1 and len(built) == 1
    assert ledger.episodes[0] is built[0], "the ledger must verify the episode that was judged"


def test_a_call_whose_episode_cannot_be_built_reaches_the_ledger_with_no_episode():
    """So the ledger refuses it (fail closed) instead of the pipeline guessing one."""
    h, ledger = _wired_harness()

    def _cannot_build(assessment):
        raise EpisodeIntegrityError("ep-simulated", ["simulated malformed episode"])

    h.pack.build_episode = _cannot_build

    h.process_call(RECORD)

    assert ledger.episodes == [None]


def test_the_ledger_is_handed_the_events_the_episode_was_built_from():
    """With the events the kernel can refuse an episode they do not support (sentinel_os #88)."""
    h, ledger = _wired_harness()
    built = []
    original = h.pack.build_episode

    def _spy(assessment):
        assembly = original(assessment)
        built.append(assembly)
        return assembly

    h.pack.build_episode = _spy
    result = h.process_call(RECORD)

    assert "error" not in result
    events = ledger.observed[0]
    assert events, "the IVR pack builds events, so the ledger must receive them"
    assert tuple(e.event_id for e in sorted(events, key=lambda e: e.event_id)) == tuple(sorted(built[0].source_events))
    assert {e.episode_id for e in events} == {ledger.episodes[0].episode_id}


def test_the_ivr_packs_events_reproduce_its_episode_under_the_kernels_own_guard():
    """The risk in passing events is a good call refused as ROOT_NOT_ATTESTED. Run the kernel's real guard."""
    from conservation.episode_guard import EpisodeRootGuard  # noqa: E402  (kernel is on sys.path via conftest)

    h, ledger = _wired_harness()
    h.process_call(RECORD)

    EpisodeRootGuard().attest(ledger.episodes[0], ledger.observed[0])  # raises EpisodeNotAttested if not


def test_a_pack_whose_assembly_carries_no_events_passes_none():
    """The pack contract is unchanged: events are optional, and without them the ledger is called as before."""
    from episode import Episode  # noqa: F401,E402
    from event_v1 import EpisodeAssembly  # noqa: E402

    h, ledger = _wired_harness()
    original = h.pack.build_episode

    def _plain(assessment):
        full = original(assessment)
        return EpisodeAssembly(episode=full.episode, provenance=full.provenance,
                               estimated_fields=full.estimated_fields, source_events=full.source_events)

    h.pack.build_episode = _plain
    h.process_call(RECORD)

    assert ledger.observed == [None]
