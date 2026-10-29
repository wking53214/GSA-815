"""
Proof that GSA-815 runs without IVR (step 4 of the IVR separation).

THE CLAIM
    "IVR in GSA-815 is a placeholder example of functionality. GSA-815 should
    be able to run without the IVR component."

THE TEST
    A made-up expense-approval domain (Tests/toy_expense_pack.py) is run
    through the real generic core (governed_pipeline.GovernedPipeline):

      expense record -> pack describes the case -> kernel judges it
      -> the kernel's own AI governor signs off (or refuses)
      -> decision written to the real hash-chained Postgres ledger

    What is real: the pipeline, the pack contract, the kernel judgment, the
    kernel's governor code (including its fail-closed behavior), the
    cassette schema checks and content binding, and the Postgres ledger.
    What is stood in: only the network call to the AI model. The model client
    returns a canned answer and records what it was asked.

    The last test starts a fresh Python process and proves that running this
    domain never even loads a phone-call module.

NEEDS POSTGRES (same as test_production_harness_breakers.py).
"""

import json
import os
import subprocess
import sys
import types

import psycopg2
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from domain_pack import DomainPack  # noqa: E402
from governance_decider import GovernanceDecider  # noqa: E402
from governed_pipeline import GovernedPipeline  # noqa: E402
from toy_expense_pack import ExpenseCassette, ExpensePack  # noqa: E402

PG = dict(host="localhost", port=5432, dbname="iceberg", user="iceberg", password="iceberg")
PIPELINE_CONFIG = {
    "postgres_host": PG["host"], "postgres_port": PG["port"],
    "postgres_db": PG["dbname"], "postgres_user": PG["user"],
    "postgres_password": PG["password"],
}

APPROVES = {"safe": True, "risk_level": "low", "reasoning": "receipt is routine",
            "recommendations": [], "confidence": 0.9}
REFUSES = {"safe": False, "risk_level": "high", "reasoning": "no receipt on a large amount",
           "recommendations": [], "confidence": 0.8}

# 480 over the 75 limit with no receipt = 1 problem (manager did approve).
ONE_PROBLEM = {"expense_id": "EXP-1", "amount": 480.0, "category": "travel",
               "receipt_attached": False, "manager_approved": True}
# Fine on both counts = 0 problems.
CLEAN = {"expense_id": "EXP-CLEAN", "amount": 40.0, "category": "meals",
         "receipt_attached": False, "manager_approved": True}
# No receipt and no manager approval = 2 problems.
TWO_PROBLEMS = {"expense_id": "EXP-2", "amount": 900.0, "category": "equipment",
                "receipt_attached": False, "manager_approved": False}


# ---- stand-ins and helpers ---------------------------------------------------------

class _ModelClient:
    """The only fake: answers canned JSON and keeps the requests it was sent."""

    def __init__(self, reply):
        self.calls = []
        self._reply = reply
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=json.dumps(self._reply))],
            model="claude-opus-4-6", usage=None)


def _connect():
    conn = psycopg2.connect(**PG)
    conn.autocommit = True
    return conn


@pytest.fixture(autouse=True)
def _empty_ledger():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("ALTER TABLE ledger_entries DISABLE TRIGGER USER;")
    cur.execute("TRUNCATE ledger_entries RESTART IDENTITY;")
    cur.execute("ALTER TABLE ledger_entries ENABLE TRIGGER USER;")
    conn.close()
    yield


def _pipeline(reply=APPROVES, with_governor=True, cassette=None):
    config = dict(PIPELINE_CONFIG)
    if with_governor:
        config["claude_api_key"] = "sk-fake-not-used"
    # Cassette binding stays ON (the default): the expense cassette must be
    # content-bound into the ledger like any other.
    pipeline = GovernedPipeline(config, ExpensePack(), cassette=cassette or ExpenseCassette())
    if with_governor:
        pipeline.claude_decider.client = _ModelClient(reply)
    return pipeline


