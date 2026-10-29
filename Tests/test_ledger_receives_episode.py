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

    def sid_exists(self, sid):
        return False

    def append_decision(self, record, governance_params=None, episode=None):
        self.written.append(record)
        self.episodes.append(episode)


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
