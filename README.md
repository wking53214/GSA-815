# GSA-815

IVR / "Iceberg" **domain execution and learning** application that consumes the [`sentinel_os`](https://github.com/wking53214/sentinel_os) kernel. Not a standalone product. Not imported by [`observe-perceive`](https://github.com/wking53214/observe-perceive): in chain diagrams "GSA-815" means **a caller-supplied callable**.

## Role Within ≡TACK

- **What it is.** The IVR (Iceberg) domain application extracted out of sentinel_os: telephony ingestion, simulation, a production harness and a governance decider that subclasses the kernel's. It does not run alone.
- **Nothing actuates.** "Execution" here means running one call record through the pipeline: the IVR pack scores it, the kernel judges it, the model is asked to sign off when the pack says a sign-off is needed, a row is written to the kernel's ledger, and a result is returned to the caller. No code in this repository routes, transfers, holds or changes a call or a queue. The Twilio stream adapter is a stub that returns an empty list, and the only outbound request in non-test code is the one to the Anthropic API (INSPECTED 2026-11-18). "Learning" is two separate things: a per-intent tally the pipeline writes after each call, which no decision reads; and a small reinforcement-learning trainer used only by the standalone simulator and its tests.
- **Authority matrix.** Evaluation and domain execution only, under sentinel_os's custody. It does not own the ledger, define the kernel's policy, issue authorization, or authenticate callers beyond what the kernel provides. The Anthropic model is a component inside processing, not the governing authority.
- **Does not own.** The kernel modules listed in `DEPENDENCIES.md` (episode, ledger, cassette loader and others), conservation, or the governed action gate (observe-perceive).
- **Depends on.** The `vendor/sentinel_os` submodule, CNS (git pin), Postgres and Redis for the kernel, and Anthropic for live decider tests.
- **Depended on by.** Not imported by observe-perceive (stated in section 1).
- **Fail behavior.** Fail-closed governor tests exist. With `require_cassette_binding=True`, the harness raises when the ledger is unavailable instead of continuing (seen in an earlier run as a Postgres connection error). EXECUTED 2026-11-18 on `main`: the harness refuses to start with no `POSTGRES_PASSWORD`, and with a password but no `ICEBERG_LEDGER_RUNTIME_USER` the ledger refuses and the harness raises. `api_server_resilient.py` is now as strict (2026-11-19): it refuses to start with no `ICEBERG_API_KEYS` (the made-up development key is never used) and refuses to serve plain HTTP when no certificate files are found. One explicit switch, `ICEBERG_ALLOW_INSECURE_DEV=1`, allows both for local development only. `/health` needs no key. Neither entry point starts from a bare `python production_harness.py`: the kernel folder `vendor/sentinel_os/sentinel_os` has to be on `PYTHONPATH` (the tests get it from `conftest.py`). A public clone needs the setup in section 4 before it runs.

## 1. Pipeline Position & Role

**EXECUTION** (domain application), under sentinel_os custody.

```text
Admission → Observe → Locks → PERCEIVE → Decision → Conservation
    → EXECUTION (this repo, IVR reference) → Custody (sentinel_os)
```

This is the design order, not an order any program here runs. observe-perceive does not import this repo (in its chain diagrams "GSA-815" is a caller-supplied callable), and "EXECUTION" here means scoring and recording one call record (see "Nothing actuates" above); no code in this repo changes a call or a queue.

Sells only together with sentinel_os. Vendored as git submodule `vendor/sentinel_os`.

## 2. Full System Scope & Architectural Depth

GSA-815 was extracted *out of* sentinel_os so the kernel could stay domain-blind. This side keeps telephony-shaped pieces:

- **Live path:** `production_harness.py` (`IcebergProductionHarness`), `api_server_resilient.py`.
- **Domain:** `Domain/CallerState.py`, `Emotion.py`, `Intent.py`, `QueueState.py` (several types now re-exported from `CNS`).
- **Sim / RL:** `Sim/Simulator.py`, `Engines/simple_rl_trainer.py`, `iceberg_complete_simulator.py`.
- **Observe/ingest:** `observe/IngestAdapter.py`, `twilio_log_ingestion.py`, `observe_perceive_core.py` (engines stay here; percept types from `cns.perception`).
- **Cassettes:** `cassettes/ivr_cassette.py`, `GSA_Universal_Interlock_Wrapper_v1.py`.
- **Governance consumer:** `claude_governance_api.py`, `gsa-governance-core/` (not on the live path; freeze-era leftover).
- **Ops:** `metrics_prometheus.py`, `grafana_dashboard.py`, `telemetry_pipeline.py`, `k8s/*`, `docker-compose-prod.yml`.

Which of these the live path really uses (INSPECTED 2026-11-18, by following imports from `production_harness.py` and `api_server_resilient.py`): it imports `governed_pipeline`, `ivr_pack`, `domain_pack`, `ivr_friction`, `twilio_log_ingestion`, `observe_perceive_core`, `sentinel_core`, `queue_staffing_bayes_integration`, `claude_governance_api`, `resilient_harness`, `metrics_prometheus` and `grafana_dashboard`, and it loads `cassettes/ivr_cassette.py` by name through the kernel's cassette loader. It does **not** import `Domain/`, `Sim/`, `Engines/`, `Model/`, `Latent/`, `observe/`, `iceberg_complete_simulator.py`, `cassettes/GSA_Universal_Interlock_Wrapper_v1.py`, `telemetry_pipeline.py`, `recommendation_impact.py` or `gsa-governance-core/`. Those are the standalone simulator, test-only code, or files nothing imports. So the Domain, Sim / RL and Observe/ingest bullets above (except `twilio_log_ingestion.py` and `observe_perceive_core.py`) and the Interlock wrapper describe code that is present, not code that runs when a call is processed.

LLM (Anthropic) is a **component within processing**, not the governing authority. `governance_decider` lives in the kernel; this repo subclasses (`ClaudeGovernanceDecider`).

Kernel modules **deliberately not copied** (see `DEPENDENCIES.md`): `episode`, `event_v1`, `canonical_fields`, cassette loader/schema, `governance/ledger_postgres`, `governance_loop_guard`, `governor_injection_defense`, `ai_cost_tracking`, `queue_schema`, circuit breaker, etc. One copy of the kernel.

## 3. What It Does NOT Do / Non-Goals

- Does **not** run without `git submodule update --init`.
- Does **not** implement the governed action gate (observe-perceive).
- Does **not** own conservation (removed 2026-09-03; kernel still pulls Conservation Kernel transitively).
- Does **not** issue authorization. It executes under kernel custody.
- Does **not** generalize out of IVR by itself, that is the cassette story in sentinel_os.

## 4. Brutally Honest Current Status & Gaps

| Gap | Detail |
|---|---|
| Collector crash | `pytest` from repo root hits `gsa-governance-core/test_harness.py` `SystemExit`. **CI runs `pytest Tests/`.** So should you. |
| Missing submodule | Without vendor: 29 of the 32 test files do not collect (EXECUTED 2026-11-18; this row said 17). |
| Infra | Needs local Postgres (`iceberg/iceberg` superuser) and Redis as the kernel does. Anthropic for live decider tests (failing-key tests exist). |
| `CNS` visibility | `cns @ git+https://github.com/wking53214/CNS.git@v4.1.0`. CNS is public. It was installed from this pin on 2026-11-18 in a session with no access to the library's private repositories (EXECUTED), and this repository's CI dropped its read token on 2026-11-17 because every repository it reads is public. This row used to say CNS is private; that is no longer true. |
| `httpx<0.28` | anthropic 0.116.0 breaks on `proxies` with httpx≥0.28. |
| Removed `governance/perceive_gate.py` | Was an orphaned, already-broken stub; deleted (see `docs/CHANGELOG.md`, `PROVENANCE.md`). Nothing to fix. |
| Dual copies | Kernel historically still carried `sentinel_core` / metrics / grafana; this repo now owns the IVR-shaped copies. Drift risk if kernel copies remain. |
| `gsa-governance-core/` | Not on the live path. Classes overlapping `cns.governance`. Left frozen. |
| Commercial | Red team: sells only with sentinel_os; ledger stage "least evidenced". |

`pip install -r requirements.txt` only works from **repo root** (it `-r vendor/sentinel_os/sentinel_os/requirements.txt`). EXECUTED 2026-11-18 at `9e65a09` (`main`), Python 3.13: a fresh copy with the submodule at its pinned commit `cf4bbc1`, `pip install -r requirements.txt`, a local Postgres 16 with the `iceberg` superuser, the `redis-server` binary on the path, run as root as CI does. `pytest Tests/`: 333 passed, 0 failed, 0 skipped. With no Postgres server: 312 passed, 21 errors, all `connection refused` in `test_ivr_events_real_ledger.py`, `test_production_harness_breakers.py` and `test_toy_pack_end_to_end.py`. `ruff check . --exclude vendor`: clean.

Three tests in `test_production_harness_breakers.py` build a real Anthropic client with an invalid key and call the real API address. They now run only when `GSA_REAL_CONNECTION_TESTS=1` is set; otherwise they are skipped, so an ordinary run never leaves the machine. The counts above were taken before this change, when those three always ran: with the switch off, expect 3 fewer passes and 3 skips. This change was not run here (no Postgres or submodule in the working copy); only the file's syntax was checked. In the earlier isolated run (loopback only) the three still passed, which shows they pass on any connection failure, not only on a rejected key.

Earlier figures, for the record: "121 to 127 tests" (reported, undated), and 307 passed with 21 errors on 2026-11-15 at the earlier commit `fefdabd`, with no Postgres and a sibling kernel checkout. At `fefdabd` itself `pip install -r requirements.txt` fails, because the kernel commit it pinned (`e97683c`) pins CNS v2.3.0 against this repository's v4.0.0 (EXECUTED as a dry run); `main` moved the pin on 2026-11-16. The pinned kernel commit is on sentinel_os `main` and 6 commits behind it (VERIFIED 2026-11-18). Not run: CI on GitHub, Python 3.12 (CI's version), Docker and the `k8s/` files.

