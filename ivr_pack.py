"""
IVR domain pack - the first example of a domain on the governed pipeline.

Everything in here is specific to phone calls and IVR friction: reading a
Twilio call record, counting long waits as friction, inferring caller emotion,
scoring and labelling the call, building the call's kernel episode, and the
metrics and intent learning that follow a judged call.

It reads its working parts (parser, observer, scorer, metrics, learner,
cassette) from the harness that owns them, at the moment they are needed, so
swapping the cassette or replacing a part on the harness takes effect here too.
"""

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from claude_governance_api import ClaudeGovernanceDecider
from domain_pack import Assessment, DomainPack, KernelAnnotation, Rejection
from twilio_log_ingestion import (
    FALLBACK_ROUTE_METHOD, FALLBACK_WAIT_METHOD, NODE_ROLE_QUEUE,
)
from observe_perceive_core import FrictionEvent
from governance.friction_core import compute_friction
from tracing import tracer
from event_v1 import (PROVENANCE_ESTIMATED, PROVENANCE_VERIFIED,
                      EpisodeAssembly, assemble_episode, make_event)
from cassette_capabilities import (
    CAPABILITY_ROUTING_TOPOLOGY,
    CAPABILITY_SELF_HEALING,
    CAPABILITY_TELEPHONY_INGEST,
)
from operational_resilience import setup_logging

# Same logger name the harness has always used, so existing log filters and
# alerts keep matching.
logger = setup_logging("IcebergProductionHarness")


@dataclass
class _IvrCall:
    """What this pack remembers about one call between its steps."""

    journey: Any
    first_queue: str
    friction_count: int
    friction_events: List[Any]
    emotion: Any
    measured_waits: Dict[str, float]
    call_sid: Optional[str]
    twilio_record: Dict[str, Any]
    quality_score: Any
    intent_signal: Any


@dataclass(frozen=True)
class IvrEpisodeAssembly(EpisodeAssembly):
    """An `EpisodeAssembly` that also keeps the events the episode was folded from.

    The plain assembly keeps only their ids. The ledger needs the events themselves: with them the kernel
    registers the episode's root only if they reproduce it (sentinel_os #88), and the stream is written
    beside the decision. `events` is optional on purpose: a pack whose assembly has none is called as before.
    The events are built here from the same Twilio record as the episode, so this catches an episode that
    says more than its events support; it does not show the events are true."""

    events: Tuple[Any, ...] = ()


