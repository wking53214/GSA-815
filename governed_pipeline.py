"""
Governed pipeline - the domain-neutral core.

Takes one raw record, asks a domain pack (domain_pack.py) to describe the case,
has the kernel judge it, asks the AI governor to sign off when the pack says
governance is required, and records the decision in the ledger.

This module must stay free of any one domain's vocabulary. It never imports
phone, queue, friction, emotion or metrics code; everything of that kind
belongs to the pack. Tests/test_domain_pack_contract.py guards that.

Behavior is a straight move of what IcebergProductionHarness.process_call did,
pinned by Tests/test_process_call_characterization.py. Names of trace spans
and trace attributes ("process_call", "call.sid", ...) are unchanged on
purpose so existing dashboards keep working; renaming them is a later cleanup.
"""

from typing import Dict

from governance.ledger_postgres import PostgreSQLLedger, GovernanceDecisionRecord
from cassette_loader import CassetteLoader
from cassette_schema import validate_cassette
from tracing import tracer, mark_error
from episode import EpisodeIntegrityError, judge_episode
from event_v1 import EventIntegrityError, estimated_fields
from cassette_capabilities import CAPABILITY_OUTCOME_OBLIGATION, require_capabilities
from operational_resilience import setup_logging
from circuit_breaker import CircuitBreaker
from governance_loop_guard import PipelineStateEngine
from cassette_forensics import (
    compute_cassette_code_hash, compute_cassette_hash,
    serialize_cassette_for_ledger,
)
from domain_pack import DomainPack, Rejection

# Same logger name the harness has always used, so existing log filters and
# alerts keep matching.
logger = setup_logging("IcebergProductionHarness")


def _safe_code_hash(cassette_obj):
    """Compute the cassette CODE hash without ever raising (Item 3).

    A failure to hash the decision code must NOT crash a governance decision or
    block the ledger write -- so any exception yields None, which omits the
    field from the canonical form (the row simply carries no code-hash commitment
    rather than a wrong one). compute_cassette_code_hash is itself fail-closed
    internally (unreadable source becomes a marker string), so this is a
    belt-and-suspenders guard for anything unexpected in the object itself.
    """
    try:
        return compute_cassette_code_hash(cassette_obj)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"cassette code hash unavailable, omitting: {exc}")
        return None


