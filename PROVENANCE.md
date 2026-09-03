# Provenance

## What GSA-815 is

The **IVR / "Iceberg" call-center application**, extracted from the
[`sentinel_os`](https://github.com/wking53214/sentinel_os) governance kernel.
`sentinel_os` is the domain-blind governance substrate; GSA-815 is one
domain-specific consumer of it.

## Origin

| Date | Event |
|---|---|
| 2026-07-31 | Repo created (`db72dcc`). |
| 2026-08-05 | `ee4bac7` "Extract IVR-side of sentinel_os into GSA-815" + `50bde52` `DEPENDENCIES.md`. This is the real starting point: the IVR mission (Twilio ingestion, the Claude governor client, the queue/staffing/Bayes/RL layer, the simulator, `production_harness.py`, `api_server_resilient.py`) moved out of the kernel tree. |
| 2026-08 | A run of `Integrate <X> module into GSA-815` commits (`f0b70d6`, `47b14ac`, `2e7920c`, `e7f60f5`, `7b68b10`, `4b1075f`, `10deea8`) bulk-imported design material derived from an earlier Gemini transcript — see "Transcript-derived material" below. Most of it is not on the live path. |
| 2026-08-28 → 09-03 | Prior sessions' PRs #1–#5: flagged the governance-core status, fixed the dependency blocker (dropped the shadowing `governance/__init__.py`, vendored the owed IVR modules), relocated the synthetic caller data, received the IVR island + `telemetry_pipeline` from the kernel's own IVR scrub, added a ghost-buster baseline. |
| 2026-09-03 | This housekeeping pass: README/PROVENANCE reality-align, dead-weight sweep, `GSA-2/` split to the archived [`GSA-Master-Kernel`](https://github.com/wking53214/GSA-Master-Kernel) repo, kernel-as-submodule + CI. See `docs/CHANGELOG.md`. |

## How it runs

GSA-815 imports ~16 modules from the `sentinel_os` kernel (`episode`,
`event_v1`, `canonical_fields`, `governance_loop_guard`, `governance/`,
`cassette_*`, `circuit_breaker`, `operational_resilience`, `tracing`,
`array_ops`, `governor_injection_defense`, `ai_cost_tracking`, `api_key_auth`,
`queue_schema`). These are **not vendored** — one copy of the kernel. See
[`DEPENDENCIES.md`](DEPENDENCIES.md) for the current mechanism and test result.

Five modules **are** carried here, on purpose, because they are IVR/telephony-
shaped and left the kernel with the rest of the IVR mission:
`sentinel_core.py`, `metrics_prometheus.py`, `grafana_dashboard.py`,
`observe_perceive_core.py`, `telemetry_pipeline.py` (rationale in
`DEPENDENCIES.md`).

## Transcript-derived material

`gsa-governance-core/` (a self-contained "Unified Governance Operating Core"
reference runtime, **not imported by any GSA-815 code**) and several now-removed
root `gsa-*.py` files descend from a Google Gemini design conversation.

The governance core is a deterministic reference/simulation runtime. Its
ledger is an in-memory dict, its "attestation" records without checking, its
"seal" does not sign — `gsa-governance-core/README.md` says so plainly. The
production governance path is the `sentinel_os` kernel ledger, not this file.

That conversation — the full 178 KB transcript, its own provenance record, and
15 extracted code artifacts — was the `GSA-2/` subdirectory here until
2026-09-03. It now lives in its own archived repo:
**[wking53214/GSA-Master-Kernel](https://github.com/wking53214/GSA-Master-Kernel)**.

## Removed in the 2026-09-03 housekeeping pass

All zero-importer; all recoverable from git history.

- `GSA.py`, `GSA/GSA.py`, root `GSA_Governance_Operating_Core_Enterprise.py` —
  three further copies of the governance core. `gsa-governance-core/` is kept
  as the one canonical copy (the two variants differed by 7 trivial lines).
- `gsa-master-kernel-base-flattened.py`, `gsa_universal_interlock_wrapper.py`,
  `gsa-universal-interlock-wrapper-v7.py`, `gsa-cryptographic-interlock-wrapper.py`
  — flattened single-file artifacts from the same transcript.
- `conservation/` — an orphaned "return gateway" experiment (nothing imported
  it; it also pulled an undeclared `conservation_kernel` dependency).
- `governance-control-plane/` (`gov4_kernel`) + `INTEGRATION.md` — a small
  incomplete "GOV4" skeleton and a doc describing it as co-located. Dead.
- `governance/perceive_gate.py` — a broken PERCEIVE-integration stub (imported
  `governance_contracts` from a path that does not exist; nothing imported it).
  `governance/` then had no tracked files and is gone; `governance.*` still
  resolves to the kernel package as intended (verified — the kernel's
  `governance/` is a regular package and wins).

An uncommitted local change dated 2026-09-02 (adding `_canonicalize` /
`compute_state_signature` to the four core copies) was **investigated and
dropped**: it never executed (a dataclass field-ordering error), it edited
code with no importers, and it duplicated hash-chaining that already exists in
`sentinel_os/sage_k/gsa_adapter.py`. It was the GSA-815 half of a cross-repo
"state commitment" effort whose `observe-perceive` half (`cd61bc3`) is a
separate, unresolved thread. The patch is preserved outside the repo.

## Known gaps

- `docker-compose-prod.yml` and `k8s/` reference a `Dockerfile` that does not
  exist in this repo. They are aspirational deployment config, not a wired
  build.

## License

Apache-2.0 (`LICENSE`).
