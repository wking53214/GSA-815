# GSA-815 — Event-Sourced Governed State Transition: Improvement Investigation

**Status:** Investigation only. No production code was changed, committed, or refactored.
**Date:** 2026-08-27
**Scope:** Determine which ideas from the candidate event-sourcing / state-reduction /
governance-invariant design can improve GSA-815 *without* unnecessarily replacing existing
architecture.
**Evidence base:** GSA-815 source at `b1831fb`; sentinel_os kernel at `cdf5f52`
(`~/sentinel_os/sentinel_os/`, on `PYTHONPATH` per `DEPENDENCIES.md`); candidate at
`GSA-815/governance-control-plane/gov4_kernel`.

Every conclusion is tagged **FACT** (verified in source or by running it), **INFERENCE**
(reasoned from evidence, not directly demonstrated), **RECOMMENDATION**, or **UNKNOWN**.

---

## 1. Executive Summary

**The candidate architecture is already implemented in GSA-815's dependency stack — the
sentinel_os kernel — and implemented more carefully than the candidate.** The candidate
(`gov4_kernel`) is a 108-line incomplete skeleton that cannot execute. GSA-815 itself
contains **no** event store, reducer, state-transition module, or hash chain of its own
(**FACT** — zero matches for `event_store`, `state_transition`, `reducer`, `hash_chain`,
`event_hash`, `sequence_no` across GSA-815's own `.py` files).

**The candidate's core pattern — "projected state → invariants → accept/reject" — already
exists in GSA-815's live path and is deliberately non-binding.** `process_call` runs the
kernel's `judge_episode` on every call, compares its verdict to the legacy scorer, records
`agrees_with_legacy_scoring`, logs a `warning` on disagreement, and then **acts on the
legacy score anyway** (**FACT** — `production_harness.py:458-498`; the comment at `:460-468`
says so explicitly). A governed transition evaluator that never bites is monitoring, not
governance. This is *why* the high-value move is to make that evaluator's inputs durable
and reconstructible (decision C) rather than to build a new gateway (decision E) — the
gateway is already there, it just runs in shadow mode.

What GSA-815 *does* have:

- **A governed transition boundary already in production**, non-authoritatively (above).
- **A production hash chain, concurrency control, provenance, and immutability** — all in
  the shared kernel ledger `governance/ledger_postgres.py` (`pg_advisory_xact_lock`,
  `UNIQUE(current_hash)`, DB immutability triggers, twin witness, and — since sentinel_os
  PR #28 — keyed HMAC attestation of `authorized_by`). GSA-815 writes to it via
  `PostgreSQLLedger.append_decision` (**FACT**).
- **A working replay/verify mechanism for the simulator only**: `LogRotationManager`
  (chunk-file + atomic manifest hash chain, real `verify(mode="strict")`), used by
  `iceberg_complete_simulator.py:158,179` (**FACT**).

**The one genuine gap the candidate points at:** the observation events that feed a
governance decision are **built in memory and discarded**. `_assemble_live_episode`
constructs `EventV1` objects, `assemble_episode` reduces them to an `Episode`,
`judge_episode` produces a verdict, and only a *summary* (`tier`, `score`,
`agrees_with_legacy_scoring`, `estimated_fields`, `field_provenance`, and
`source_events` — a list of **event IDs, not event bodies**) is embedded in one
`governance_decision` row's `input_data["kernel"]` (**FACT** —
`production_harness.py:472-486, 641`). **You cannot independently reconstruct or re-judge a
decision from its source observations**, because the source observations are not persisted
anywhere.

**Second finding, blocking (RESOLVED 2026-08-27, after this investigation):** at
investigation time GSA-815's production spine **did not import** — three owed modules
(`observe_perceive_core`, `sentinel_core`, `metrics_prometheus`, plus `grafana_dashboard`)
were missing, and GSA-815's own `governance/__init__.py` shadowed the kernel's `governance/`
package so `governance.ledger_postgres` could not resolve. Both were fixed: the four
modules were copied in (byte-identical to source — see `DEPENDENCIES.md`) and
`governance/__init__.py` was removed. `production_harness`, `iceberg_complete_simulator`,
and `api_server_resilient` now import, and `pytest Tests/` went from **55 passed / 3
errored files** to **60 passed / 3 errored tests** (the remaining 3 are `test_real_*`
integration tests needing a live Postgres + Claude API — environment-gated, not
code-blocked). The rest of this section describes the state at investigation time.

**Final decision (§32): C — Adopt a governed event / transition layer**, scoped narrowly
to *persisting and replaying the observation-event stream on the existing kernel ledger*,
reusing the existing `assemble_episode` reducer and `judge_episode` evaluator. **Not**
partial or full event sourcing. **Not** a new event store. **Not** a new transition
gateway. **Not** event-sourcing of learning/queue/RL state. Prerequisite: fix the
dependency story (Phase 0).

---

## 2. Actual GSA-815 Architecture

**FACT.** GSA-815 is "the IVR/Iceberg side, extracted out of `sentinel_os` … not meant to
run standalone" (`DEPENDENCIES.md`). It is a thin telephony-domain application layer on top
of the sentinel_os kernel, which it consumes by `PYTHONPATH` rather than vendoring.

### 2.1 The wired production path (small)

| File | Symbol | Role | Runnable in this checkout? |
|---|---|---|---|
| `production_harness.py` | `IcebergProductionHarness` | End-to-end call pipeline: dedup → parse → friction → emotion → intent → **legacy score + kernel `judge_episode` cross-check** → Claude governor → ledger write | **No** — imports `metrics_prometheus`, `sentinel_core`, `observe_perceive_core` (all missing) |
| `twilio_log_ingestion.py` | `TwilioLogParser`, `IcebergJourney` | Parse Twilio call logs into a journey; stamp route/wait **provenance** (`PROVENANCE_VERIFIED` when `ivr_events` present, `PROVENANCE_ESTIMATED` otherwise) | **No** — imports `cassette_schema` (kernel, not on default path) |
| `claude_governance_api.py` | `ClaudeGovernanceDecider` | Subclass of kernel `governance_decider`; `safety_check()` returns a fail-closed dict, never raises | Depends on kernel |
| `queue_staffing_bayes_integration.py` | `BayesianIntentEngine`, `StaffingCoordinator`, `QueueDynamics` | Operational-response layer: Erlang-C staffing math + Bayesian P(resolution\|intent) with optional Redis persistence | Imports `redis`, kernel `circuit_breaker` |
| `Engines/simple_rl_trainer.py` | `SimpleRLTrainer` | Policy-gradient RL over a 10-dim state; seeded numpy RNG | Imports `array_ops` (kernel) |
| `iceberg_complete_simulator.py` | `IcebergCompleteSimulator` | Zero-setup demo: batch → `detect_drift` → `heal` → `LogRotationManager.verify` | **No** — also imports the missing `observe_perceive_core` (line 11); compiles, does not run in this checkout |
| `governance/perceive_gate.py` | `PerceiveGate` | `require_perceive_approval` / `gate_operation` — PERCEIVE approval boundary | Standalone |
| `conservation/acceptance.py`, `conservation/return_gateway.py` | `GSA815ConservationGate`, return gateway | Validate/emit Conservation Receipts at the repo's artifact in/out boundary | Standalone |

### 2.2 The separate MARL/PPO simulation subsystem

**FACT.** `Sim/Simulator.py` (`Simulator.step`), `Sim/cluster_runner.py` (`ClusterRunner`,
`ThreadPoolExecutor`, 8 workers), `Model/Build_Graph.py` (`RoutingGraph`), `Domain/*`
(`CallerState`, `QueueState`, `Emotion`, `Intent`), `Latent/LatentPayload.py`. This is a
distinct, self-contained simulation stack — **it does not import, and is not imported by,
`iceberg_complete_simulator.py` or `production_harness.py`.** Its docstrings assert
"deterministic replay", "Replay-Safety: Identical caller + queues -> identical step
output".

**FACT.** `Simulator.step(caller: Dict[str, Any], start_node)` (`Simulator.py:67-124`)
takes a **dict**, not a `Domain/CallerState` object, and returns a telemetry packet. But
`Sim/README.md`'s claim that it does so "rather than mutating the caller in place" is only
partly true: step 6 calls `_evolve_latent_state(caller)` which mutates the attached latent
payload (`payload.update_after_step(dynamic)`, `Simulator.py:60-61, 99`), and the Bayes
update reads and may mutate `caller["posterior"]` (`:89-92`). **Discrepancy (§31):** the
README overstates the no-mutation guarantee.

**UNKNOWN.** Whether `Simulator`'s "deterministic replay" docstring claims actually hold —
not verified in this investigation, and no evidence either way.

**FACT.** `Simulator` has an optional `governance: Any | None = None` arbiter; when `None`,
`governance.enforce(...)` is skipped entirely (`Simulator.py:46-48`) — a bypass by
omission (§9 #7).

### 2.3 Prototype / reference material (not wired)

**FACT.** Large standalone files imported by nobody except their own test harness:
`GSA_Governance_Operating_Core_Enterprise.py` (4,987 lines; imported only by
`gsa-governance-core/test_harness.py`), `GSA.py` (4,985 lines; zero importers), `GSA/GSA.py`,
`GSA-2/artifact_*.py` (15 files, 6 of them 0 bytes),
`gsa-*-interlock-wrapper*.py` (several), `gsa-master-kernel-base-flattened.py` (0 bytes).
These follow the ecosystem's aspirational-README pattern (see the repo owner's memory
`project_ecosystem_readme_implementation_gap`) and PR #1 already flagged
`gsa-governance-core/README.md`. **They are out of scope** for this investigation — they
are not GSA-815's architecture, they are drafts beside it.

### 2.4 The candidate

**FACT.** `governance-control-plane/gov4_kernel` — 108 lines, **no `.py` extension** (not
importable as a module). Contains `canonical()`, `normalize(precision=10)`, `class WAL`,
`class GovernanceCoreReducer.apply(context, event)`, `class ExecutionRuntime`. **References
six undefined names**: `NormalizedEvent`, `EventStore`, `Reducer`, `SnapshotPolicy`,
`StateSnapshot`, `EveryNEventsSnapshot`. `ExecutionRuntime.__init__` defaults
`self._snapshot_policy = snapshot_policy or EveryNEventsSnapshot(50)` — `EveryNEventsSnapshot`
is undefined, so the class **cannot be instantiated with default arguments**.
`GOV4_kernel.README.md` is a **byte-identical copy** of `gov4_kernel` (both 4,391 bytes) —
it is not documentation. **The candidate as it exists in GSA-815 cannot execute.**

---

## 3. Current State Model

For every state domain: **who creates / modifies / consumes it, is it persisted /
reproducible / deterministic / governed / provenanced / replayable / reconstructable /
independently verifiable.**

| Domain | Where | Persisted | Reproducible | Deterministic | Governed | Provenance | Replayable | Independently verifiable |
|---|---|---|---|---|---|---|---|---|
| **Authoritative governance state** (the decision record) | kernel `ledger_postgres` `ledger_entries` table, written by `PostgreSQLLedger.append_decision` from `production_harness.py:621` | **Yes** (Postgres, append-only, immutability triggers) | Yes (row is immutable) | N/A (a record, not a computation) | **Yes** — `verify_chain` + twin witness + HMAC `authorized_by` | **Yes** — `authorized_by`, `model_identity`, `cassette_code_hash`, `policy_parameters`, `cassette_version` on the row | Partial — chain re-verify yes; decision *recompute* no (inputs not stored) | **Yes** for tamper (hash chain); **No** for "was this the right verdict given the observations" |
| **Observation events** (`EventV1` route/wait/emotion/call_ended) | built in memory in `_assemble_live_episode` (`production_harness.py:311-346`) | **No** — discarded after `judge_episode` | No | Mostly (see §14) | Judged, not gated | **Yes** — `PROVENANCE_VERIFIED/ESTIMATED` + `method` + `source` per event | **No** — not stored | **No** |
| **Episode / projected verdict** | `assemble_episode` → `judge_episode` (`production_harness.py:472-486`) | Only a summary dict in `input_data["kernel"]` | No | Yes given events | Non-authoritative cross-check | Inherits event provenance (`field_provenance`) | **No** | **No** |
| **Legacy quality score** (authoritative for action) | `sentinel_core.score_outcome_quality` (`production_harness.py:453`) | Only `quality_tier` string on the row | No | Yes | This is what the harness acts on | None beyond the tier string | No | No |
| **Cassette / policy state** | `CassetteLoader().load_cassette`; re-read every call via `_params()` (`production_harness.py:226-231`) | Bound into ledger (`bind_cassette_version`, content hash + code hash) | Yes | Yes | **Yes** — `require_cassette_binding=True` fail-closed | `cassette_version` + `cassette_hash` + `cassette_code_hash` | N/A | **Yes** — hash comparison |
| **Queue state** | `StaffingCoordinator.current_staffing` dict; `QueueDynamics.erlang_c_cache` dict | **No** — in-process | No | Yes (pure math) | No | None | No | No |
| **Learning state — Bayes** | `BayesianIntentEngine.intent_stats` (in-mem EMA) + optional Redis per-intent hash | Redis only (best-effort) | **No** — cross-worker EMA merge is order-dependent by design (`queue_staffing_bayes_integration.py:290-299`) | No | **No** — `observe_outcome` has no gate, no provenance, no ledger entry | **None** | No | No |
| **Learning state — RL** | `SimpleRLTrainer.policy_weights` / `value_weights` (numpy, in-mem) | **No** | Yes from `seed` (`simple_rl_trainer.py:15-33` — seed is now live; a prior bug that made it dead is fixed) | Yes given seed | No | None | No (weights not saved) | No |
| **Simulated caller/queue state** (MARL) | `Sim/Simulator.step` takes a `caller` dict, returns a telemetry packet; mutates the attached latent payload (`_evolve_latent_state`) and `caller["posterior"]` in place | No | Claimed yes (docstrings) | **UNKNOWN** — claimed, not verified | Optional `governance.enforce`, skipped if `governance` unset | `CallerState.snapshot()` exists but carries no origin/actor | Claimed, unverified | No |
| **Simulator drift/heal ledger** | `LogRotationManager(LocalDiskAdapter("/tmp/iceberg_final"), seed="815")` | **Yes** — local disk chunks + manifest | Yes | Yes | Heal recommendations written through it | Manifest head hash | **Yes** — `verify(mode="strict")` | **Yes** — `_recompute_head` |
| **Telemetry / metrics** | `PrometheusMetrics` (missing module); `metrics.record_call` (`production_harness.py:515`) | Scrape-time only | No | No | No | None | No | No |
| **Dedup / idempotency state** | `ledger.sid_exists(call_sid)` (`production_harness.py:391`) + `idx_unique_call_sid` UNIQUE index | Yes (in the ledger) | Yes | Yes | Yes — hard reject | call_sid on row | Yes | Yes |

**FACT:** the only authoritative, persisted, governed, independently-verifiable state in
GSA-815 is what lands in the kernel ledger. Everything else is transient.

### State-flow diagram (as-built)

```
Twilio record
    │
    ▼
TwilioLogParser.parse_call_log ──► IcebergJourney  (route/wait PROVENANCE stamped here)
    │
    ▼
ObserveCore friction + emotion  (in-memory, ephemeral)
    │
    ├─────────────────────────────────────────────┐
    ▼                                             ▼
SentinelCore.score_outcome_quality        _assemble_live_episode
  (legacy quality_score)                    → [EventV1, EventV1, ...]   ← BUILT IN MEMORY
    │  ← ACTED ON                                 │
    │                                     assemble_episode  (the reducer)
    │                                             │
    │                                     judge_episode  (projected verdict)
    │                                             │
    │                            kernel = {tier, score, agrees_with_legacy,
    │                                       estimated_fields, field_provenance,
    │                                       source_events: [IDs only]}
    │                                             │
    │         ┌───────────────────────────────────┘   EventV1 objects DISCARDED here
    ▼         ▼
friction_count >= governance_trigger ?  ──no──► (no governance, no row)
    │ yes
    ▼
ClaudeGovernanceDecider.safety_check  (circuit-breakered, fail-closed dict)
    │
    ▼
PostgreSQLLedger.append_decision(GovernanceDecisionRecord(
    input_data={... "kernel": <summary dict>},
    policy_parameters=..., cassette_code_hash=..., model_identity=...,
    authorized_by="harness:production", ...))
    │
    ▼   pg_advisory_xact_lock('ledger_entries')  → global hash chain  → UNIQUE(current_hash)
    │   → DB immutability triggers  → twin witness recompute
    ▼
governance_approved = claude_safe AND ledger_write_succeeded     (fail-closed, §9)
```

---

## 4. Current Event Model

**FACT.** GSA-815 has **no native event model**. It borrows the kernel's:

- `event_v1.EventV1` — frozen dataclass: `event_id`, `episode_id`, `domain`, `kind`,
  `occurred_at`, `observed_at`, `source`, `provenance`
  (`PROVENANCE_VERIFIED` / `PROVENANCE_ATTESTED` / `PROVENANCE_ESTIMATED`), `method`
  (required iff `ESTIMATED`, forbidden iff `VERIFIED`), `fields`, `detail`.
  `make_event` / `validate_event` enforce the integrity rules.
- `event_v1.assemble_episode(...) -> EpisodeAssembly` — deterministic fold of an event
  list into `requested` / `actual` / `attributes` / provenance maps. **This is a reducer**
  (`state=∅ + events → projected episode`), it simply is not labelled one.
- `episode.judge_episode` / `validate_episode` — invariant checks
  (reason-on-any-mismatch, never-trust-actor-report) then a verdict.

Operations in GSA-815 and how they are currently represented:

| Operation | Current representation |
|---|---|
| Route decision | `IcebergJourney.journey` list + `route_provenance` field; transiently → an `EventV1` `route_selected` in `_assemble_live_episode` |
| Wait observation | `IcebergJourney.wait_times` dict; transiently → `EventV1` `wait_observed` |
| Emotion inference | `EmotionalState` object; transiently → `EventV1` `emotion_inferred` (always `ESTIMATED` + `method`) |
| Call end | Twilio record fields; transiently → `EventV1` `call_ended` (`VERIFIED`) |
| Governance decision | **`GovernanceDecisionRecord` → a persisted ledger row** (the only durable "event") |
| Escalation | Not modelled as an event anywhere in wired code |
| Model output | Fields inside `claude_decision` dict → folded into the ledger row |
| Adaptive / drift / heal update | `heal(...)` writes recommendations through `LogRotationManager` (simulator) or `InMemoryParameterStore` |
| Bayes update | In-place mutation of `intent_stats` + Redis `hincrby`; **no event** |
| Simulation step | `Simulator.step` returns a telemetry packet; queue/bayes/latent mutated in place |
| Policy change | `swap_cassette` + `bind_cassette_version` ledger row |

**Minimum useful event boundary (RECOMMENDATION):** the **observation events already built
by `_assemble_live_episode`** and nothing else. They are the inputs a re-judgment needs,
they already carry provenance, and they are already constructed — they are just thrown
away. Queue math, Bayes, RL, and telemetry should **not** become events (see §8, §14).

---

## 5. Candidate Architecture — What It Is and Whether It Fits

**FACT (completeness).** `gov4_kernel` is non-executable (§2.4). Taking it as pseudocode:

| Candidate component | What it does | GSA-815 already has |
|---|---|---|
| `canonical(obj)` | `json.dumps(sort_keys, separators, default=str)` | **Yes** — kernel `canonical_fields.py` uses the identical idiom |
| `normalize(obj, precision=10)` | round floats to 10 dp before hashing | **No** — kernel does not round floats; minor gap (§7) |
| `WAL.append` | line-buffered append of `canonical(record)`, `flush()` each write | **Yes, stronger** — `ledger_postgres` (DB durability) and `log_rotation_v1` (fsync'd chunk + atomic manifest) |
| `GovernanceCoreReducer.apply(context, event)` | dict-merge, `event_type` branches: `telemetry_update`, `escalation`, `status_change`, `hiring_decision` (→ `ISOLATE` sets `CRITICAL`) | **Yes, better** — `assemble_episode`; and the candidate's branches are a **different domain** (hiring/isolation, not IVR) |
| `ExecutionRuntime.materialize_state(entity_id)` | snapshot + `events_since` + incremental reduce + `EveryNEventsSnapshot(50)` + `MappingProxyType` | **Partly** — `LogRotationManager._resume_state` / `_recompute_head` does snapshot-resume + incremental replay for the simulator ledger |
| `StateSnapshot` (undefined) | entity_id, last_sequence_no, context | `LogRotationManager` manifest is the working analogue |
| `EventStore` (undefined) | implied in-memory | **N/A** — GSA-815's store is Postgres |
| `SnapshotPolicy` / `EveryNEventsSnapshot` (undefined) | every-N | `LogRotationManager` rotates by chunk size |
| `Provenance(actor_id, policy_id, justification)` | flat 3-field | **Yes, richer** — `EventV1.provenance` + `method` + `source`; ledger row `authorized_by` (HMAC) + `model_identity` + `cassette_code_hash` |

**INFERENCE:** the candidate is a generic, unfinished event-sourcing tutorial skeleton
with one domain-specific reducer copied in from a *different* system (hiring/isolation
governance, per the `hiring_decision` / `ISOLATE` branch and the sibling
`governance-control-plane` origin noted in `INTEGRATION.md`). It contributes **one** idea
GSA-815 doesn't already have better: `normalize(precision=10)` float canonicalization —
and even that is a kernel concern, not GSA-815's.

---

## 6. Existing Capability Overlap

| Candidate capability | GSA-815 / kernel equivalent | Verdict |
|---|---|---|
| Canonical SHA-256 hashing | `canonical_fields.py`, `ledger_postgres` per-row `current_hash` over canonical entry | **Covered, stronger** |
| Hash chaining (`previous_hash → event_hash`) | `ledger_postgres` global chain: each row's hash includes `previous_hash`; `verify_chain` walks it; twin recomputes independently | **Covered, stronger** (chain is over *governance decisions*, not raw events) |
| Entity-partitioned event streams | `ledger_entries` is a single global chain, not per-entity; `episode_id` groups `EventV1`s in memory | **Partial** — global not partitioned; see §11 |
| Reducer (`state + event → next`) | `assemble_episode` (events → episode); `heal` (breach + store → recommendations) | **Covered** |
| Governance invariants on projected state | `validate_episode` (reason-on-mismatch, never-trust-actor); `judge_episode` | **Covered** — but non-authoritative in the live path (§9) |
| Projected-state validation before commit | `judge_episode` runs before the ledger write, but its verdict is not the gate | **Partial** |
| Replay | `LogRotationManager.verify` + `_recompute_head` (simulator); `verify_chain` (production, tamper only) | **Partial** — no decision *recompute* in production |
| Snapshot policy | `LogRotationManager` chunk rotation + manifest | **Covered for the sim**, absent for production |
| Provenance | `EventV1` provenance model + ledger provenance fields | **Covered, stronger** |
| WAL / durability | Postgres + fsync'd manifest | **Covered, stronger** |
| Concurrency control | `pg_advisory_xact_lock('ledger_entries')` on every append + `UNIQUE(current_hash)` + `idx_unique_call_sid` | **Covered, stronger** (§11) |

---

## 7. Hash / Integrity Analysis

**FACT — what exists.**
- `ledger_postgres`: every row's `current_hash = sha256(canonical(entry_including_previous_hash))`.
  `UNIQUE(current_hash)` constraint. `verify_chain(mode=...)` walks the chain. An
  independent "twin" recomputes every row (`twin_custody.SHIPPED_COLUMNS`,
  `recompute_current_hash`). DB triggers block `UPDATE`/`DELETE`. As of sentinel_os PR #28,
  `authorized_by_sig` (keyed HMAC) is one of the `OPTIONAL_HASHED_FIELDS` and rides in the
  same chain.
- `log_rotation_v1`: per-chunk hash, manifest carries the head hash, `verify()` recomputes.
- `cassette_forensics.compute_cassette_hash` / `compute_cassette_code_hash`: content + code
  hashes of the governing policy, folded into the row (`production_harness.py:659`).

**FACT — candidate weaknesses (from §7 checklist), and whether GSA-815 shares them:**

| Weakness | Candidate | GSA-815 / kernel |
|---|---|---|
| Hash not stored inside event | `WAL` writes the record; hash computed at read | **Not shared** — `current_hash` is a stored column |
| Mutable payloads | dicts, no freeze | **Not shared** — `EventV1` is frozen; ledger rows immutable by trigger |
| Canonicalization limitations | `default=str` only | **Shared (minor)** — kernel also uses `default=str`; non-JSON types stringify unpredictably if ever introduced |
| Floating-point representation | `normalize(precision=10)` present | **Shared** — kernel does **not** round floats before hashing. **INFERENCE:** low risk today (Python `repr(float)` is round-trip stable and the 189 passing kernel tests hash floats consistently), but a float that differs in the last ULP between writer and verifier would break `verify_chain`. Worth a kernel-side `normalize`. |
| Timestamp handling | raw floats | **Shared** — `occurred_at`/`observed_at` are floats; same ULP caveat |
| Schema evolution | none | **Partially shared** — `EventV1` has no `schema_version`; ledger `record_kind` acts as a discriminator; `OPTIONAL_HASHED_FIELDS` gives forward-compatible field addition (§18) |
| Concurrency | in-memory, racy | **Not shared** — advisory lock serializes appends (§11) |
| Persistence | in-memory | **Not shared** — Postgres |
| Chain truncation | undetectable | **Partially shared** — `verify_chain` detects internal tampering but a truncated *tail* (drop the last N rows) is only caught by the twin's independent head or an external height check; **UNKNOWN** whether GSA-815 exports a monotonic height monitor |
| Chain verification | absent | **Not shared** — `verify_chain` + twin |

**RECOMMENDATION:** the production-grade design for GSA-815 already exists — it *is*
`ledger_postgres`. The only integrity improvement worth making is **kernel-side float
normalization in `canonical_fields`** (a hardening, not a new capability), and it belongs
to the kernel repo, not GSA-815.

**Do not claim** GSA-815 provides cryptographic non-repudiation. The HMAC attestation
proves *"the holder of the service key wrote this row and the `authorized_by` string is
unchanged"* — nothing about whether the named party had authority (per the PR #28 honesty
scope).

---

## 8. Reducer Analysis

**FACT.** GSA-815 has an implicit reducer: `assemble_episode` (kernel), a pure fold of an
`EventV1` list into an `EpisodeAssembly`. It is deterministic given its input list.

**RECOMMENDATION — where `state + event → next state` should become a formal contract:**

| Domain | Formal reducer appropriate? | Why |
|---|---|---|
| **Episode assembly from observation events** | **Yes** — already is one; make it the contract | Pure, deterministic, replay = re-fold; this is the §25 recommendation |
| Drift/heal parameter store | Maybe | `heal` is already `(breaches, store, band) → recommendations`; store mutation is the side effect. Could be expressed as reduce, low value |
| Bayes belief update | **No** | Cross-worker merge is order-dependent *by design* (`get_posterior` overwrites local from Redis running mean); an EMA cannot be correctly resumed/merged (the code says so at `:290-297`). Forcing a reducer contract would misrepresent it as replayable |
| RL weights | **No** | Gradient updates are path-dependent on minibatch order; "replay" only means "re-run from seed", which already works |
| Queue Erlang-C | **No** | Pure function of inputs, no accumulated state worth folding; `erlang_c_cache` is a memo, not state |
| Simulator step | Partial | `Simulator.step` already returns a packet rather than mutating the caller; but queue/latent mutation inside is not folded |

**Domains where reducer-based reconstruction is *inappropriate* (FACT-backed):** anything
touching Redis running means, numpy RNG streams across process boundaries, wall-clock
timestamps as data, or `ThreadPoolExecutor` result ordering (`cluster_runner.py`).

---

## 9. Governance Boundary Analysis — Bypass Enumeration

**This is the highest-value section.** Does GSA-815 validate governance **before** or
**after** state mutation?

**FACT: the authoritative state mutation (the ledger row) is gated correctly.** In
`process_call` the order is: friction gate → governor `safety_check` → `append_decision`.
The row is written *after* the decision, and `governance_approved` is `True` **only if**
the governor said safe **and** the write succeeded (`production_harness.py:723-730`). The
docstring at `:686-698` records that this used to be broken ("3 of 4 approvals went
unrecorded and were still reported as approved") and is now fail-closed.

**FACT: the kernel's episode judgment — the candidate-style "projected state → invariants →
accept/reject" — is NOT authoritative.** `process_call` runs `judge_episode` (`:475`) but
the comment at `:460-468` is explicit: *"quality_score above stays the value this harness
acts on, and the kernel's verdict is recorded ALONGSIDE it rather than replacing it."* The
governed-transition pattern the candidate proposes **already exists here and is
deliberately shadow-mode.**

### Every place governance can be bypassed

| # | Path | Mechanism | Evidence | Severity |
|---|---|---|---|---|
| 1 | **Kernel judgment degrades to advisory on malformed input** | `except (EpisodeIntegrityError, EventIntegrityError, KeyError)` → `kernel={"judged":False}`, "legacy scoring stands" | `production_harness.py:499-512` | Low — legacy path is itself a governance path; but a caller who can force a malformed episode disables the cross-check |
| 2 | **`judge_episode` disagreement is logged, not enforced** | `if not agrees: logger.warning(...)` then proceeds on legacy score | `production_harness.py:489-498` | **Medium** — a real divergence between the two governance evaluators produces a warning line and an approved call |
| 3 | **`require_cassette_binding=False` escape** | constructor flag; "Set False only for local/dev/simulator callers" | `production_harness.py:66, 85` | Low in prod (`sentinel_worker.py` has no override) — but any direct `IcebergProductionHarness(config, require_cassette_binding=False)` governs with an unbound cassette |
| 4 | **No-ledger path** | `if self.ledger and claude_decision is not None:` — no ledger ⇒ no row | `production_harness.py:616` | Low — `_init_optional_components` raises if `require_cassette_binding` and no ledger (`:168-182`); reachable only with #3 |
| 5 | **Ungoverned calls below threshold** | `governed = friction_count >= governance_trigger`; below it, `claude_decision=None`, no row | `production_harness.py:560, 616` | By design — but the *episode is still not persisted*, so a later "why wasn't this call governed" question has no evidence |
| 6 | **Bayes / RL / staffing updates are entirely ungoverned** | `observe_outcome`, `update_weights`, `current_staffing[...]=` — no gate, no provenance, no ledger | `queue_staffing_bayes_integration.py:238`, `simple_rl_trainer.py:85` | **Medium** — learning state that influences future routing has no authorization or audit trail |
| 7 | **Simulator `governance` arbiter optional** | `Simulator(governance=None)` ⇒ `_apply_aegis_loop` returns routing unchanged | `Sim/Simulator.py:36, 46-48` | Low (sim only) — but tests/demos run "governed" pipelines with no governor |
| 8 | **Concurrent worker double-commit** | see §11 | — | Mitigated by advisory lock + `idx_unique_call_sid` |
| 9 | **Retry path re-invokes governor** | `process_call` under `ResilientHarness.retry_with_backoff` retries any exception 3× | `production_harness.py:699-707` | Low — ledger write failure is returned not raised specifically to avoid governor re-invocation; dedup catches re-processed sids |
| 10 | **Direct `append_decision` call** | anything with a `PostgreSQLLedger` handle can append a row without going through `process_call` | kernel API | Low — the advisory lock and chain still apply; the row just may not reflect a real call |

**RECOMMENDATION.** GSA-815 does **not** need a *new* mandatory state-transition gateway —
it has one for the authoritative state (the ledger append path). What it needs is:
1. **Persist the observation events** so bypasses #1, #2, #5 leave evidence.
2. **Decide whether `judge_episode` disagreement (#2) should escalate** rather than warn —
   that is a policy question for the repo owner, not an architecture gap.
3. Treat #6 (ungoverned learning state) as a **known, accepted limitation** to document,
   not necessarily to fix — event-sourcing Redis EMAs is not viable (§8, §14).

---

## 10. Conservation / Authority Analysis

**FACT.** GSA-815 has a conservation boundary: `GSA815ConservationGate.validate_artifact_receipt`
(`conservation/acceptance.py`) refuses artifacts without a valid Conservation Receipt
(`artifact_id`, `verification_status`, `kernel_version`, content hash check);
`return_gateway.py` is the exit. This is an **artifact in/out boundary**, not a
state-transition invariant engine.

**FACT.** The kernel's `EventV1` already encodes the epistemic distinctions the candidate's
§10 asks about:
- `PROVENANCE_VERIFIED` vs `PROVENANCE_ESTIMATED` (with mandatory `method`) —
  inferred-vs-observed is a **structural invariant**: `validate_event` rejects a `VERIFIED`
  event that carries a `method` and an `ESTIMATED` event that doesn't
  (`_assemble_live_episode` comments at `:297-310` show the harness working around exactly
  this rule).
- `estimated_fields(episode)` surfaces which numbers were derived — written into the
  ledger row (`production_harness.py:483`).
- `authorized_by` + HMAC sig — the human/service authority claim, now attested.

**INFERENCE:** the transitions the candidate worries about (`inferred → asserted`,
`AI-generated → human-authoritative`, `unauthorized → authorized`, `unverified → verified`)
are **not currently possible to make silently** in the wired path, because provenance
travels *with* each `EventV1` and is folded into the immutable row. The risk surface is:
- A future reducer that **drops** provenance when folding events into projected state.
- The **legacy `quality_score`** path, which carries no provenance at all — it is a bare
  tier string. If it ever became the sole input to a downstream authoritative action, the
  provenance chain would break there.

**RECOMMENDATION (formal invariant, low cost):** if the observation-event layer is built
(§25), add one property test: *the projected episode's provenance map is never "stronger"
than the weakest contributing event* (no `ESTIMATED` input yields a `VERIFIED` projected
field). Do **not** invent authority/classification machinery GSA-815 has no use for.

---

## 11. Concurrency Analysis — HIGH PRIORITY

**Hostile analysis of the candidate runtime.** `ExecutionRuntime.materialize_state`:
reads `self._snapshots.get(entity_id, ...)`, calls `self._store.events_since(...)`, folds,
conditionally writes `self._snapshots[entity_id]`. **FACT:** no lock anywhere. The classic
race applies verbatim:

```
Worker A: events_since(E, 10) → [e11]        Worker B: events_since(E, 10) → [e11]
Worker A: append e11 (seq 11)               Worker B: append e11 (seq 11)   ← collision
```

The candidate has **no** unique constraint on `(entity_id, sequence_no)`, no optimistic
`WHERE last_sequence_no = ?`, no advisory lock. **Adopting the candidate's runtime would be
a regression.**

**FACT — GSA-815's actual concurrency model:**
- **Production ledger writes are fully serialized.** Every `append_decision` /
  `bind_cassette_version` / `record_*` path in `ledger_postgres.py` executes
  `SELECT pg_advisory_xact_lock(hashtext('ledger_entries'))` first (lines 699, 820, 945,
  1094, 1204, 1311, 1396, 1494, 1707, 2046, 2231). Two workers appending concurrently
  block on the lock; the second reads the *committed* head. `UNIQUE(current_hash)` is the
  backstop.
- **Duplicate calls** are rejected by `sid_exists` pre-check (`production_harness.py:391`)
  **and** `CREATE UNIQUE INDEX idx_unique_call_sid` (`ledger_postgres.py:436`) — belt and
  suspenders.
- **`ResilientHarness.retry_with_backoff`** retries any exception 3×; ledger-write failure
  is *returned, not raised* specifically so a retry does not re-invoke the governor
  (`production_harness.py:699-707`).
- **`cluster_runner.ClusterRunner`** runs `Simulator.step` across a `ThreadPoolExecutor`
  (8 workers). **FACT:** `ClusterRunner` "holds no state beyond its simulator/telemetry
  handles" (README), but `Simulator` mutates shared `queues` dicts and the `bayes` engine
  concurrently with **no lock**. This is sim-only and results are collected per-future, but
  a shared `QueueState` mutated by 8 threads is a real data race. **INFERENCE:** tolerated
  because the sim is a demo, not a correctness oracle.
- **Bayes Redis path:** `_persist_observation` uses a `pipe = self._redis.pipeline()` with
  `hincrby`/`hincrbyfloat` — redis-py pipelines default to `MULTI/EXEC`, so the three
  increments are atomic *as a unit*, but `get_posterior` then does a non-atomic
  read-and-overwrite of local stats from the Redis running mean
  (`queue_staffing_bayes_integration.py:281-299`). Concurrent workers converge but never
  agree exactly at a point in time. **FACT** and **by design.**

**RECOMMENDATION — correct serialization strategy:** GSA-815 already has it for the state
that matters (advisory lock + unique index). If observation events are persisted (§25),
write them **inside the same transaction and under the same advisory lock** as the
`governance_decision` row they belong to — one lock acquisition, one commit, events +
decision atomic. Do **not** introduce a second lock domain or a per-entity sequence
counter; the global chain already totally-orders everything.

---

## 12. Provisional Event Problem

**FACT.** The candidate's pattern (validate `event_id = "PROVISIONAL"`, then commit a
different event with a generated UUID) — **GSA-815 does not have this problem.**
`make_event` assigns the real `event_id` at construction (`_assemble_live_episode` passes
explicit stable ids: `f"{base}:route"`, `f"{base}:wait:{node}"`, `f"{base}:emotion"`,
`f"{base}:ended"` — `production_harness.py:313-345`). The event that is validated **is** the
event that would be persisted. `EventV1` is frozen, so it cannot be mutated between
validation and commit.

**RECOMMENDATION:** keep the existing "assign identity at creation" model. If events are
persisted, the `event_id` should be `f"{episode_id}:{kind}[:{discriminator}]"` — stable,
derivable, and naturally unique per episode. **Do not** adopt a PROVISIONAL→UUID lifecycle;
it is strictly weaker.

---

## 13. Replay / Snapshot Analysis

**FACT — what replays today:**
- `LogRotationManager.verify(mode="strict")` — recomputes the simulator ledger's chunk
  chain from disk and compares to the manifest head. Real. Used at
  `iceberg_complete_simulator.py:179`.
- `verify_chain(mode=...)` — production ledger; walks the chain, recomputes each row's
  hash, checks links. Detects tampering. **Does not** re-derive the decision.
- `twin_custody` — an independent process recomputes every row's hash from
  `SHIPPED_COLUMNS`. A second opinion on integrity.
- RL: "replay" = re-run from `seed` (works, `simple_rl_trainer.py:23`).

**FACT — what does NOT replay:**
- A governance decision cannot be recomputed from its inputs, because the `EventV1`
  observations are not stored (§1, §3).
- No production snapshots — the production ledger is replayed from row 0 every time
  `verify_chain` runs (acceptable at current volume; **UNKNOWN** at scale).

**RECOMMENDATION — snapshot contents, if ever needed for production:** `LogRotationManager`
already models this well. A production snapshot should carry: `state`, `last_sequence_no`
(row id), `row_hash` at that point, `schema_version`, `reducer_version`
(`assemble_episode` version), `cassette_version` + `cassette_code_hash`, `created_at`.
Corruption detection: recompute the chain from the *previous* snapshot forward and compare
the snapshot's `row_hash` — same mechanism as `_recompute_head`.

**INFERENCE:** production snapshots are **premature**. The chain is short (one row per
governed call). Revisit only if `verify_chain` latency becomes a monitored problem.

---

## 14. Determinism Analysis

**Same initial state + same event sequence ⇒ same resulting state?**

| Source of nondeterminism | Location | Classification |
|---|---|---|
| `hash(caller_id)` for RNG seed | `iceberg_complete_simulator.py:54` — `random.Random(hash(caller_id) % 10000)` | **REMOVABLE.** **FACT:** `python3 -c 'print(hash("C0001"))'` gives a different value each process (`PYTHONHASHSEED` randomization, on by default). The simulator's per-caller routing **is not reproducible across runs.** Fix: `hashlib.sha256(caller_id.encode())` or `zlib.crc32`. |
| `time.time()` as event data | `_assemble_live_episode:282` (`observed_at`), `:289` (`started_at = observed_at - duration`) | **GOVERNABLE.** Wall clock leaks into `occurred_at`/`observed_at`. For replay, these must be captured *in the persisted event*, not recomputed. |
| numpy RNG | `simple_rl_trainer.py:23` | **GOVERNABLE / REQUIRED.** Seeded → deterministic; seed now correctly retained (`:33`). A prior bug (re-seeding from the global RNG) is fixed. |
| Redis running-mean merge order | `queue_staffing_bayes_integration.py:283-299` | **REQUIRED NONDETERMINISM.** Cross-worker EMA convergence is order-sensitive by construction. |
| `ThreadPoolExecutor` completion order | `Sim/cluster_runner.py` | **REQUIRED** for throughput; results are keyed per-future so the *collection* is order-independent, but shared queue mutation is not. |
| dict iteration order | `_assemble_live_episode:320` sorts `measured_waits.items()`; `assemble_episode` fold order | **REMOVED already** — the sort is explicit. Good. |
| `json.dumps(default=str)` on unexpected types | kernel `canonical_fields` | **GOVERNABLE** — constrain payloads to JSON scalars. |
| float last-ULP | timestamps, waits, scores in the hash | **UNKNOWN** — no observed failure; `normalize(precision=N)` would close it. |
| Claude model call | `ClaudeGovernanceDecider.safety_check` | **REQUIRED NONDETERMINISM** — external, non-replayable. `model_identity` is captured; the *decision* is not reproducible. |
| UUIDs | not used for event ids (§12) | N/A |

**Is event-sourced replay realistic?** **Partially, and only for the observation→judgment
segment.** **FACT:** if you persist the `EventV1` list (with its captured timestamps) and
the `cassette_code_hash`, then `assemble_episode` + `judge_episode` **is** deterministic
and **will** reproduce the recorded `kernel` verdict. That segment is replayable. The
governor call, the Bayes state, and the RL policy are **not** and should not be claimed to
be.

---

## 15. OBSERVE Relationship

**FACT.** There is a separate `~/observe/` repository (clinical-domain adapters:
`clinical_capacity_orchestration`, `clinical_governance_ledger`, plus a generic
OBSERVE/PERCEIVE `*_adapter.py` / `*_source.py` pattern and a
`RESILIENCE_INTEGRATION_ASSESSMENT.md`). It carries its own `sentinel_os/` copy.
GSA-815's own `observe/` directory is unrelated — it is synthetic call-log generation
(`generate_synthetic_call`) and friction derivation (`derive_stimuli`) for tests and the
simulator (`observe/README.md`).

**UNKNOWN:** the precise integration contract between GSA-815 and the `~/observe/` repo. It
is not imported by any wired GSA-815 code. `production_harness.py:20` imports
`observe_perceive_core` (a *missing* module owed to this repo per `DEPENDENCIES.md`), not
the `~/observe/` package.

**RECOMMENDATION (conditional on the §25 event layer existing).** If GSA-815 persists a
canonical observation-event stream, OBSERVE should **consume that stream read-only** rather
than re-deriving call state from Twilio logs independently. Benefits: one provenance-stamped
source of truth; OBSERVE's diagnostics become reproducible (they replay the same events);
the `EVENT → STATE → OBSERVATION → DIAGNOSIS → GOVERNANCE → ACTION` separation becomes real
instead of two parallel ingestion paths.

**OBSERVE must NOT be allowed to mutate:** the event stream, any ledger row, the cassette,
`intent_stats`, RL weights, or `current_staffing`. OBSERVE reads and emits *observations*
(its own records); it never writes back into the governed state. **This is a hard
invariant** and should be enforced by giving OBSERVE a read-only ledger handle / a
read replica, not the `PostgreSQLLedger` write object.

---

## 16. Resilience Engine Relationship

**FACT.** GSA-815's resilience surface today: `circuit_breaker.CircuitBreaker` instances
(`claude_governor`, `postgres_ledger`, `bayes_redis`), `operational_resilience`,
`resilient_harness.ResilientHarness` (retry-with-backoff wrapping `process_call`).
`~/observe/RESILIENCE_INTEGRATION_ASSESSMENT.md` and a `~/resilience_package/` exist but are
not wired into GSA-815 (**UNKNOWN** what they contain in detail).

**INFERENCE.** A canonical, timestamped observation-event stream *would* be a better
temporal substrate for the resilience concepts the task lists (baseline, deviation, regime
classification, entropy, anomaly detection) than sampling mutable state — because:
- events are immutable and ordered (a baseline computed over them is reproducible);
- provenance lets the analyzer weight `VERIFIED` vs `ESTIMATED` signals differently;
- replay lets a new resilience model be back-tested against historical streams.

Sampling `metrics.get_summary()` or `intent_stats` gives you a point-in-time snapshot with
no history and no provenance.

**RECOMMENDATION:** resilience analysis should be a **downstream consumer of the event
stream**, same as OBSERVE (§15) — not a component inside `process_call`. Keep synchronous
work on the call path minimal (§21).

---

## 17. Persistence Analysis

**FACT.** GSA-815 already has an adequate persistence mechanism: the kernel Postgres
ledger. The candidate's in-memory `EventStore` is strictly worse.

**RECOMMENDATION — persist observation events as a new `record_kind` on the existing
`ledger_entries` table.** Not a new table, not a new database.

| Concern | Design |
|---|---|
| Primary key | existing `ledger_entries.id` (serial) |
| Uniqueness | `event_id` unique per `episode_id`; enforce with a partial unique index `(input_data->>'event_id')` filtered on `record_kind='observed_event'`, mirroring `idx_unique_call_sid` |
| Sequence guarantee | the existing global chain order (row `id`) — no separate `sequence_no` |
| Concurrency | write events in the **same transaction + same `pg_advisory_xact_lock('ledger_entries')`** as the decision row (§11) |
| Hash | events ride the existing per-row `current_hash` chain automatically |
| Retention / archival | same policy as the rest of the ledger; events are the bulk of the volume, so revisit archival if row count becomes a problem |
| Replay performance | acceptable now; snapshots deferred (§13) |

**Alternative considered and rejected:** a separate `observed_events` table with a FK to
`ledger_entries`. Rejected because it would need its *own* hash chain and its *own*
concurrency control, reintroducing exactly the drift the "one copy of the kernel" principle
(`DEPENDENCIES.md`) exists to prevent.

---

## 18. Schema Evolution

**FACT.** `EventV1` has **no** `schema_version` field. The ledger uses `record_kind` as a
discriminator and `OPTIONAL_HASHED_FIELDS` (kernel `canonical_fields.py`) to add hashed
fields without breaking legacy rows (absent field ⇒ omitted from canonical form ⇒ old rows
hash identically). This mechanism was just exercised by sentinel_os PR #28
(`authorized_by_sig`).

**RECOMMENDATION.** If observation events are persisted:
- Add `schema_version` (int) and `reducer_version` (string, e.g. `assemble_episode`'s
  version) to the event payload **from day one** — cheap now, impossible to backfill.
- Do **not** add `event_type_version`, `governance_manifest_version`,
  `configuration_version` as separate fields — `cassette_version` + `cassette_code_hash`
  already pin the governance/config manifest, and they are already on the decision row.
- Replaying an old stream after a reducer change: keep `assemble_episode` versioned and
  dispatch on the event's `reducer_version` — or, simpler, accept that replay reproduces
  *the verdict under the current reducer* and flag when `reducer_version` differs. **The
  honest guarantee is "same events + same reducer version ⇒ same verdict", not "same events
  ⇒ same verdict forever".**

---

## 19. Failure Analysis

| Failure | Classification | Handling (proposed / existing) |
|---|---|---|
| Corrupted event (bad hash) | **REJECT** + **GOVERNANCE REVIEW** | `verify_chain` flags it; twin confirms; row is immutable so corruption = storage fault or attack |
| Missing event (gap in episode's event set) | **WARN** → **RECONSTRUCT** if possible, else **REJECT** the replay | replay of that episode returns "incomplete"; the decision row still stands (it was made with what was there) |
| Duplicate event | **IGNORE** (idempotent) | partial unique index on `event_id` rejects the second write |
| Out-of-order / invalid sequence | **N/A** | global chain order is authoritative; events carry `occurred_at` for domain ordering, not chain position |
| Invalid hash on chain walk | **HALT** verification + **GOVERNANCE REVIEW** | existing `verify_chain` behavior |
| Stale / corrupt snapshot | **RECONSTRUCT** from prior snapshot / row 0 | deferred (§13); when built, recompute-forward + compare |
| Reducer version mismatch on replay | **WARN** | report "verdict recomputed under reducer vX, original was vY" (§18) |
| Provenance mismatch (projected stronger than input) | **REJECT** the projection + **GOVERNANCE REVIEW** | the §10 property test |
| Concurrent commit | **RETRY** (second waits on advisory lock, re-reads head) | existing |
| Partial persistence (events written, decision row not) | **REJECT** — atomic transaction prevents it | §11 — events + decision in one transaction |
| Crash after validation, before commit | **safe** — nothing persisted, call fails, dedup allows reprocess | existing |
| Crash after commit, before response | **safe** — row exists; client retry hits `sid_exists` and gets `duplicate_sid` | existing (`production_harness.py:391-399`) |
| Crash before cache update (`erlang_c_cache`, `intent_stats`) | **IGNORE** — caches rebuild; in-memory learning state loss is already tolerated | existing |
| Replay divergence (recomputed verdict ≠ stored) | **GOVERNANCE REVIEW** | this is the *whole point* of persisting events — it makes this detectable where today it is invisible |

---

## 20. Security Analysis

| Threat | Candidate | GSA-815 with proposed event layer |
|---|---|---|
| Event injection | possible (no auth on `append`) | events written only inside `append_decision`'s locked transaction, by the same service identity that signs `authorized_by` |
| Replay attack | undefended | `call_sid` unique index; events keyed to an `episode_id` that maps 1:1 to a decision row |
| Event duplication | undefended | partial unique index on `event_id` |
| Sequence manipulation | trivial (in-memory) | chain order = row `id`, immutable, trigger-protected |
| Provenance forgery | `Provenance` is a plain dataclass, unsigned | `EventV1.provenance` is folded into the row's `current_hash`; forging it breaks the chain. `authorized_by` is HMAC'd. **But:** an attacker who controls the ingestion path can still *originate* a false `PROVENANCE_VERIFIED` event — the hash proves it wasn't changed after write, not that it was true when written |
| Hash-chain manipulation | undefended | `verify_chain` + independent twin + `UNIQUE(current_hash)` |
| Unauthorized state mutation | undefended | DB immutability triggers; OBSERVE gets a read-only handle (§15) |
| Stale authorization | undefended | `authorized_by` + sig captured per row; rotation handled (PR #28 KeySet) |
| Privilege escalation via projection | undefended | the §10 provenance-monotonicity invariant |

**FACT:** event identity does **not** need stronger semantics than the derived
`episode_id:kind` scheme — it is already unique, non-guessable-in-practice (contains the
`call_sid`), and non-forgeable-post-write (in the chain).

**Do not claim:** that persisting events prevents a compromised ingestion path from
fabricating observations. It makes fabrication *durable and attributable*, not impossible.

---

## 21. Performance Analysis

**Conceptual cost of the proposed event layer, per governed call:**

| Step | Cost | Path |
|---|---|---|
| Build `EventV1`s | already paid today (`_assemble_live_episode`) | sync |
| `assemble_episode` fold | already paid today | sync |
| `judge_episode` | already paid today | sync |
| **New:** canonical-serialize N events (~4–8) | ~microseconds each | sync |
| **New:** N extra INSERTs in the same transaction | one round trip if batched; **shares the advisory lock already held** | sync |
| `verify_chain` over a longer chain | grows O(rows); rows go from ~1/call to ~5–9/call | **async / on-demand only** — it is not on the call path |

**FACT:** the only new synchronous cost is serializing a handful of small dicts and adding
them to an INSERT that is already happening under a lock that is already held. The
5–9× row-count growth affects `verify_chain` and archival, both **off the hot path**.

**Hot path:** `process_call`. Synchronous work that must stay synchronous: dedup check,
cassette read, governor call, decision + event write. Everything else (resilience analysis,
OBSERVE consumption, chain verification, drift analysis, snapshotting) is
**asynchronous / downstream**.

**Do not optimize prematurely:** no snapshots, no async event queue, no batching layer
until row count or `verify_chain` latency is a *measured* problem.

---

## 22. Architecture Comparison

| Option | Description | Fit for GSA-815 | Verdict |
|---|---|---|---|
| **A. Current architecture** | legacy score authoritative; kernel judgment shadow; decision row persisted; observations discarded | Works, ships, but decisions are not reconstructible and bypasses #1/#2/#5 (§9) leave no trace | **Insufficient** — the reconstructibility gap is real |
| **B. Full event sourcing** | all state (queue, Bayes, RL, staffing, sim) derived by replaying an event log | **Wrong** — Bayes EMAs, RL gradients, model calls, thread ordering are non-replayable (§8, §14); would require lying about determinism | **Reject** |
| **C. Partial event sourcing** | event-source *some* domains, keep others mutable | Closer, but "partial event sourcing" implies the sourced domains *derive* their state from the log. Only the episode/verdict domain qualifies, and it does not hold long-lived state | **Overweight** for what is needed |
| **D. Event envelope + existing state model** | define a canonical `EventV1`-shaped envelope, keep all state as-is | Half the answer — envelope without persistence still discards the events | **Incomplete** |
| **E. Governed transition gateway + existing persistence** | mandatory normalize→authorize→project→invariants→commit boundary in front of all state changes | GSA-815 already has this for the authoritative state (ledger append path, §9); building a *new* universal gateway means routing Bayes/RL/queue mutations through it, which serves no governance purpose and adds latency | **Over-engineered** |
| **F. Event ledger primarily for audit/replay** | persist the observation events on the existing ledger; use them for reconstruction, replay verification, OBSERVE/resilience input; keep the decision path exactly as-is | Directly closes the §1 gap; reuses `ledger_postgres`, `assemble_episode`, the advisory lock; no determinism claims beyond what holds; smallest change | **Best fit** |

**The recommended architecture is F, framed as decision C** ("adopt a governed event /
transition *layer*") — because the persisted events plus the existing
`assemble_episode`/`judge_episode` do constitute a governed event+transition layer, just
one built on existing infrastructure rather than a new runtime. **Full event sourcing (E in
the task's §32 sense / B here) does not win, and the investigation explicitly tested that.**

---

## 23. Component Disposition

| Candidate component | Disposition | Rationale |
|---|---|---|
| **Provenance** (`actor_id, policy_id, justification`) | **REJECT (as-is); KEEP kernel's** | `EventV1.provenance` + `method` + `source` and the ledger row's `authorized_by`/`model_identity`/`cassette_code_hash` are strictly richer. Adopting the flat 3-field version would be a downgrade. |
| **NormalizedEvent** | **ADAPT → use `EventV1`** | GSA-815 already normalizes at ingestion (`twilio_log_ingestion` stamps provenance) and builds `EventV1`s. Add `schema_version` + `reducer_version` (§18). Do not build a parallel type. |
| **StateSnapshot** | **EXPERIMENTAL / DEFER** | `LogRotationManager` manifest is the working analogue for the sim. Production snapshots are premature (§13). |
| **HashStrategy** | **REJECT** | `ledger_postgres` + `canonical_fields` + twin is the strategy. Only borrow `normalize(precision=N)` as a **kernel-side** hardening (§7). |
| **EventStore** | **REJECT (in-memory); REPLACE with existing ledger** | Persist as `record_kind='observed_event'` rows (§17). No new store, no new DB. |
| **Reducer** (`GovernanceCoreReducer`) | **REJECT (this one); ADOPT the concept via `assemble_episode`** | The candidate's reducer is a different domain (hiring/isolation). `assemble_episode` is GSA-815's reducer; formalize it, version it. |
| **GovernanceAuditor / InvariantSpec** | **ADAPT → `validate_episode` + one new invariant** | `validate_episode` already does reason-on-mismatch / never-trust-actor. Add the provenance-monotonicity property (§10). Do not build a generic invariant DSL. |
| **SnapshotPolicy / EveryNEventsSnapshot** | **DEFER** | Tied to StateSnapshot. `LogRotationManager` already rotates by size for the sim. |
| **ExecutionRuntime** | **REJECT** | `IcebergProductionHarness` *is* the execution runtime. It has dedup, tracing, circuit breakers, fail-closed governance, cassette binding. The candidate's `ExecutionRuntime` has none of that and cannot instantiate (§2.4). |
| **WAL** | **REJECT** | Postgres + fsync'd manifest already provide durability. |
| **canonical()** | **KEEP (already have it)** | Identical idiom in `canonical_fields`. |
| **normalize(precision=10)** | **ADOPT — in the kernel, not GSA-815** | The one net-new idea. Small float-canonicalization hardening for `canonical_fields`. |

---

## 24. Existing GSA-815 Components to Strengthen

### 24.1 `production_harness.py` — `IcebergProductionHarness._assemble_live_episode`

- **Current responsibility:** builds `EventV1` observations for one call, folds them via
  `assemble_episode`, returns an `EpisodeAssembly`.
- **Current weakness (FACT):** the `EventV1` objects are used once (`judge_episode`) and
  discarded; only `source_events` (IDs) and a summary reach the ledger. A decision cannot
  be re-derived from its inputs.
- **Proposed improvement:** return the event list alongside the assembly; `process_call`
  persists it in the same transaction as the decision row (new `record_kind`).
- **Why:** closes the §1 reconstructibility gap; makes bypasses §9 #1/#2/#5 leave evidence;
  gives OBSERVE/resilience a real substrate.
- **Risk:** 5–9× ledger row growth; the events carry `call_sid`/`caller_id` (PII posture —
  already true of existing rows, but more of it).
- **Test impact:** **cannot be tested in this checkout** — `production_harness` does not
  import (§1). Phase 0 must fix that first. Then: characterization test that a decision +
  its events commit atomically; property test that replaying the events reproduces
  `kernel["tier"]`.

### 24.2 `production_harness.py` — `process_call`, the dual-verdict block (`:458-498`)

- **Current responsibility:** run legacy scorer + kernel `judge_episode`, record agreement,
  act on legacy.
- **Current weakness (FACT):** disagreement produces a `logger.warning` and an approved
  call. The kernel governance evaluator is non-binding and a divergence has no consequence.
- **Proposed improvement:** *policy decision for the repo owner* — either (a) leave as
  shadow but persist the events so divergences are auditable after the fact, or (b)
  escalate: a disagreement forces `governed=True` / routes to human review.
- **Why:** a governance cross-check that never bites is monitoring, not governance.
- **Risk:** (b) changes production behavior and could increase governor load / block calls
  on a scorer bug. Needs a shadow period with persisted events first.
- **Test impact:** integration test with a cassette where `judge_episode` and
  `score_outcome_quality` deliberately diverge.

### 24.3 `governance/ledger_postgres.py` (kernel) — `verify_chain`

- **Current responsibility:** walk the chain, recompute row hashes, detect tampering.
- **Current weakness (INFERENCE):** verifies integrity, not *correctness* — it cannot say
  "this verdict does not match these observations" because the observations are not there.
  Also **UNKNOWN** whether a tail-truncation (drop last N rows) is monitored.
- **Proposed improvement:** add a `reconstruct_decision(row_id)` that pulls the row's
  `observed_event` rows, re-runs `assemble_episode` + `judge_episode`, and compares to the
  stored `kernel` summary.
- **Why:** turns "trust the row" into "recompute the row".
- **Risk:** kernel change, shared by all consumers; must be opt-in and read-only.
- **Test impact:** kernel test suite; a tampered-summary row must fail reconstruction.

### 24.4 `governance/canonical_fields.py` (kernel) — canonical serialization

- **Current weakness (FACT):** no float normalization; `default=str` for unexpected types.
- **Proposed improvement:** apply `normalize(obj, precision=N)` before `json.dumps`.
- **Why:** removes the last-ULP hash-divergence risk between writer and verifier (§7).
- **Risk:** **changes every hash** — must ship as a versioned canonical format with a
  migration, exactly like a schema change. High blast radius; low current urgency.
- **Test impact:** the entire kernel hash-chain test suite; needs a format-version gate.

### 24.5 `iceberg_complete_simulator.py` — RNG seeding (`:54`)

- **Current weakness (FACT):** `random.Random(hash(caller_id) % 10000)` — `hash()` of a
  str is salted per process (verified: two processes gave `7979893543395344367` and
  `4244176512367980173` for `hash("C0001")`); this simulator's per-caller routing is not
  reproducible across runs.
- **Proposed improvement:** `random.Random(int.from_bytes(hashlib.sha256(caller_id.encode()).digest()[:4], "big"))`.
- **Why:** removes an unnecessary source of nondeterminism from the zero-setup demo path.
- **Risk:** trivial; changes which pseudo-random sequence each caller gets (test
  fixtures may need re-baselining).
- **Test impact:** add a test that two runs with the same input produce identical routing.

### 24.6 `queue_staffing_bayes_integration.py` — `BayesianIntentEngine.observe_outcome`

- **Current responsibility:** update P(resolution|intent) from call outcomes.
- **Current weakness (FACT):** no provenance, no authorization, no ledger record — learning
  state that steers routing is entirely ungoverned (§9 #6).
- **Proposed improvement:** *do not event-source it* (§8). Instead, periodically snapshot
  `intent_stats` into the ledger as a `record_kind='belief_snapshot'` row with
  `authorized_by` — an audit checkpoint, not a reducible log.
- **Why:** makes "what did the system believe when it made that routing decision" answerable
  without pretending the EMA is replayable.
- **Risk:** low; additive.
- **Test impact:** new; snapshot round-trips through the ledger.

### 24.7 `Sim/Simulator.py` — `Simulator` `governance` arg

- **Current weakness (FACT):** `governance: Any | None = None`; `None` silently skips
  `governance.enforce`.
- **Proposed improvement:** require an explicit `NullGovernance()` sentinel to run
  ungoverned, so "no governance" is a choice in the call site, not a default.
- **Risk:** trivial; touches sim call sites and fixtures.
- **Test impact:** sim tests updated to pass an explicit governance object.

---

## 25. Recommended Architecture

**Smallest change, largest benefit: persist the observation-event stream on the existing
ledger and make it replayable through the existing reducer.**

```
                        ┌─────────────────────────────────────────────┐
                        │  process_call  (unchanged control flow)      │
                        │                                             │
 Twilio ─► parse ─► friction/emotion ─► legacy score (acts on this)   │
                        │                    │                        │
                        │            _assemble_live_episode           │
                        │             → events: [EventV1...]  ◄── now RETURNED, not dropped
                        │                    │                        │
                        │            assemble_episode (reducer, VERSIONED)
                        │                    │                        │
                        │            judge_episode  → kernel summary   │
                        │                    │                        │
                        │            governor.safety_check            │
                        │                    │                        │
                        │   ┌────────────────┴───────────────────┐    │
                        │   │  ONE transaction, ONE advisory lock │    │
                        │   │   append_decision(row)              │    │
                        │   │   + INSERT observed_event × N       │    │  ◄── NEW
                        │   │   (events ride the same hash chain) │    │
                        │   └────────────────────────────────────┘    │
                        └─────────────────────────────────────────────┘
                                             │
             ┌───────────────────────────────┼───────────────────────────────┐
             ▼                               ▼                               ▼
  reconstruct_decision(row_id)      OBSERVE (read-only)          resilience analysis
  re-run assemble+judge,            consumes event stream,       (async, downstream)
  compare to stored summary         emits observations
  (async / on-demand)
```

**What is new:** (1) `_assemble_live_episode` returns its events; (2) N `observed_event`
rows written in the decision's transaction; (3) a `reconstruct_decision` verifier
(kernel-side, read-only, opt-in). **What is unchanged:** the entire decision control flow,
the legacy-score-is-authoritative posture, the governor, the cassette binding, the
concurrency model, the response shape.

**What this explicitly is NOT:** a new event store, a new database, a new transition
gateway, event-sourcing of queue/Bayes/RL/sim state, or any change to what the harness
acts on.

---

## 26. Proposed Event Contract

Reuse `EventV1`; add two fields. Minimum correct contract:

```
ObservedEvent  (persisted form of EventV1)

  event_id          str    # "{episode_id}:{kind}[:{discriminator}]" — stable, derived, unique per episode
  episode_id        str    # == the governance decision's call_sid-derived id; the partition key
  domain            str    # "ivr"
  kind              str    # route_selected | wait_observed | emotion_inferred | call_ended
  occurred_at       float  # captured, never recomputed on replay
  observed_at       float  # captured
  source            str    # "twilio_log_ingestion" | "observe_perceive_core" | "twilio:call_log"
  provenance        str    # PROVENANCE_VERIFIED | PROVENANCE_ATTESTED | PROVENANCE_ESTIMATED
  method            str?   # required iff ESTIMATED, forbidden iff VERIFIED (existing rule)
  fields            dict   # JSON scalars only
  detail            dict   # JSON scalars only
  schema_version    int    # NEW — 1
  reducer_version   str    # NEW — version of assemble_episode that this stream is meant for
```

**Deliberately omitted** (and why):
- `sequence_no` — the global chain (ledger row `id`) totally-orders everything; a
  per-entity sequence is redundant and adds a concurrency failure mode (§11).
- `previous_hash` / `event_hash` *on the event itself* — the event is a payload inside a
  ledger row; the **row** carries `current_hash` over the canonical form including
  `previous_hash`. Duplicating it on the event invites the two to disagree.
- `execution_id` — `episode_id` already maps 1:1 to the decision.
- `actor` / `authority` / `policy` as event fields — these belong to the **decision row**
  (`authorized_by`, `model_identity`, `cassette_version`), not to each observation. An
  observation's "authority" is its `provenance` + `source`.
- `configuration_version` — `cassette_version` + `cassette_code_hash` on the decision row.

---

## 27. Proposed Transition Contract

```
current_state:      ∅  (episodes are stateless folds — there is no prior episode state)
proposed_event(s):  [EventV1]  built by _assemble_live_episode

  ── normalize ──────  twilio_log_ingestion stamps provenance; make_event validates
                       (VERIFIED⊄method, ESTIMATED⊃method).  Responsibility: ingestion layer.

  ── project ────────  assemble_episode(events) → EpisodeAssembly.
                       Responsibility: kernel reducer (versioned).

  ── governance eval ─ judge_episode(cassette, episode) → verdict;
                       validate_episode invariants (reason-on-mismatch, never-trust-actor).
                       Responsibility: kernel.

  ── conservation ───  provenance-monotonicity check: projected field provenance is never
                       stronger than the weakest contributing event (§10).
                       Responsibility: kernel (new, small).

  ── authorize ──────  governor.safety_check (unchanged); authorized_by + HMAC on the row.
                       Responsibility: GSA-815 harness + kernel ledger.

  ── commit ─────────  ONE transaction under pg_advisory_xact_lock('ledger_entries'):
                         append_decision(GovernanceDecisionRecord(...))
                         + INSERT observed_event × N
                       Responsibility: kernel ledger.

  ── ledger ─────────  events + decision now on the same immutable hash chain.
```

**Where the legacy score sits:** unchanged, outside this contract — it is computed in
parallel and is what the harness acts on. This contract governs *what gets recorded and how
it can be verified*, not *what the harness does next*. Making `judge_episode` authoritative
is the separate policy decision in §24.2.

---

## 28. Test Strategy

| Category | Test |
|---|---|
| **Unit** | `EventV1` with `schema_version`/`reducer_version` round-trips through canonical form; partial unique index rejects a duplicate `event_id` |
| **Integration** | `process_call` writes decision + N events in one transaction; kill the connection mid-write → neither persists (atomicity) |
| **Regression** | existing 55 passing `Tests/` still pass; a legacy `governance_decision` row (no events) still verifies |
| **Property** | for any generated event list, `assemble_episode` is order-independent given the explicit sort; projected provenance ≤ min(input provenance) |
| **Deterministic replay** | persist events for a call, run `reconstruct_decision(row_id)`, assert recomputed `tier`/`score` == stored `kernel` summary — **same event sequence → same verdict** |
| **Rejected event → no mutation** | force `validate_episode` to fail (malformed event) → assert no `observed_event` rows and no `governance_decision` row for that call |
| **Committed event → verifiable lineage** | after commit, `verify_chain` passes over the extended chain; twin recomputes the event rows too (add to `SHIPPED_COLUMNS` if needed) |
| **Concurrency** | two threads `process_call` the same `call_sid` → one `duplicate_sid`, one success, exactly one decision row, its events intact |
| **Transaction atomicity** | crash injection between `append_decision` and event INSERTs → rolled back together |
| **Hash verification** | tamper a persisted event's `fields` (direct SQL, bypassing triggers in a test DB) → `verify_chain` flags the row; `reconstruct_decision` flags the mismatch |
| **Provenance preservation** | an `ESTIMATED` wait event never yields a `VERIFIED` projected `wait_*` field |
| **Snapshot recovery** | deferred with snapshots (§13) |
| **Corruption detection** | truncate the chain tail → external height monitor alarms (needs the monitor — §24.3) |
| **Schema evolution** | replay an event stream tagged `reducer_version=v1` under `assemble_episode` v2 → returns "verdict under v2, original v1", does not silently claim a match |
| **Adversarial mutation** | fabricate a `PROVENANCE_VERIFIED` event via the ingestion path → it persists and is attributable (documents the limit, §20), chain still valid |
| **Performance** | 1000 calls with event persistence vs. without → added latency is serialization + N INSERTs under an already-held lock; assert < a set budget |

**Phase 0 blocker:** none of the `production_harness`-touching tests can run until the
missing modules (`observe_perceive_core`, `sentinel_core`, `metrics_prometheus`,
`cassette_schema` on path) are resolved.

---

## 29. Implementation Plan — DO NOT IMPLEMENT YET

| Phase | Work | Exact files / symbols |
|---|---|---|
| **0. Characterization + unblock** | **DONE 2026-08-27.** The four owed modules were copied into GSA-815 (byte-identical to source) and `governance/__init__.py` removed; spine now imports, `pytest Tests/` is 60 passed / 3 env-gated errors. **Remaining:** write characterization tests capturing current `process_call` behavior (decision row shape, `kernel` summary contents, dual-verdict agreement), ideally against a live `iceberg` Postgres so the `test_real_*` breakers run too. | `DEPENDENCIES.md` ("Owed files delivered"); `production_harness.py:17,20,21`; new `Tests/test_process_call_characterization.py` |
| **1. Canonical event envelope** | Add `schema_version`, `reducer_version` to the event payload. Version `assemble_episode`. | kernel `event_v1.py` (`make_event`, `EventV1`); kernel `assemble_episode` |
| **2. Transition validation boundary** | Add the provenance-monotonicity invariant. Return events from `_assemble_live_episode`. | kernel `episode.py` (`validate_episode`); `production_harness.py:272-364` (`_assemble_live_episode` return), `:472-486` (capture) |
| **3. Provenance / integrity strengthening** | Persist `observed_event` rows in the decision transaction. Partial unique index on `event_id`. Add event columns to `SHIPPED_COLUMNS` if twin should recompute them. | kernel `ledger_postgres.py` (`append_decision`, `_initialize_schema`, the advisory-lock block ~`:699`); `twin_custody.py` (`SHIPPED_COLUMNS`); `production_harness.py:621` |
| **4. Replay / snapshot support** | `reconstruct_decision(row_id)` — read events, re-run `assemble_episode`+`judge_episode`, compare to stored summary. Read-only, opt-in. Snapshots **deferred**. | kernel `ledger_postgres.py` (new method near `verify_chain` ~`:2340`) |
| **5. OBSERVE integration** | Give OBSERVE a read-only ledger handle / replica; have it consume `observed_event` rows instead of re-parsing Twilio logs. Enforce no-write. | `~/observe/` adapters; a read-only `PostgreSQLLedger` variant or a `SELECT`-only role |
| **6. Resilience integration** | Resilience analyzer consumes the event stream (async, downstream) for baseline/deviation/regime work. | `~/resilience_package/`; `circuit_breaker` stays as-is on the hot path |
| **7. Concurrency hardening** | Fix `iceberg_complete_simulator.py:54` RNG. Add a chain-height monitor for tail-truncation. Make `Simulator.governance` non-optional. Add a cross-worker concurrency test for the event+decision transaction. | `iceberg_complete_simulator.py:54`; `Sim/Simulator.py:36`; new `Tests/test_ledger_concurrency.py`; a metrics export of chain height |

**Stop after Phase 4** unless the repo owner wants the OBSERVE/resilience integration —
Phases 5–7 are separate initiatives that the event layer *enables* but does not require.

---

## 30. Rejected Ideas

| Idea | Why rejected |
|---|---|
| Adopt `gov4_kernel` as-is | Non-executable (no `.py`, 6 undefined names, uninstantiable `ExecutionRuntime`). A different domain's reducer. |
| Build a new `EventStore` | GSA-815 has Postgres + a hash chain + concurrency control. A second store is a second source of truth to drift. |
| Full event sourcing (derive all state from a log) | Bayes EMAs, RL gradients, Redis merge order, model calls, thread scheduling are non-replayable. Would require false determinism claims (§14). |
| A universal mandatory transition gateway | The authoritative state (ledger) already has one. Routing Bayes/RL/queue mutations through a gateway adds latency for no governance benefit — those are not governed decisions. |
| Per-entity `sequence_no` on events | The global chain totally-orders everything; a second counter adds the read-seq-N race the candidate has (§11). |
| PROVISIONAL→UUID event lifecycle | GSA-815 assigns stable ids at creation and freezes the event (§12). The candidate's model is strictly weaker. |
| Flat `Provenance(actor, policy, justification)` | `EventV1.provenance` + ledger `authorized_by`/`model_identity`/`cassette_code_hash` is richer. |
| Event-source the Bayes engine | The code itself documents that its EMA "can't be correctly resumed after a restart or merged across processes" (`:290-297`). Snapshot it instead (§24.6). |
| Production state snapshots now | Chain is short; `verify_chain` from row 0 is fine. Premature (§13, §21). |
| Separate `observed_events` table with FK | Needs its own chain + concurrency control. Use a `record_kind` on `ledger_entries` (§17). |
| Make `judge_episode` authoritative in this change | Behavior change; needs a shadow period with persisted events first. It is a policy decision, flagged in §24.2, not folded in silently (matches the harness's own comment at `:460-468`). |

---

## 31. Open Questions / UNKNOWNs

1. **UNKNOWN:** the intended production deployment topology — how many `sentinel_worker`
   processes append concurrently, and at what rate. Determines whether the advisory lock
   is a throughput ceiling and whether snapshots ever matter.
2. **RESOLVED 2026-08-27.** The four owed modules were located (`sentinel_core`,
   `metrics_prometheus`, `grafana_dashboard` in `sentinel_os/sentinel_os/`;
   `observe_perceive_core` in `observe/sentinel_os/` — deliberately removed from the kernel
   in sentinel_os `e50edc3`) and copied into GSA-815 byte-identically. See `DEPENDENCIES.md`.
   `SentinelCore.score_outcome_quality` is now readable (`sentinel_core.py`, 306 lines).
3. **UNKNOWN:** whether the chain's tail-truncation (drop last N rows) is monitored
   anywhere. `verify_chain` catches internal edits; a monotonic height monitor is a
   separate control.
4. **UNKNOWN:** the exact contract between GSA-815 and the `~/observe/` repository —
   nothing wired imports it, and `observe_perceive_core` (the thing `production_harness`
   imports) is a different, missing module.
5. **UNKNOWN:** whether the `Sim/` MARL subsystem's "deterministic replay" docstring claims
   hold — not verified, no evidence either way. Separately and independently: the
   `iceberg_complete_simulator.py:54` determinism claim **is** false (verified — `hash()`
   of a str is per-process salted). These are two unrelated simulators.
6. **RECOMMENDATION-pending:** should `judge_episode` disagreement escalate (§24.2)? Repo
   owner's call.
7. **UNKNOWN:** PII retention posture for 5–9× more ledger rows carrying `caller_id` /
   `call_sid` in `observed_event` payloads.
8. **UNKNOWN:** whether kernel-side canonical-format versioning (for float `normalize`,
   §24.4) is worth its blast radius given no observed hash divergence.

---

## 32. Final Architectural Decision

### **C — ADOPT A GOVERNED EVENT / TRANSITION LAYER**

Scoped precisely as: **persist the observation-event stream (`EventV1`) on the existing
kernel Postgres ledger, in the same transaction and under the same advisory lock as the
governance decision it belongs to, and add a read-only `reconstruct_decision` verifier that
replays those events through the existing `assemble_episode` reducer and `judge_episode`
evaluator.**

This is a governed event+transition layer — but built entirely on infrastructure GSA-815
already depends on (`ledger_postgres`, `assemble_episode`, `validate_episode`, the advisory
lock, the hash chain, HMAC attestation). It is **not** partial or full event sourcing
(D/E in the task's terms are rejected — Bayes/RL/queue/sim state is not replayable and the
investigation tested that), **not** a new gateway (E as phrased — the authoritative state
already has one), **not** a move to OBSERVE (F — OBSERVE should *consume* the stream, not
own it), and **not** "no improvement" (A — the reconstructibility gap in §1 is real and
evidence-backed).

**Prerequisite (Phase 0, non-negotiable):** GSA-815's production spine does not import in
this checkout. The dependency story must be fixed before any of this is testable.

---

## 33. Final Summary — Answers to the Ten Questions

**1. The single most valuable improvement discovered.**
Persist the `EventV1` observation stream that `_assemble_live_episode` already builds and
currently discards, on the existing ledger, so a governance decision can be independently
reconstructed and re-judged from its source observations. Today only a summary and a list
of event *IDs* survive (`production_harness.py:472-486, 641`).

**2. The three highest-value improvements.**
(a) The observation-event persistence layer above.
(b) A `reconstruct_decision(row_id)` verifier that replays events through
`assemble_episode`+`judge_episode` and compares to the stored verdict — turns "trust the
row" into "recompute the row" (`ledger_postgres.py` near `verify_chain`).
(c) Fix `iceberg_complete_simulator.py:54` (`random.Random(hash(caller_id) % 10000)` is not
reproducible across processes — verified) and add a chain-height monitor for tail
truncation.

**3. The biggest architectural risk.**
Believing GSA-815 can offer deterministic replay in general. It cannot — the governor call,
the Bayes EMA (order-dependent by design, `:290-297`), RL gradients, and `ThreadPoolExecutor`
ordering are non-replayable. The honest guarantee is narrow: *same observation events +
same reducer version ⇒ same episode verdict*. Any broader claim would be false.

**4. The most important thing NOT to integrate.**
The candidate's `ExecutionRuntime` / in-memory `EventStore` / per-entity snapshot model.
It has no locking (the exact read-seq-N double-commit race the task's §11 describes), no
persistence, no concurrency control, and cannot even instantiate (`EveryNEventsSnapshot`
undefined). Adopting it would replace a working serialized Postgres chain with a racy
in-memory one. Runner-up: event-sourcing the Bayes engine.

**5. Exact GSA-815 files/symbols that should eventually change.**
- `production_harness.py` — `_assemble_live_episode` (return events, `:272-364`),
  `process_call` (persist them + the dual-verdict block, `:458-498`, `:621`).
- `iceberg_complete_simulator.py:54` — RNG seed.
- `Sim/Simulator.py:36` — make `governance` non-optional.
- `queue_staffing_bayes_integration.py` — `BayesianIntentEngine.observe_outcome` (add a
  ledger `belief_snapshot`, do **not** event-source it).
- `twilio_log_ingestion.py` — `parse_call_log` / `IcebergJourney` (the actual
  GSA-815-owned provenance-stamping boundary; add `schema_version` when the envelope lands).
- `DEPENDENCIES.md` + the three owed modules — Phase 0.
- `Tests/` — new characterization, replay, concurrency, atomicity tests.

**6. Exact capabilities that should remain outside GSA-815 (in the kernel).**
The hash chain, `verify_chain`, twin custody, `pg_advisory_xact_lock` serialization, DB
immutability triggers, `authorized_by` HMAC attestation, `EventV1`/`make_event`/
`validate_event`, `assemble_episode`, `judge_episode`/`validate_episode`, canonical
serialization + any float `normalize` hardening. GSA-815 is a consumer of the kernel's
governance substrate, not a place to reimplement it ("one copy of the kernel", per
`DEPENDENCIES.md`). This is the same finding as sentinel_os PR #28's Q3.

**7. Should OBSERVE consume the resulting event stream?**
Yes — read-only. If the stream is persisted, OBSERVE should consume it instead of
independently re-parsing Twilio logs, giving one provenance-stamped source of truth and
reproducible diagnostics. OBSERVE must never write to the event stream, any ledger row, the
cassette, or learning state — enforce with a `SELECT`-only handle. (Contract with the
`~/observe/` repo is currently **UNKNOWN**, §31.4.)

**8. Is a governed transition gateway justified?**
Not a *new* one. GSA-815's authoritative state mutation (the ledger append) is already
gated: friction gate → governor → atomic write, with `governance_approved` true only if
approved **and** durably recorded (`:723-730`). What is justified is making that path's
*inputs* durable (the event layer) and adding one invariant (provenance monotonicity,
§10). A universal gateway in front of Bayes/RL/queue mutations is over-engineering — those
are not governed decisions.

**9. Should event sourcing be none / partial / substantial / full?**
**None**, in the "derive state by replaying a log" sense — no GSA-815 state domain should
have its authoritative value reconstructed from an event log. What is recommended is an
**audit/replay event ledger** (task option F): events are persisted and replayable *for
verification*, but no component *depends* on replay for its state. This is less than
"partial event sourcing".

**10. Recommended implementation order.**
Phase 0 (unblock imports + characterization tests) → Phase 1 (event envelope:
`schema_version`, `reducer_version`, version `assemble_episode`) → Phase 2 (return events
from `_assemble_live_episode`; add the provenance-monotonicity invariant) → Phase 3
(persist `observed_event` rows in the decision transaction; unique index) → Phase 4
(`reconstruct_decision` verifier). **Stop here and evaluate.** Phases 5 (OBSERVE), 6
(resilience), 7 (concurrency hardening + sim RNG + height monitor) are separate initiatives
the layer enables but does not require.