class GovernedPipeline:
    """The generic governance pipeline: a domain pack plus the shared machinery.

    Subclasses (the IVR harness today) may override the three `_..._domain_...`
    hooks below to build and maintain whatever components their pack needs.
    """

    def __init__(self, config: Dict, pack: DomainPack, cassette=None,
                 require_cassette_binding: bool = True):
        """Initialize the pipeline.

        The cassette is THE governing policy for this pipeline. It is
        loaded (or injected), schema-validated fail-loud, and every
        governance number read later in process() comes from it --
        never from a literal in this file.

        require_cassette_binding (default True, fail-closed): a loaded
        cassette must be content-bound into the ledger (Item 2 /
        bind_cassette_version) before this pipeline will start. Without
        this, a cassette can govern real decisions with no ledger
        commitment of what content it actually is -- an operator could
        change parameters or code without changing the version string,
        and historical queries by version would silently return rows
        governed by different content. There is no env-var override for
        this in the real production entrypoint (sentinel_worker.py) --
        same posture as ICEBERG_LEDGER_RUNTIME_USER: no fallback ever.
        Set False only for local/dev/simulator callers that construct
        this pipeline directly and explicitly accept an unbound cassette.
        """

        self.config = config
        self.require_cassette_binding = require_cassette_binding
        self.pack = pack

        # Governing cassette: injected, or loaded for the configured
        # domain. Validated here so an invalid policy halts construction.
        self.cassette = cassette or CassetteLoader().load_cassette(
            config.get("cassette_domain", pack.default_cassette_domain)
        )
        validate_cassette(self.cassette)
        # The pack says what it reads from the cassette. Refuse a cassette
        # missing any of it at construction -- and again at swap -- rather
        # than mid-call.
        require_capabilities(
            self.cassette,
            pack.required_capabilities(),
            consumer=pack.consumer_name,
        )

        # Pack-specific components (the IVR harness builds its parser,
        # observer, scorer, metrics and learner here).
        self._init_domain_components()

        # Persistence
        self.ledger = None  # Will init if DB config provided

        # Governance
        self.claude_decider = None  # Will init if API key provided

        # Roadster phase-1 (F-A): per-resource breakers. Two separate
        # instances -- a struggling Postgres connection must never gate
        # the Claude governor call, or vice versa. Always constructed
        # (cheap, no I/O); only exercised when the corresponding client
        # below is actually configured.
        self.claude_breaker = CircuitBreaker(
            name="claude_governor", failure_threshold=5, reset_timeout_s=30,
        )
        self.ledger_breaker = CircuitBreaker(
            name="postgres_ledger", failure_threshold=3, reset_timeout_s=15,
        )

        # Catches a different failure mode than claude_breaker above: a
        # syntactically successful, correctly-parsed governor response
        # that repeats a PRIOR call's exact reasoning text verbatim --
        # not an API/transport error (claude_breaker would never see
        # this), a plausible signal of a stuck or degenerate response
        # instead. See governance_loop_guard.py for provenance.
        #
        # Observe-only: a repeated text is recorded (loop_repeats_seen, a
        # trace attribute, a log line) and never changes the decision. A
        # healthy governor repeats short verdicts across different calls and
        # on retries, so denying on a repeat refused healthy calls.
        self.claude_loop_guard = PipelineStateEngine()
        self.loop_repeats_seen = 0

        self._init_optional_components()

    # ---- hooks for subclasses that own pack-specific components ---------------

    def _init_domain_components(self):
        """Build components the pack needs. Runs once the cassette is valid."""

    def _init_domain_optional_components(self):
        """Build pack components that need external credentials."""

    def _on_cassette_swapped(self, cassette):
        """Re-point pack components at a newly swapped-in cassette."""

    # ---- shared machinery ------------------------------------------------------

    def _init_optional_components(self):
        """Initialize components that require external credentials"""

        # PostgreSQL ledger
        if self.config.get("postgres_host"):
            try:
                self.ledger = PostgreSQLLedger(
                    host=self.config.get("postgres_host", "localhost"),
                    port=self.config.get("postgres_port", 5432),
                    dbname=self.config.get("postgres_db", "iceberg"),
                    user=self.config.get("postgres_user", "iceberg"),
                    password=self.config.get("postgres_password", "iceberg")
                )
                print("✓ PostgreSQL ledger connected")
            except Exception as e:
                if self.require_cassette_binding:
                    # Fail-closed: binding is mandatory and needs a live
                    # ledger. A soft "not available" here would let the
                    # pipeline continue and govern real decisions with an
                    # unbound cassette -- exactly the gap this item closes.
                    raise RuntimeError(
                        f"PostgreSQL ledger unavailable and "
                        f"require_cassette_binding=True: cannot bind "
                        f"cassette without a ledger. Original error: {e}"
                    ) from e
                print(f"⚠ PostgreSQL not available: {e}")
                self.ledger = None
        elif self.require_cassette_binding:
            raise RuntimeError(
                "require_cassette_binding=True but no postgres_host "
                "configured: cannot bind cassette without a ledger. "
                "Set postgres_host, or pass require_cassette_binding=False "
                "for a dev/simulator harness that accepts an unbound "
                "cassette."
            )

        # Item 2: content-bind the loaded cassette into the ledger chain,
        # fail-closed, before any decision can be governed by it. Only
        # reachable here if either binding was required (ledger is
        # guaranteed present by the checks above) or binding was not
        # required but a ledger happens to be configured anyway -- in
        # both cases, binding an available ledger is strictly better
        # than not.
        if self.ledger is not None:
            cassette_snapshot = serialize_cassette_for_ledger(self._params())
            cassette_hash = compute_cassette_hash(cassette_snapshot)
            cassette_code_hash = _safe_code_hash(self.cassette)
            self.ledger.bind_cassette_version(
                cassette_snapshot.get("cassette_version"),
                cassette_hash,
                cassette_code_hash=cassette_code_hash,
                authorized_by=self.config.get("authorized_by"),
            )
            print(f"✓ Cassette bound: {cassette_snapshot.get('cassette_version')}")

        # Claude API
        if self.config.get("claude_api_key"):
            try:
                self.claude_decider = self.pack.build_governor(
                    self.config.get("claude_api_key"),
                )
                print("✓ Claude governance API connected")
            except Exception as e:
                print(f"⚠ Claude API not available: {e}")
                self.claude_decider = None

        self._init_domain_optional_components()

    def _params(self):
        """Re-validate and read the cassette AT DECISION TIME, fresh on
        every call. Never cached: if the governing policy is swapped,
        the very next decision must see it -- a cached snapshot would be
        a second, stale source of truth."""
        return validate_cassette(self.cassette)

    def swap_cassette(self, cassette) -> None:
        """Replace the governing cassette (validated fail-loud). The
        next process() reads the new policy; nothing is cached across
        the swap."""
        validate_cassette(cassette)
        require_capabilities(
            cassette,
            self.pack.required_capabilities(),
            consumer=f"{self.pack.consumer_name}.swap_cassette",
        )
        self.cassette = cassette
        self._on_cassette_swapped(cassette)

    def _outcome_obligation_declaration(self):
        """The maturation rule this cassette declares, or None.

        None is the honest answer for IVR and every other domain whose outcome
        is settled when the interaction ends -- see cassette_capabilities'
        anti-placeholder rule. A domain that does not enable the capability is
        not asked to invent a horizon."""
        try:
            if CAPABILITY_OUTCOME_OBLIGATION not in self.cassette.capabilities():
                return None
            return self.cassette.get_maturation_rule().declaration()
        except Exception as exc:
            logger.warning("cassette declares outcome_obligation but its maturation "
                           "rule could not be read; no obligation recorded",
                           extra={"extra_data": {"error": str(exc)}})
            return None

    def process(self, record: Dict) -> Dict:
        """Process one record through the complete pipeline"""

        with tracer.start_as_current_span("process_call") as root_span:
            record_id = self.pack.record_id(record)
            root_span.set_attribute("call.sid", record_id or "unknown")

            # 0. Reject duplicate submissions (Option A: hard reject).
            if record_id and self.ledger:
                with tracer.start_as_current_span("dedup_check"):
                    if self.ledger.sid_exists(record_id):
                        root_span.set_attribute("call.duplicate", True)
                        return {
                            "error": "duplicate_sid",
                            "detail": f"Call {record_id} has already been processed",
                            "sid": record_id,
                        }

            # Read the governing policy fresh, at decision time.
            params = self._params()
            obligation_declaration = self._outcome_obligation_declaration()

            # 1. The pack reads the record and describes the case.
            assessment = self.pack.assess(record, params)
            if isinstance(assessment, Rejection):
                return assessment.response

            # 2. Kernel: judge the episode. THE governance path, live.
            #
            # Additive on purpose. The pack keeps whatever scoring path it
            # acts on, and the kernel's verdict is recorded ALONGSIDE it
            # rather than replacing it -- swapping the live scoring path in
            # the same change that introduces the episode would make any
            # difference in behaviour impossible to attribute. The pack may
            # cross-check the two (annotate_kernel), and a disagreement
            # becomes an observable ledger fact rather than an assumption
            # nobody tested.
            kernel = {"judged": False}
            # The episode the ledger needs in order to verify the decision at
            # the conservation boundary. None until the pack builds one: a
            # call whose episode could not be built has nothing to verify,
            # and the ledger refuses to record it (see step 5).
            episode = None
            with tracer.start_as_current_span("kernel_judgment") as kernel_span:
                try:
                    assembly = self.pack.build_episode(assessment)
                    episode = assembly.episode
                    kernel_result = judge_episode(self.cassette, assembly.episode)
                    annotation = self.pack.annotate_kernel(assessment, kernel_result)
                    kernel = {
                        "judged": True,
                        "tier": kernel_result.tier,
                        "score": round(float(kernel_result.score), 6),
                    }
                    kernel.update(annotation.ledger_fields)
                    kernel.update({
                        "estimated_fields": list(estimated_fields(assembly.episode)),
                        "field_provenance": assembly.provenance,
                        "source_events": list(assembly.source_events),
                    })
                    kernel_span.set_attribute("kernel.tier", str(kernel_result.tier))
                    for name, value in annotation.span_attributes.items():
                        kernel_span.set_attribute(name, value)
                except (EpisodeIntegrityError, EventIntegrityError, KeyError) as e:
                    # A malformed episode is a real finding -- it means the
                    # ingest path produced something the kernel cannot accept.
                    # It does not take the call down, because the pack has a
                    # working scoring path that does not depend on it; but it
                    # is recorded, never silently dropped.
                    kernel = {"judged": False, "error": type(e).__name__,
                              "detail": str(e)[:400]}
                    kernel_span.set_attribute("kernel.judged", False)
                    mark_error(kernel_span, f"Kernel judgment unavailable: {e}")
                    logger.warning(
                        "kernel could not judge this call; legacy scoring stands",
                        extra={"extra_data": {"call_sid": record_id,
                                              "error": str(e)[:400]}})

            # 3. Pack side effects that follow the verdict (IVR: metrics and
            # intent learning). Not part of the governance decision.
            self.pack.on_assessed(assessment)

            # 4. Governance gate
            claude_decision = None

            # The pack decides, from the case it measured, whether this case
            # needs sign-off. The same measured value is what the governor is
            # handed (below) and what is written to the ledger, so a ledger row
            # can always reproduce its own decision.
            governed = assessment.governance_required
            root_span.set_attribute("call.governed", governed)
            for name, value in assessment.trace_attributes.items():
                root_span.set_attribute(name, value)

            if self.claude_decider and governed:
                with tracer.start_as_current_span("governance_decision") as gov_span:
                    try:
                        claude_decision = self.claude_breaker.call(
                            self.claude_decider.safety_check,
                            assessment.governor_action,
                            assessment.governor_facts,
                            # safety_check() fails closed by RETURNING a
                            # dict, never raising (see its own
                            # docstring) -- an exception-only breaker
                            # would never see these. Only the
                            # "transport_error:"-prefixed reasoning is a
                            # real API/network failure worth tripping
                            # the breaker on; a malformed-JSON or
                            # bad-shape response from a live, reachable
                            # API is not an outage and must not count.
                            is_failure=lambda r: isinstance(r, dict) and str(
                                r.get("reasoning", "")
                            ).startswith("transport_error:"),
                        )

                        # Loop guard: only meaningful for a response that
                        # actually reached and was parsed by a real model.
                        # model_identity is None on every fail-closed path
                        # (no client configured, JSON parse failure,
                        # transport error) -- see claude_governance_api.py,
                        # every one of those return dicts sets it to None
                        # explicitly. Skipping those avoids false-tripping
                        # the loop guard on their fixed, always-repeating
                        # reasoning text (e.g. "No API client configured"),
                        # which isn't a governor loop, it's the same
                        # non-decision every time by design.
                        if claude_decision.get("model_identity"):
                            loop_state = self.claude_loop_guard.process_lifecycle(
                                claude_decision.get("reasoning", "")
                            )
                            if loop_state == "BLOCKED_LOOP":
                                # A signal, not proof: record it and leave the
                                # decision alone.
                                self.loop_repeats_seen += 1
                                gov_span.set_attribute("decision.loop_repeat", True)
                                logger.warning(
                                    "governor reasoning repeats an earlier call's "
                                    "text verbatim; decision unchanged "
                                    f"(repeat #{self.loop_repeats_seen})"
                                )

                        gov_span.set_attribute("decision.approved", bool(claude_decision.get("safe")))
                    except Exception as e:
                        # CircuitOpenError (breaker OPEN) lands here too --
                        # same fail-closed shape as any other governor
                        # exception, no new branch needed.
                        print(f"Claude decision failed: {e}")
                        gov_span.record_exception(e)
                        mark_error(gov_span, f"Governor exception: {e}")
                        claude_decision = {
                            "safe": False,
                            "governed": False,
                            "parse_failed": True,
                            "reasoning": f"Governor exception: {str(e)}",
                            "confidence": 0.0
                        }

            elif governed:
                claude_decision = {
                    "safe": False,
                    "governed": False,
                    "parse_failed": False,
                    "reasoning": "Governance required but no governor configured",
                    "confidence": 0.0
                }

            # 5. Ledger: record the governance DECISION
            ledger_write_failed = False
            if self.ledger and claude_decision is not None:
                with tracer.start_as_current_span("ledger_write") as ledger_span:
                    try:
                        approved = bool(claude_decision.get("safe"))
                        root_span.set_attribute("call.approved", approved)
                        self.ledger_breaker.call(
                            self.ledger.append_decision,
                            GovernanceDecisionRecord(
                                action_type="governance_decision",
                                node=assessment.label,
                                cassette_version=params.cassette_version,
                                # The pack's domain facts, then the kernel
                                # verdict (EventV1: which of the numbers were
                                # measured and which were derived -- what an
                                # auditor asks for to know how much of a
                                # record is real).
                                input_data={**assessment.ledger_input,
                                            "kernel": kernel},
                                policy_parameters=params.snapshot(),
                                reasoning=claude_decision.get("reasoning", ""),
                                output={
                                    "approved": approved,
                                    "risk_level": claude_decision.get("risk_level"),
                                    "confidence": claude_decision.get("confidence"),
                                },
                                previous_value=assessment.value,
                                applied_value=assessment.value,
                                parameter_changed=False,
                                # Item 3: hash of the cassette DECISION CODE
                                # (scoring/intent logic), not just its
                                # parameters. Computed from the live cassette
                                # object so it enters the canonical hash. Closes
                                # F-H: a params-identical cassette with changed
                                # logic no longer hashes identically.
                                cassette_code_hash=_safe_code_hash(self.cassette),
                                # Item 5: the model the governor actually used
                                # (response.model), passed through from
                                # safety_check so it enters the canonical hash.
                                # None on any fail-closed governor path.
                                model_identity=claude_decision.get("model_identity"),
                                # Item 7: the authorizing service identity. This
                                # is a role/key NAME, never a raw key and never
                                # PII. Defaults to the harness service identity;
                                # override via config for distinct deployments.
                                authorized_by=self.config.get(
                                    "authorized_by", "harness:production"),
                                # OutcomeV1: the maturation rule in force at
                                # decision time, hashed in now and never
                                # edited. The obligation record points back at
                                # this row; this row points at nothing, which
                                # is what lets it close permanently.
                                outcome_obligation=obligation_declaration,
                                # Item 8 (2026-07-31): real usage-derived cost
                                # of this safety_check call, passed through
                                # from claude_governance_api unchanged -- see
                                # ai_cost_tracking.py. None on any fail-closed
                                # governor path (no API call, nothing to cost).
                                ai_cost=claude_decision.get("cost"),
                            ),
                            governance_params=params,
                            episode=episode,
                        )
                    except Exception as e:
                        # CircuitOpenError (breaker OPEN) lands here too --
                        # same ledger_write_failed=True / retryable shape
                        # sentinel_worker.py already fails correctly on.
                        # A decision that isn't durably recorded is not an
                        # audited decision. This used to be a print() with
                        # the function falling through to report
                        # governance_approved straight from claude_decision
                        # -- a caller could be told "approved" with no row
                        # to show for it. Confirmed live under concurrent
                        # duplicate-sid submissions at realistic governor
                        # latency: 3 of 4 approvals went unrecorded and
                        # were still reported as approved.
                        #
                        # This is returned in the response below, not
                        # raised: process() runs under
                        # ResilientHarness's retry_with_backoff, which
                        # retries ANY exception up to 3x and opens the
                        # circuit breaker after 5 failures -- raising here
                        # would re-invoke the governor on every retry for
                        # what is often a transient write failure, and
                        # could trip the breaker on a brief blip.
                        ledger_write_failed = True
                        logger.error(
                            "Ledger write failed for a governed decision -- "
                            "decision was NOT durably recorded",
                            extra={"extra_data": {
                                "call_sid": record_id,
                                "node": assessment.label,
                                "claude_safe": claude_decision.get("safe"),
                                "error": str(e),
                            }},
                        )
                        ledger_span.record_exception(e)
                        ledger_span.set_attribute("ledger_write.failed", True)
                        mark_error(ledger_span, f"Ledger write failed: {e}")

            # A case only counts as approved if the approval is both
            # granted AND durably recorded; either half missing means the
            # case was not successfully governed end-to-end.
            governance_approved = (
                bool(claude_decision.get("safe", False))
                if claude_decision is not None and not ledger_write_failed
                else False
            )
            governance_blocked = governed and (
                claude_decision is None or
                not claude_decision.get("safe", False) or
                ledger_write_failed
            )

            # Domain fields first, then the governance fields. The core's
            # fields win on a name clash, so a pack cannot overwrite them.
            response = dict(assessment.response_fields)
            response.update({
                "claude_safe": claude_decision.get("safe") if claude_decision else None,
                "governance_required": governed,
                "governance_approved": governance_approved,
                "governance_blocked": governance_blocked,
                "ledger_write_failed": ledger_write_failed,
                "governed": governed,
                "cassette_version": params.cassette_version,
            })
            return response
