"""An IVR call goes through the REAL ledger with its observed events.

The stand-in ledger tests show the pipeline hands the events over. This one shows the real ledger and the
real conservation boundary accept them: the kernel attests the episode against its events (sentinel_os #88)
and the event stream is written beside the decision. Needs the local Postgres the other real-ledger tests use.
"""
from __future__ import annotations

import os
import sys

import psycopg2
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("ICEBERG_LEDGER_RUNTIME_USER", "")

from production_harness import IcebergProductionHarness  # noqa: E402

PG_DSN = dict(host="localhost", port=5432, dbname="iceberg", user="iceberg", password="iceberg")


class _Approves:
    def safety_check(self, action, details):
        return {"safe": True, "governed": True, "parse_failed": False,
                "reasoning": "stub approve", "risk_level": "low",
                "confidence": 0.9, "model_identity": None, "cost": None}


def _clear_ledger():
    conn = psycopg2.connect(**PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("ALTER TABLE ledger_entries DISABLE TRIGGER USER;")
    cur.execute("TRUNCATE ledger_entries RESTART IDENTITY;")
    cur.execute("ALTER TABLE ledger_entries ENABLE TRIGGER USER;")
    conn.close()


def _count(kind):
    conn = psycopg2.connect(**PG_DSN)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM ledger_entries WHERE record_kind = %s", (kind,))
        return cur.fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def harness():
    h = IcebergProductionHarness({
        "postgres_host": PG_DSN["host"], "postgres_port": PG_DSN["port"],
        "postgres_db": PG_DSN["dbname"], "postgres_user": PG_DSN["user"],
        "postgres_password": PG_DSN["password"], "cassette_domain": "ivr",
        "claude_api_key": None,
    })
    _clear_ledger()
    h.claude_decider = _Approves()
    yield h
    h.shutdown()


def test_a_governed_call_is_recorded_with_its_events_through_the_real_ledger(harness):
    record = {"sid": "CAREALEV", "status": "completed", "from": "+15551234561", "duration": 320, "start_time": 0}
    result = harness.process_call(record)

    assert "error" not in result
    assert _count("governance_decision") == 1
    assert _count("observed_event") > 0, "the event stream must be written beside the decision"


def test_an_episode_its_events_do_not_support_is_refused_by_the_real_ledger(harness):
    """The point of passing the events: an episode that says more than they support is not recorded.

    The episode stays valid on its own; one of its events is withheld, so the episode claims a field no
    event supports. Only the attestation against the events can see that."""
    import dataclasses

    from conservation.boundary import ConservationBoundaryRejected

    original = harness.pack.build_episode

    def _drop_an_event(assessment):
        full = original(assessment)
        return dataclasses.replace(full, events=tuple(e for e in full.events if e.kind != "emotion_inferred"))

    harness.pack.build_episode = _drop_an_event

    raised = []
    real_append = harness.ledger.append_decision

    def _spy(*args, **kwargs):
        try:
            return real_append(*args, **kwargs)
        except Exception as exc:
            raised.append(exc)
            raise

    harness.ledger.append_decision = _spy
    record = {"sid": "CAUNSUPPORTED", "status": "completed", "from": "+15551234561", "duration": 320, "start_time": 0}
    result = harness.process_call(record)

    assert result.get("ledger_write_failed") is True
    assert raised and isinstance(raised[0], ConservationBoundaryRejected)
    assert "ROOT_NOT_ATTESTED" in str(raised[0])
    assert _count("observed_event") == 0 and _count("governance_decision") == 0, "a refused decision leaves nothing behind"
