"""Domain pack contract.

WHAT A DOMAIN PACK IS
    GSA-815 judges "cases" and decides whether an AI governor must sign off
    before the result is acted on. Everything about that process is generic
    EXCEPT knowing what a case looks like in one particular business domain.
    A domain pack is the plug-in that holds that knowledge. The generic core
    (governed_pipeline.py) asks the pack a fixed set of questions and does
    everything else itself.

    IVR (phone-call friction) is the first pack (ivr_pack.py). It is an
    example of a domain, not the definition of the system: the core must be
    able to run with a different pack and never mention a call, a queue, or a
    friction count.

WHAT THE PACK ANSWERS
    required_capabilities  What the pack needs from the kernel's cassette.
    record_id              A unique id for an incoming record (duplicates are
                           rejected by the core using this).
    assess                 Read one raw record and describe the case: where it
                           happened, whether governance is required, what to
                           ask the governor, what domain facts go in the
                           ledger row, what domain fields go in the response.
    build_episode          Turn the assessment into a kernel episode so the
                           kernel can judge it.
    annotate_kernel        (optional) Add domain cross-checks to the kernel
                           verdict, e.g. compare it with an older scoring path.
    on_assessed            (optional) Domain side effects after the verdict and
                           before the governance gate, e.g. metrics.

WHAT THE CORE KEEPS FOR ITSELF
    Duplicate rejection, reading the governing policy fresh at decision time,
    the kernel verdict, the governor call with its circuit breaker and loop
    guard, the ledger write, and the rule that a case counts as approved only
    when the governor approved AND the ledger recorded the decision.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Union


@dataclass
class Assessment:
    """What a pack tells the core about one case.

    label                 Where the case happened (an IVR queue today). Used as
                          the ledger row's node.
    value                 The numeric size of the case (call duration today).
                          Recorded as the ledger row's previous and applied
                          value, because governance does not change it.
    governance_required   True when this case must be signed off by the
                          governor. The pack owns the trigger rule.
    governor_action       The action name the governor is asked about.
    governor_facts        The facts handed to the governor.
    ledger_input          Domain facts for the ledger row. The core adds the
                          kernel verdict to this before writing.
    response_fields       Domain fields for the response. The core adds the
                          governance fields; on a name clash the core wins.
    trace_attributes      Extra attributes for the top-level trace span.
    private               State the pack needs later (for build_episode and
                          on_assessed). The core never reads it.
    """

    label: str
    value: float
    governance_required: bool
    governor_action: str
    governor_facts: Dict[str, Any]
    ledger_input: Dict[str, Any]
    response_fields: Dict[str, Any]
    trace_attributes: Dict[str, Any] = field(default_factory=dict)
    private: Any = None


@dataclass
class Rejection:
    """A record the pack cannot assess. The core returns `response` as is.

    Returned rather than raised so the trace is not marked as an error: an
    unreadable record is an expected outcome, not a crash.
    """

    response: Dict[str, Any]


@dataclass
class KernelAnnotation:
    """Domain additions to the kernel verdict.

    ledger_fields    Merged into the verdict recorded in the ledger row.
    span_attributes  Set on the kernel judgment trace span.
    """

    ledger_fields: Dict[str, Any] = field(default_factory=dict)
    span_attributes: Dict[str, Any] = field(default_factory=dict)


class DomainPack(ABC):
    """The contract every domain pack fulfils. See the module docstring."""

    # Used in capability error messages, so a refusal names who asked.
    consumer_name: str = "DomainPack"

    # Cassette domain loaded when the config does not name one.
    default_cassette_domain: Optional[str] = None

    @abstractmethod
    def required_capabilities(self) -> Tuple[str, ...]:
        """Capabilities the kernel cassette must enable for this pack."""

    @abstractmethod
    def record_id(self, record: Dict[str, Any]) -> Optional[str]:
        """A unique id for the record, or None if it has none."""

    @abstractmethod
    def assess(self, record: Dict[str, Any], params: Any) -> Union[Assessment, Rejection]:
        """Describe the case, or return a Rejection if the record is unreadable.

        `params` is the governing policy, read fresh by the core for this
        decision. Read thresholds from it here, never from literals.
        """

    @abstractmethod
    def build_episode(self, assessment: Assessment) -> Any:
        """Build the kernel episode assembly for this case.

        Must return an object with `.episode`, `.provenance` and
        `.source_events` (what event_v1.assemble_episode returns).
        """

    def annotate_kernel(self, assessment: Assessment, kernel_result: Any) -> KernelAnnotation:
        """Optional domain cross-check of the kernel verdict."""
        return KernelAnnotation()

    def on_assessed(self, assessment: Assessment) -> None:
        """Optional domain side effects, after the verdict, before the gate."""
        return None