## 5. Core Invariants & Guarantees

- Domain execution is a consumer of kernel custody, not a second kernel.
- Fail-closed governor tests exist (`test_governor_failclosed.py`).
- Production harness breakers: real Anthropic bad-key failure, real Postgres restricted-role INSERT denial (environment-gated).
- Canonical fields for hashing live in the kernel; this repo must not fork them.

No guarantee the public GitHub clone is runnable without setup: it needs the submodule, a local Postgres with an `iceberg` superuser, and the `redis-server` binary (section 4). CNS is public, so it is no longer an obstacle (this line used to say "private CNS").

## 6. Inputs, Outputs & Type Contracts

IVR events via `twilio_log_ingestion` / `observe_perceive_core.CallPercept` (from CNS). Decisions are written by `governed_pipeline.py` straight to the kernel's Postgres ledger, handing it the episode it judged. The ledger (`governance/ledger_postgres.py`) runs the conservation boundary on that episode before it writes a row, and refuses a decision that arrives without one. The kernel's `governance_harness` is not on this path; earlier revisions of this line said it was, and the pipeline wrote to the ledger with no boundary check at all until this change. Telemetry: wait, abandonment, frustration (`CallMetric`).

## 7. Stack Integration Topology

```text
GSA-815 production_harness
    → vendor/sentinel_os (submodule)  episode / ledger_postgres / cassette_loader
    → Conservation_Kernel (transitive pin cc42d3f, via the kernel's requirements)
    → DIT (kernel epistemic gate, git pin)
    → CNS (public; git pin v4.1.0)
    ✗ observe-perceive does not import this repo
ICEBERG / ICEBURG = lineage predecessors, not runtime deps
```

Apache-2.0.
