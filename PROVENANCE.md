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
| 2026-09-03 | This housekeeping pass: README/PROVENANCE reality-align (this PR), then a dead-weight sweep, `GSA-2/` split to its own archived repo, and kernel-as-submodule + CI (following PRs). See `docs/CHANGELOG.md`. |

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
reference runtime, **not imported by any GSA-815 code**), the `GSA-2/`
subdirectory, and several root `gsa-*.py` files descend from a Google Gemini
design conversation.

The governance core is a deterministic reference/simulation runtime. Its
ledger is an in-memory dict, its "attestation" records without checking, its
"seal" does not sign — `gsa-governance-core/README.md` says so plainly. The
production governance path is the `sentinel_os` kernel ledger, not this file.

`GSA-2/` is the archived transcript itself (its own provenance record, the
full conversation, and 15 extracted code artifacts). It is being split out to
its own archived repo in this pass; this file is updated when that lands.

## Known gaps

- `docker-compose-prod.yml` and `k8s/` reference a `Dockerfile` that does not
  exist in this repo. They are aspirational deployment config, not a wired
  build.

## License

Apache-2.0 (`LICENSE`).
