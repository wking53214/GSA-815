# GSA-815

**Role in the governed action stack:** EXECUTION / domain application — IVR call-center consumer of [sentinel_os](https://github.com/wking53214/sentinel_os) governance kernel. In [observe-perceive](https://github.com/wking53214/observe-perceive) diagrams, "GSA-815" is typically a **callable the caller supplies**, not a hard import of this repo.

```text
Live path: Admission → OBSERVE/Keys → Locks → PERCEIVE → Decision → Conservation → Execution → Custody
This repo: domain execution + learning under sentinel_os custody
```

---

> **Unfrozen 2026-09-11.** GSA-815 is the execution side of the custody
> ledger stage and sells only together with
> [sentinel_os](https://github.com/wking53214/sentinel_os), which it
> vendors as a git submodule at `vendor/sentinel_os`. Without
> `git submodule update --init` 17 test files do not collect; with the
> submodule and Postgres and Redis available, 121 tests pass. Running
> `pytest` from the repo root crashes the collector
> (`gsa-governance-core/test_harness.py` raises SystemExit); CI runs
> `pytest Tests/` and so should you. The governed action gate in
> observe-perceive never imports this repo: "GSA-815" in the chain diagram
> is a callable the caller supplies.
>
> See `docs/audit/COMMERCIAL_RED_TEAM_2026-09-08.md` in observe-perceive for freeze history.

A governed adaptive processing architecture for controlled decision-making, execution, simulation, learning, and system integration. The current implementation is an Interactive Voice Response (IVR) call-center system.

## What this repo actually is

GSA-815 is the **IVR / "Iceberg" application** that was extracted out of the
[`sentinel_os`](https://github.com/wking53214/sentinel_os) governance kernel.
It is the domain-specific consumer; `sentinel_os` is the domain-blind
governance substrate (append-only hash-chained ledger, episode/event schema,
conservation boundary, twin witness).

- **It does not run standalone.** GSA-815's code imports ~16 modules from the
  `sentinel_os` kernel which are **deliberately not copied in here**. See [`DEPENDENCIES.md`](DEPENDENCIES.md).
- **The live path** is `production_harness.py` (`IcebergProductionHarness`) and
  `api_server_resilient.py`.
- **Provenance:** see [`PROVENANCE.md`](PROVENANCE.md).

### Running it

```bash
git submodule update --init
python3 -m pytest Tests/
```

## Architectural purpose

INPUT / ENVIRONMENT → DOMAIN & STATE → PROCESSING / INTELLIGENCE → DECISION / ACTION → OBSERVATION → SIMULATION / LEARNING → GOVERNANCE CONTROL → CONTROLLED EXECUTION

The LLM is a component within processing, not the governing authority.

The IVR scenario is the **reference application**, not the limit of the architecture.
