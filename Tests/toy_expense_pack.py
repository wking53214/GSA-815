"""
A deliberately tiny, made-up domain pack: expense approval.

WHY THIS EXISTS
    GSA-815's claim is that IVR (phone-call friction) is one example of a
    domain, not the definition of the system. This file is a second, unrelated
    domain written against the same contract (domain_pack.py), to show the
    generic core (governed_pipeline.py) runs it with no phone-call code at all.

    It is test support, not production code. Nothing imports it except
    Tests/test_toy_pack_end_to_end.py. It also doubles as the smallest worked
    example of "how to write a pack".

THE DOMAIN
    An employee submits an expense. Two things can be wrong with it:
      - no receipt, on an amount over the policy's receipt limit
      - no manager approval
    When the number of problems reaches the policy's trigger, the AI governor
    must sign off before the expense is paid.

WHAT IS DELIBERATELY ABSENT
    No telephony, queues, friction, emotion, metrics or learning. The cassette
    enables NO optional capabilities (CAPABILITIES = ()): it is a "kernel-only"
    domain, which the kernel supports explicitly.
"""

import copy
from typing import Any, Dict, List, Optional, Tuple, Union

from cassette_interface import Cassette, CassetteConfig, QualityResult
from domain_pack import Assessment, DomainPack, Rejection
from episode import Episode
from event_v1 import (
    PROVENANCE_ESTIMATED,
    PROVENANCE_VERIFIED,
    assemble_episode,
    make_event,
)

DOMAIN = "expense"

# The kernel wants absolute epoch seconds, never offsets from zero.
SUBMITTED_AT = 1_760_000_000.0


class ExpenseCassette(Cassette):
    """The expense policy and how this domain judges one expense."""

    # Kernel-only: no optional capability is enabled, said explicitly.
    CAPABILITIES: Tuple[str, ...] = ()

    _GOVERNANCE_PARAMETERS = {
        "governance_trigger": {
            "value": 1,
            "type": "int",
            "min": 0,
            "max": 10,
            "unit": "policy problems",
            "description": "Expenses with this many problems or more go to the governor (inclusive).",
            "metadata": {
                "approval_date": None,
                "justification": "Toy value for the end-to-end proof; not a real policy.",
                "last_reviewed": None,
            },
        },
        "receipt_required_over": {
            "value": 75.0,
            "type": "float",
            "min": 0.0,
            "max": 10000.0,
            "unit": "USD",
            "description": "An expense above this amount needs a receipt.",
            "metadata": {
                "approval_date": None,
                "justification": "Toy value for the end-to-end proof; not a real policy.",
                "last_reviewed": None,
            },
        },
    }

    def __init__(self, governance_trigger: Optional[int] = None):
        self._params = copy.deepcopy(self._GOVERNANCE_PARAMETERS)
        if governance_trigger is not None:
            self._params["governance_trigger"]["value"] = governance_trigger

    def get_config(self) -> CassetteConfig:
        return CassetteConfig(
            name="expense-v1",
            version="1.0.0",
            description="Toy expense approval (test support)",
            domain=DOMAIN,
        )

    def get_governance_parameters(self) -> Dict[str, Dict]:
        return copy.deepcopy(self._params)

    def _problems(self, episode: Episode) -> int:
        return int(episode.attributes["policy_problems"])

    def judge(self, episode: Episode) -> QualityResult:
        # Each problem costs 0.4. Reads the observed record only, never the
        # actor's own report.
        if "manager_approved" not in episode.actual:
            raise KeyError("expense judgment requires episode.actual['manager_approved']")
        score = max(0.0, round(1.0 - 0.4 * self._problems(episode), 6))
        if score >= 0.8:
            tier = "excellent"
        elif score >= 0.5:
            tier = "good"
        elif score >= 0.2:
            tier = "poor"
        else:
            tier = "failed"
        return QualityResult(score=score, tier=tier)

    def explain(self, episode: Episode) -> List[Dict[str, Any]]:
        return [{"factor": "policy_problems", "count": self._problems(episode),
                 "cost_each": 0.4}]

    def validate(self) -> bool:
        return True


class ExpensePack(DomainPack):
    """Reads one expense record and describes the case to the core."""

    consumer_name = "ExpensePack"

    def __init__(self):
        self.assessed: List[str] = []  # proves the on_assessed hook ran

    def required_capabilities(self) -> Tuple[str, ...]:
        return ()

    def record_id(self, record: Dict[str, Any]) -> Optional[str]:
        return record.get("expense_id")

    def assess(self, record: Dict[str, Any], params: Any) -> Union[Assessment, Rejection]:
        try:
            amount = float(record["amount"])
        except (KeyError, TypeError, ValueError):
            return Rejection({"error": "Failed to read expense"})

        problems: List[str] = []
        if amount > params.float_value("receipt_required_over") and not record.get("receipt_attached"):
            problems.append("missing_receipt")
        if not record.get("manager_approved"):
            problems.append("no_manager_approval")

        expense_id = record["expense_id"]
        category = str(record.get("category", "other"))
        return Assessment(
            label=category,
            value=amount,
            governance_required=len(problems) >= params.int_value("governance_trigger"),
            governor_action="approve_expense",
            governor_facts={"expense_id": expense_id, "amount": amount,
                            "category": category, "problems": problems},
            # The ledger finds earlier records of the same case by the key
            # `call_sid` (a leftover from the phone domain, in the kernel's
            # ledger). A pack that wants duplicate rejection supplies its id
            # under that key.
            ledger_input={"call_sid": expense_id, "expense_id": expense_id,
                          "amount": amount, "category": category,
                          "problems": problems},
            response_fields={"expense_id": expense_id, "problems": problems},
            private={"record": dict(record), "problems": problems},
        )

    def build_episode(self, assessment: Assessment):
        record = assessment.private["record"]
        expense_id = record["expense_id"]
        amount = assessment.value
        events = [
            make_event(
                event_id=f"{expense_id}:submitted", episode_id=expense_id,
                domain=DOMAIN, kind="expense_submitted",
                occurred_at=SUBMITTED_AT, observed_at=SUBMITTED_AT + 1.0,
                source="expense_system:export",
                provenance=PROVENANCE_VERIFIED,
                fields={"amount": amount,
                        "manager_approved": bool(record.get("manager_approved")),
                        "receipt_attached": bool(record.get("receipt_attached"))},
            ),
            # A derived number, honestly stamped as an estimate.
            make_event(
                event_id=f"{expense_id}:tax_split", episode_id=expense_id,
                domain=DOMAIN, kind="tax_estimated",
                occurred_at=SUBMITTED_AT + 1.0, observed_at=SUBMITTED_AT + 1.0,
                source="toy_expense_pack",
                provenance=PROVENANCE_ESTIMATED, method="amount * 0.10",
                fields={"tax_portion": round(amount * 0.10, 2)},
            ),
        ]
        return assemble_episode(
            episode_id=expense_id, domain=DOMAIN, requested={}, events=events,
            attributes={"policy_problems": len(assessment.private["problems"]),
                        "category": assessment.label},
        )

    def on_assessed(self, assessment: Assessment) -> None:
        self.assessed.append(assessment.private["record"]["expense_id"])
