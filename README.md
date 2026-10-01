# GSA-815

IVR / "Iceberg" **domain execution and learning** application that consumes the [`sentinel_os`](https://github.com/wking53214/sentinel_os) kernel. Not a standalone product. Not imported by [`observe-perceive`](https://github.com/wking53214/observe-perceive): in chain diagrams "GSA-815" means **a caller-supplied callable**.

## 1. Pipeline Position & Role

**EXECUTION** (domain application), under sentinel_os custody.

```text
Admission → Observe → Locks → PERCEIVE → Decision → Conservation
    → EXECUTION (this repo, IVR reference) → Custody (sentinel_os)
```

Sells only together with sentinel_os. Vendored as git submodule `vendor/sentinel_os`.

## 2. Full System Scope & Architectural Depth

GSA-815 was extracted *out of* sentinel_os so the kernel could stay domain-blind. This side keeps telephony-shaped pieces:

- **Live path:** `production_harness.py` (`IcebergProductionHarness`), `api_server_resilient.py`.
- **Domain:** `Domain/CallerState.py`, `Emotion.py`, `Intent.py`, `QueueState.py` (several types now re-exported from private `CNS`).
- **Sim / RL:** `Sim/Simulator.py`, `Engines/simple_rl_trainer.py`, `iceberg_complete_simulator.py`.
- **Observe/ingest:** `observe/IngestAdapter.py`, `twilio_log_ingestion.py`, `observe_perceive_core.py` (engines stay here; percept types from `cns.perception`).
- **Cassettes:** `cassettes/ivr_cassette.py`, `GSA_Universal_Interlock_Wrapper_v1.py`.
- **Governance consumer:** `claude_governance_api.py`, `gsa-governance-core/` (not on the live path; freeze-era leftover).
- **Ops:** `metrics_prometheus.py`, `grafana_dashboard.py`, `telemetry_pipeline.py`, `k8s/*`, `docker-compose-prod.yml`.

LLM (Anthropic) is a **component within processing**, not the governing authority. `governance_decider` lives in the kernel; this repo subclasses (`ClaudeGovernanceDecider`).

Kernel modules **deliberately not copied** (see `DEPENDENCIES.md`): `episode`, `event_v1`, `canonical_fields`, cassette loader/schema, `governance/ledger_postgres`, `governance_loop_guard`, `governor_injection_defense`, `ai_cost_tracking`, `queue_schema`, circuit breaker, etc. One copy of the kernel.

## 3. What It Does NOT Do / Non-Goals

- Does **not** run without `git submodule update --init`.
- Does **not** implement the governed action gate (observe-perceive).
- Does **not** own conservation (removed 2026-09-03; kernel still pulls Conservation Kernel transitively).
- Does **not** issue authorization. It executes under kernel custody.
- Does **not** generalize out of IVR by itself — that is the cassette story in sentinel_os.

## 4. Brutally Honest Current Status & Gaps

| Gap | Detail |
|---|---|
| Collector crash | `pytest` from repo root hits `gsa-governance-core/test_harness.py` `SystemExit`. **CI runs `pytest Tests/`.** So should you. |
| Missing submodule | Without vendor: 17 test files do not collect. |
| Infra | Needs local Postgres (`iceberg/iceberg` superuser) and Redis as the kernel does. Anthropic for live decider tests (failing-key tests exist). |
| Private `CNS` | `cns @ git+https://github.com/wking53214/CNS.git@4ffcaaac…` — **private**. Public clone cannot pip-install the shared contracts. |
| `httpx<0.28` | anthropic 0.116.0 breaks on `proxies` with httpx≥0.28. |
| Orphan `governance/perceive_gate.py` | Hard-coded `../../../observe-perceive` path; nothing imports it; already broken. |
| Dual copies | Kernel historically still carried `sentinel_core` / metrics / grafana; this repo now owns the IVR-shaped copies. Drift risk if kernel copies remain. |
| `gsa-governance-core/` | Not on the live path. Classes overlapping `cns.governance`. Left frozen. |
| Commercial | Red team: sells only with sentinel_os; ledger stage "least evidenced". |

`pip install -r requirements.txt` only works from **repo root** (it `-r vendor/sentinel_os/sentinel_os/requirements.txt`). Measured: 121–127 tests with submodule + Postgres + Redis.

## 5. Core Invariants & Guarantees

- Domain execution is a consumer of kernel custody, not a second kernel.
- Fail-closed governor tests exist (`test_governor_failclosed.py`).
- Production harness breakers: real Anthropic bad-key failure, real Postgres restricted-role INSERT denial (environment-gated).
- Canonical fields for hashing live in the kernel; this repo must not fork them.

No guarantee the public GitHub clone is runnable (private CNS + undeclared local services).

## 6. Inputs, Outputs & Type Contracts

IVR events via `twilio_log_ingestion` / `observe_perceive_core.CallPercept` (from CNS). Decisions written through kernel `governance_harness` → conservation boundary → Postgres ledger. Telemetry: wait, abandonment, frustration (`CallMetric`).

## 7. Stack Integration Topology

```text
GSA-815 production_harness
    → vendor/sentinel_os (submodule)  episode / ledger_postgres / cassette_loader
    → Conservation_Kernel (transitive pin 25145aa)
    → DIT (kernel epistemic gate, git pin)
    → private CNS
    ✗ observe-perceive does not import this repo
ICEBERG / ICEBURG = lineage predecessors, not runtime deps
```

Proprietary. Copyright (c) 2026 William King. All rights reserved. See LICENSE.