class IvrPack(DomainPack):
    """Phone-call friction domain. See the module docstring."""

    consumer_name = "IcebergProductionHarness"
    default_cassette_domain = "ivr"

    def __init__(self, harness):
        # The harness owns the working parts; this pack reads them live.
        self._h = harness

    def required_capabilities(self) -> Tuple[str, ...]:
        # This pipeline reads long_wait_threshold + Twilio ingest
        # (telephony), routes intent through SentinelCore (routing),
        # and clamps healing inside expected_wait_bounds (self_healing).
        return (CAPABILITY_TELEPHONY_INGEST, CAPABILITY_ROUTING_TOPOLOGY,
                CAPABILITY_SELF_HEALING)

    def build_governor(self, api_key: Optional[str]):
        # The kernel's governor plus the three IVR deciders.
        return ClaudeGovernanceDecider(api_key=api_key)

    def record_id(self, record: Dict[str, Any]) -> Optional[str]:
        return record.get("sid")

    # ---- OutcomeV1 / EventV1: the live path, stamped -------------------------
    #
    # Everything below exists to stop the pack handing the kernel numbers
    # whose origin it has forgotten. By default the route still comes from
    # twilio_log_ingestion's phone-digit rule and the per-node waits still
    # come from its fixed 0.1/0.5/0.4 split -- that default does not fix
    # either one, and is not pretending to. What changes is that both travel
    # with an honest stamp: ESTIMATED with the derivation named when the
    # ingest layer had to guess, VERIFIED naming the real source when the
    # Twilio record carried real per-node events (see twilio_log_ingestion's
    # ivr_events contract). The pack does not decide which happened for
    # a given call -- it reads whatever twilio_log_ingestion already
    # determined and stamps that, honestly, rather than assuming.

    _EMOTION_METHOD = "observe_perceive_core.get_emotional_state: inferred from friction"
    _ORIGIN_METHOD = ("call start derived as (ingest time - total duration); Twilio "
                      "log ingest carries no absolute start timestamp")

    def assemble_live_episode(self, journey, first_queue, friction_count,
                              friction_events, emotion, measured_waits,
                              call_sid, twilio_record):
        """Build a validated Episode from stamped events for one live call.

        This is the seam that makes the governance kernel real. Until now every
        production caller of make_episode/judge_episode was a test; the live
        path scored calls through a parallel route and the kernel judged
        nothing that had happened.
        """
        observed_at = time.time()
        # The pipeline speaks EmotionalState objects, cassettes speak dicts.
        # SentinelCore already owns that boundary conversion; calling it rather
        # than writing a second one keeps this from becoming the two-places-
        # that-can-quietly-disagree problem the cassette system exists to end.
        emotion_dict = self._h.sentinel._emotion_as_dict(emotion)
        duration = float(journey.total_duration or 0.0)
        started_at = max(observed_at - duration, 1.0)
        base = f"{call_sid or journey.caller_id}"

        route_provenance = getattr(journey, "route_provenance", PROVENANCE_ESTIMATED)
        route_method = getattr(journey, "route_method", FALLBACK_ROUTE_METHOD)
        wait_provenance = getattr(journey, "wait_provenance", PROVENANCE_ESTIMATED)
        wait_method = getattr(journey, "wait_method", FALLBACK_WAIT_METHOD)

        # event_v1's own integrity rule: a VERIFIED event cannot carry a
        # `method` -- method names how something was DERIVED, and a
        # verified fact was observed, not derived (see event_v1.validate_
        # event). When real ivr_events produced this journey, the real
        # system's name still has to reach the ledger -- it goes in
        # `detail` instead, which carries no such restriction.
        route_is_verified = route_provenance == PROVENANCE_VERIFIED
        wait_is_verified = wait_provenance == PROVENANCE_VERIFIED

        route_detail = {"journey": list(journey.journey),
                         "origin_note": self._ORIGIN_METHOD}
        if route_is_verified:
            route_detail["real_source"] = route_method

        events = [
            make_event(
                event_id=f"{base}:route", episode_id=base, domain="ivr",
                kind="route_selected", occurred_at=started_at,
                observed_at=observed_at, source="twilio_log_ingestion",
                provenance=route_provenance,
                method=None if route_is_verified else route_method,
                fields={"route": first_queue}, detail=route_detail),
        ]
        for node, wait in sorted((measured_waits or {}).items()):
            wait_detail = {"node": node}
            if wait_is_verified:
                wait_detail["real_source"] = wait_method
            events.append(make_event(
                event_id=f"{base}:wait:{node}", episode_id=base, domain="ivr",
                kind="wait_observed",
                occurred_at=min(started_at + float(wait), observed_at),
                observed_at=observed_at, source="twilio_log_ingestion",
                provenance=wait_provenance,
                method=None if wait_is_verified else wait_method,
                fields={f"wait_{node}": float(wait)}, detail=wait_detail))
        events.append(make_event(
            event_id=f"{base}:emotion", episode_id=base, domain="ivr",
            kind="emotion_inferred", occurred_at=observed_at,
            observed_at=observed_at, source="observe_perceive_core",
            provenance=PROVENANCE_ESTIMATED, method=self._EMOTION_METHOD,
            fields={"emotion_frustration": emotion_dict.get("frustration")},
            detail={"emotion": emotion_dict}))
        # The only two facts here that Twilio actually reports rather than
        # something inferring: the call's final status and its duration.
        events.append(make_event(
            event_id=f"{base}:ended", episode_id=base, domain="ivr",
            kind="call_ended", occurred_at=observed_at, observed_at=observed_at,
            source="twilio:call_log", provenance=PROVENANCE_VERIFIED,
            fields={"resolved": bool(journey.resolved), "duration": duration},
            detail={"status": twilio_record.get("status")}))

        reasons = ()
        if not journey.resolved:
            reasons = (f"call ended unresolved (twilio status="
                       f"{twilio_record.get('status')!r}, friction_count="
                       f"{friction_count})",)
        assembly = assemble_episode(
            episode_id=base, domain="ivr",
            requested={"resolved": True},
            events=events,
            outcome_reasons=reasons,
            attributes={
                "duration": duration,
                "friction_count": int(friction_count),
                "emotion": emotion_dict,
                "journey": list(journey.journey),
                "friction_events": list(friction_events or []),
            })
        return IvrEpisodeAssembly(
            episode=assembly.episode, provenance=assembly.provenance,
            estimated_fields=assembly.estimated_fields, source_events=assembly.source_events,
            reducer_version=assembly.reducer_version, events=tuple(events))

    def assess(self, twilio_record: Dict[str, Any], params: Any):
        """Read one Twilio call record and describe the call."""
        h = self._h
        long_wait = params.float_value("long_wait_threshold")
        governance_trigger = params.int_value("governance_trigger")
        call_sid = twilio_record.get("sid")

        # 1. Parse Twilio record
        with tracer.start_as_current_span("twilio_parse") as parse_span:
            journey = h.twilio_parser.parse_call_log(twilio_record)
            if not journey:
                parse_span.set_attribute("parse.success", False)
                return Rejection({"error": "Failed to parse call"})
            parse_span.set_attribute("parse.success", True)
            parse_span.set_attribute("call.duration", journey.total_duration)

        # 2. Observe friction
        friction_events = []
        measured_waits = getattr(journey, "wait_times", {}) or {}
        if measured_waits:
            friction_count = 0
            for node in journey.journey:
                node_wait = measured_waits.get(node, 0)
                if compute_friction(node_wait, long_wait):
                    friction_count += 1
                    friction_events.append(
                        FrictionEvent(
                            node=node,
                            type="long_wait",
                            severity=0.5,
                            timestamp=0
                        )
                    )
        else:
            friction_count = getattr(journey, "friction_count", 0)

        # 3. Perceive emotional state
        emotion = h.observer.get_emotional_state(
            journey.caller_id, friction_events, journey.total_duration
        )

        # 4. Sentinel: Infer intent & quality
        # Role-tagged first (a real event source's own say-so), name
        # convention only as the fallback when nothing was tagged --
        # see twilio_log_ingestion's NODE ROLES section.
        node_roles = getattr(journey, "node_roles", {}) or {}
        first_queue = next(
            (n for n in journey.journey if node_roles.get(n) == NODE_ROLE_QUEUE),
            None)
        if first_queue is None:
            first_queue = next((n for n in journey.journey if "queue" in n),
                               "general_queue")
        intent_signal = h.sentinel.infer_intent(journey.journey, first_queue)
        quality_score = h.sentinel.score_outcome_quality(
            journey.resolved, journey.total_duration,
            friction_count, emotion
        )

        # The governance gate uses friction_count alone -- the measured value
        # from step 2, which is also what's handed to the governor and written
        # to the ledger. This used to gate on
        # max(friction_count, journey.friction_count), mixing the
        # measured value with twilio_log_ingestion's separate
        # ingest-side ESTIMATE (different heuristic, different
        # thresholds -- see _count_friction's own docstring, which
        # already states "the production harness does NOT use this
        # estimate on the governance path"; the max() contradicted
        # that). Confirmed live with an in-bounds retuned cassette:
        # the gate could govern and approve a call while the
        # governor and the ledger both saw friction_count=0 against
        # governance_trigger=2 -- a row that couldn't reproduce its
        # own decision. On the shipped default cassette this never
        # changed the outcome (measured >= ingest in every governed
        # case), so behavior here is unchanged for existing traffic.
        governance_required = friction_count >= governance_trigger

        return Assessment(
            label=first_queue,
            value=journey.total_duration,
            governance_required=governance_required,
            governor_action="heal_queue",
            governor_facts={
                "queue": first_queue,
                "wait_time": journey.total_duration,
                "friction_count": friction_count
            },
            ledger_input={
                "caller_id": journey.caller_id,
                "call_sid": call_sid,
                "friction_count": friction_count,
                "governance_trigger": governance_trigger,
                "wait_time": journey.total_duration,
                "quality_tier": quality_score.quality_tier.value,
                "intent_classification": intent_signal.classification,
                "intent_confidence": intent_signal.confidence,
                "intent_reasoning": intent_signal.reasoning,
            },
            response_fields={
                "caller_id": journey.caller_id,
                "resolved": journey.resolved,
                "quality": quality_score.quality_tier.value,
                "intent": intent_signal.queue_chosen,
                "intent_classification": intent_signal.classification,
                "emotion_frustration": emotion.frustration,
                "metrics_recorded": True,
                "friction_count": friction_count,
                "governance_trigger": governance_trigger,
            },
            trace_attributes={
                "call.queue": first_queue,
                "call.friction_count": friction_count,
            },
            private=_IvrCall(
                journey=journey, first_queue=first_queue,
                friction_count=friction_count, friction_events=friction_events,
                emotion=emotion, measured_waits=measured_waits,
                call_sid=call_sid, twilio_record=twilio_record,
                quality_score=quality_score, intent_signal=intent_signal),
        )

    def build_episode(self, assessment: Assessment):
        c: _IvrCall = assessment.private
        return self.assemble_live_episode(
            c.journey, c.first_queue, c.friction_count, c.friction_events,
            c.emotion, c.measured_waits, c.call_sid, c.twilio_record)

    def annotate_kernel(self, assessment: Assessment, kernel_result) -> KernelAnnotation:
        """Cross-check the kernel verdict against the legacy call scoring.

        quality_score stays the value this pack acts on, and the kernel's
        verdict is recorded ALONGSIDE it. The IVR cassette's judge() and
        score_outcome_quality() are documented as arithmetically identical;
        this is what continuously proves it.
        """
        c: _IvrCall = assessment.private
        legacy_tier = c.quality_score.quality_tier.value
        agrees = str(kernel_result.tier).lower() == str(legacy_tier).lower()
        if not agrees:
            # Not swallowed and not fatal: the pack keeps acting on the
            # legacy score, and the divergence is on the record for someone
            # to go look at.
            logger.warning(
                "kernel judgment disagrees with legacy scoring",
                extra={"extra_data": {
                    "call_sid": c.call_sid,
                    "kernel_tier": kernel_result.tier,
                    "legacy_tier": legacy_tier}})
        return KernelAnnotation(
            ledger_fields={"agrees_with_legacy_scoring": agrees},
            span_attributes={"kernel.agrees": agrees})

    def on_assessed(self, assessment: Assessment) -> None:
        """Metrics and intent learning for a judged call."""
        h = self._h
        c: _IvrCall = assessment.private
        journey = c.journey

        # 5. Record metrics
        h.metrics.record_call(
            wait_time=journey.total_duration * 0.3,
            resolved=journey.resolved,
            resolution_time=journey.total_duration
        )

        if c.friction_count > 0:
            h.metrics.record_drift_detection(c.first_queue, 0.2)

        # 6. Bayes: Update intent success rates
        #
        # Previously passed intent_signal.queue_chosen (e.g.
        # "billing_queue"), but BayesianIntentEngine.intent_stats is
        # keyed by the cassette's short intent labels (e.g. "billing").
        # observe_outcome() silently no-ops on an unrecognized key, so
        # every single observation was dropped -- the belief state
        # never updated no matter how many calls ran. classification
        # is the cassette-native label ("BILLING", "UNKNOWN", ...);
        # lowercased it matches intent_stats exactly for every mapped
        # queue.
        h.bayes.observe_outcome(
            c.intent_signal.classification.lower(),
            journey.resolved,
            journey.total_duration
        )