def _decision_rows():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""SELECT node, cassette_version, input_data, decision_output,
                          policy_parameters, call_sid, cassette_code_hash,
                          model_identity, reason
                   FROM ledger_entries WHERE record_kind = 'governance_decision'
                   ORDER BY id""")
    rows = cur.fetchall()
    conn.close()
    return rows


# ---- the domain is a pack like any other -------------------------------------------

def test_the_expense_pack_satisfies_the_same_contract_as_ivr():
    pack = ExpensePack()
    assert isinstance(pack, DomainPack)
    assert pack.required_capabilities() == ()
    assert pack.record_id({"expense_id": "E9"}) == "E9"
    assert type(pack.build_governor("sk-fake-not-used")) is GovernanceDecider


def test_the_cassette_is_kernel_only_and_passes_the_kernel_schema_checks():
    from cassette_schema import validate_cassette

    params = validate_cassette(ExpenseCassette())
    assert params.capabilities == ()
    assert params.int_value("governance_trigger") == 1
    assert params.float_value("receipt_required_over") == 75.0


# ---- end to end --------------------------------------------------------------------

def test_an_expense_with_no_problems_is_not_governed_and_nothing_is_recorded():
    p = _pipeline()

    result = p.process(CLEAN)

    assert result["governance_required"] is False
    assert result["governance_blocked"] is False
    assert result["problems"] == []
    assert p.claude_decider.client.calls == [], "the governor is only asked when required"
    assert _decision_rows() == []


def test_a_flagged_expense_is_judged_signed_off_by_the_governor_and_recorded():
    p = _pipeline(APPROVES)

    result = p.process(ONE_PROBLEM)

    # What the caller is told.
    assert result == {
        "expense_id": "EXP-1", "problems": ["missing_receipt"],
        "claude_safe": True, "governance_required": True,
        "governance_approved": True, "governance_blocked": False,
        "ledger_write_failed": False, "governed": True,
        "cassette_version": "expense:expense-v1:1.0.0",
        "estimated_fields": ["tax_portion"],
        "field_provenance": {
            "amount": "verified", "manager_approved": "verified",
            "receipt_attached": "verified", "tax_portion": "estimated",
        },
    }

    # What the governor was asked: the kernel's domain-blind wording, with the
    # case delivered as data. Nothing about phone calls.
    (sent,) = p.claude_decider.client.calls
    system_text = json.dumps(sent["system"]).lower()
    assert "safety auditor for automated governance decisions" in system_text
    assert "ivr" not in system_text
    user_text = json.dumps(sent["messages"])
    assert "approve_expense" in user_text and "EXP-1" in user_text

    # What the ledger holds.
    (row,) = _decision_rows()
    (node, cassette_version, input_data, output, policy, call_sid,
     code_hash, model_identity, reason) = row
    assert node == "travel"
    assert cassette_version == "expense:expense-v1:1.0.0"
    assert call_sid == "EXP-1"
    assert reason == "receipt is routine"
    assert output["approved"] is True and output["risk_level"] == "low"
    assert model_identity == "claude-opus-4-6"
    assert code_hash, "the cassette's decision code is hashed into the row"
    assert policy["parameters"]["receipt_required_over"]["value"] == 75.0
    assert policy["capabilities"] == []

    assert input_data["amount"] == 480.0 and input_data["problems"] == ["missing_receipt"]
    kernel = input_data["kernel"]
    assert kernel["judged"] is True
    assert kernel["tier"] == "good" and kernel["score"] == pytest.approx(0.6)
    # The kernel's provenance record: what was measured and what was derived.
    assert kernel["estimated_fields"] == ["tax_portion"]
    assert kernel["field_provenance"]["amount"] == "verified"
    assert kernel["field_provenance"]["tax_portion"] == "estimated"
    assert kernel["source_events"] == ["EXP-1:submitted", "EXP-1:tax_split"]


def test_a_governor_refusal_blocks_the_expense_and_the_refusal_is_recorded():
    p = _pipeline(REFUSES)

    result = p.process(TWO_PROBLEMS)

    assert result["claude_safe"] is False
    assert result["governance_approved"] is False
    assert result["governance_blocked"] is True
    (row,) = _decision_rows()
    assert row[3]["approved"] is False
    assert row[2]["kernel"]["tier"] == "poor"  # two problems: 1.0 - 0.8 = 0.2


def test_with_no_governor_configured_a_required_expense_is_blocked_not_waved_through():
    p = _pipeline(with_governor=False)

    result = p.process(ONE_PROBLEM)

    assert result["governance_required"] is True
    assert result["governance_approved"] is False
    assert result["governance_blocked"] is True
    (row,) = _decision_rows()
    assert row[3]["approved"] is False
    assert "no governor configured" in row[8].lower()


def test_an_approval_that_could_not_be_recorded_does_not_count_as_approved():
    p = _pipeline(APPROVES)

    def _write_fails(*args, **kwargs):
        raise RuntimeError("simulated ledger outage")

    p.ledger.append_decision = _write_fails

    result = p.process(ONE_PROBLEM)

    assert result["claude_safe"] is True, "the governor did approve"
    assert result["ledger_write_failed"] is True
    assert result["governance_approved"] is False, "but an unrecorded approval is not an approval"
    assert result["governance_blocked"] is True


def test_the_governing_policy_is_read_fresh_so_a_swapped_cassette_changes_the_next_decision():
    p = _pipeline()
    assert p.process(ONE_PROBLEM)["governance_required"] is True

    p.swap_cassette(ExpenseCassette(governance_trigger=2))

    # The same one-problem expense now falls below the new trigger.
    again = dict(ONE_PROBLEM, expense_id="EXP-1B")
    assert p.process(again)["governance_required"] is False
    # A two-problem expense still reaches the governor.
    assert p.process(TWO_PROBLEMS)["governance_required"] is True


def test_the_same_expense_cannot_be_decided_twice():
    p = _pipeline()
    assert "error" not in p.process(ONE_PROBLEM)

    second = p.process(ONE_PROBLEM)

    assert second["error"] == "duplicate_sid"
    assert second["sid"] == "EXP-1"
    assert len(p.claude_decider.client.calls) == 1, "the governor is not asked twice"
    assert len(_decision_rows()) == 1


def test_an_unreadable_record_is_returned_plainly_and_does_no_work():
    p = _pipeline()

    result = p.process({"expense_id": "EXP-BAD", "amount": "lots"})

    assert result == {"error": "Failed to read expense"}
    assert p.claude_decider.client.calls == []
    assert _decision_rows() == []


def test_the_pack_hook_runs_for_every_readable_expense():
    p = _pipeline()
    p.process(CLEAN)
    p.process({"expense_id": "EXP-BAD", "amount": "lots"})
    p.process(ONE_PROBLEM)
    assert p.pack.assessed == ["EXP-CLEAN", "EXP-1"]


def test_the_ledger_chain_verifies_after_several_expense_decisions():
    p = _pipeline()
    p.process(ONE_PROBLEM)
    p.process(TWO_PROBLEMS)
    p.process(dict(ONE_PROBLEM, expense_id="EXP-3"))

    report = p.ledger.verify_chain()

    assert report["ok"] is True and report["violations"] == [], report
    # The three decisions, plus whatever startup rows the kernel writes (the
    # cassette binding, and on newer kernels more). Only the floor is pinned.
    assert report["entries"] >= 3
    assert len(_decision_rows()) == 3


# ---- the claim itself --------------------------------------------------------------

_IVR_MODULES = [
    "ivr_pack", "production_harness", "claude_governance_api",
    "twilio_log_ingestion", "observe_perceive_core", "sentinel_core",
    "metrics_prometheus", "queue_staffing_bayes_integration",
    "governance.friction_core",
]

_CHILD = """
import json, sys
sys.path[:0] = [{repo!r}, {tests!r}]
sys.path.append({kernel!r})
from governed_pipeline import GovernedPipeline
from toy_expense_pack import ExpenseCassette, ExpensePack
pipeline = GovernedPipeline({{}}, ExpensePack(), cassette=ExpenseCassette(),
                            require_cassette_binding=False)
result = pipeline.process({record!r})
loaded = [m for m in {ivr!r} if m in sys.modules]
print(json.dumps({{"result": result, "ivr_modules_loaded": loaded}}))
"""


def test_running_a_non_ivr_domain_never_loads_any_ivr_module():
    """A fresh process, so nothing another test imported can hide a leak."""
    code = _CHILD.format(
        repo=REPO_ROOT, tests=os.path.dirname(__file__),
        kernel=os.path.join(REPO_ROOT, "vendor", "sentinel_os", "sentinel_os"),
        record=ONE_PROBLEM, ivr=_IVR_MODULES)

    done = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=120, cwd=REPO_ROOT)

    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["ivr_modules_loaded"] == []
    assert out["result"]["governance_required"] is True  # it really ran a case
