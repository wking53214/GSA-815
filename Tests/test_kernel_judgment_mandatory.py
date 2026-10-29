"""The kernel's judgment is mandatory for a governed call.

A governed case (one the pack says needs sign-off) whose kernel judgment
failed must not be approved. The governor is not asked, the refusal is
reported like any other governance block, and the refused decision is still
written to the ledger. An ungoverned case is unchanged: the failure is
recorded and the call carries on.

No database, no network: the stand-ins come from the characterization tests.
"""

import pytest

from episode import EpisodeIntegrityError
from event_v1 import EventIntegrityError

import test_process_call_characterization as C

RECORD = {"sid": "CA-K", "status": "completed", "duration": "350",
          "from": "+1", "to": "+2"}


def _integrity():
    return EpisodeIntegrityError("CA-K", ["simulated kernel failure"])


def _event_integrity():
    return EventIntegrityError("EV-K", ["simulated kernel failure"])


def _key_error():
    return KeyError("simulated kernel failure")


def _harness(journey_name, kernel_failure=None, gov="approve"):
    h = C._harness()
    long_wait = h._params().float_value("long_wait_threshold")
    journey = C._journeys(long_wait)[journey_name]
    h.twilio_parser.parse_call_log = lambda rec: journey
    h.claude_decider = C._FakeGovernor(gov)
    h.ledger = C._FakeLedger()
    if kernel_failure is not None:
        def boom(assessment):
            raise kernel_failure()
        h.pack.build_episode = boom
    return h


@pytest.mark.parametrize("failure", [_integrity, _event_integrity, _key_error],
                         ids=["episode", "event", "key"])
def test_a_governed_call_the_kernel_could_not_judge_is_not_approved(failure):
    h = _harness("three_friction", failure)

    result = h.process_call(RECORD)

    assert result["governed"] is True
    assert result["governance_approved"] is False
    assert result["governance_blocked"] is True
    assert result["claude_safe"] is False
    assert result["ledger_write_failed"] is False
    assert result["estimated_fields"] is None
    assert result["field_provenance"] is None
    assert h.claude_decider.calls == [], "the governor is not asked when the kernel could not judge"


def test_the_refusal_is_written_to_the_ledger_with_the_kernel_error():
    h = _harness("three_friction", _integrity)

    h.process_call(RECORD)

    (row,) = h.ledger.written
    assert row.output["approved"] is False
    assert row.reasoning.startswith("Kernel judgment unavailable: EpisodeIntegrityError")
    assert row.input_data["kernel"]["judged"] is False
    assert row.input_data["kernel"]["error"] == "EpisodeIntegrityError"


def test_the_same_governed_call_is_approved_when_the_kernel_judges_it():
    """Control: the block above comes from the kernel failure, not the case."""
    h = _harness("three_friction")

    result = h.process_call(RECORD)

    assert result["governance_approved"] is True
    assert result["governance_blocked"] is False
    assert len(h.claude_decider.calls) == 1


def test_a_refused_decision_that_cannot_be_recorded_is_still_not_an_approval():
    h = _harness("three_friction", _integrity)
    h.ledger = C._FakeLedger(fail_on_write=True)

    result = h.process_call(RECORD)

    assert result["governance_approved"] is False
    assert result["governance_blocked"] is True
    assert result["ledger_write_failed"] is True


def test_an_ungoverned_call_the_kernel_could_not_judge_is_unchanged():
    healthy = _harness("no_friction").process_call(RECORD)
    h = _harness("no_friction", _integrity)

    result = h.process_call(RECORD)

    assert result["governance_required"] is False
    assert result["governance_blocked"] is False
    assert result["governance_approved"] is False
    assert h.claude_decider.calls == []
    assert h.ledger.written == []
    # Same response as the call the kernel could judge, apart from the labels
    # that come from the kernel's judgment.
    labels = ("estimated_fields", "field_provenance")
    assert result["estimated_fields"] is None
    assert {k: v for k, v in result.items() if k not in labels} == \
        {k: v for k, v in healthy.items() if k not in labels}
