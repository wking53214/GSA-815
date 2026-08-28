# External dependencies (not vendored on purpose)

This repo is the IVR/Iceberg side, extracted out of `sentinel_os`. It is not
meant to run standalone. It depends on the following modules from the
`sentinel_os` kernel repo, which are deliberately NOT copied in here --
one copy of the kernel, not two that can quietly drift apart:

- episode
- event_v1
- cassette_interface, cassette_loader, cassette_schema, cassette_capabilities, cassette_forensics
- governance/ (ledger_postgres, etc.)
- governance_decider  (base class of this repo's ClaudeGovernanceDecider)
- governor_injection_defense
- ai_cost_tracking
- queue_schema
- circuit_breaker, operational_resilience, api_key_auth, tracing
- array_ops

Until the kernel repo is packaged as something this repo can install
(pip package, git submodule, or similar), the practical path is running
this repo's code from inside a checkout that also has those files on
PYTHONPATH -- same as it worked inside sentinel_os today.

## Corrections (2026-08-05)

`ai_cost_tracking` was listed as this repo's own file and a copy was
vendored here. It is a kernel module: `governance_decider.safety_check`
in the kernel imports it, so the kernel cannot ship without it. The
vendored copy is byte-identical today and is being removed, because two
copies of a pricing table are two answers to "what did that decision
cost".

`sentinel_core`, `metrics_prometheus` and `grafana_dashboard` were listed
as kernel modules. They are not. All three are explicitly Iceberg/
telephony-shaped (SentinelCore requires the telephony_ingest and
routing_topology capabilities; the metrics and dashboard modules export
queue wait times and abandonment rates), so they leave the kernel with
the rest of the IVR mission and belong to this repo.

Also dropped entirely, not carried forward: `gallm_coordinator.py` --
zero importers anywhere in the original repo.

## Owed files delivered (2026-08-27)

The four IVR-shaped modules the wired code here imports but that were
missing from this checkout have been copied in:

| file | source it was copied from | state |
|---|---|---|
| `sentinel_core.py`        | `sentinel_os/sentinel_os/sentinel_core.py`         | byte-identical to source today (md5 `4dcd637f…`) |
| `metrics_prometheus.py`   | `sentinel_os/sentinel_os/metrics_prometheus.py`   | byte-identical (md5 `0f8e5dae…`) |
| `grafana_dashboard.py`    | `sentinel_os/sentinel_os/grafana_dashboard.py`    | byte-identical (md5 `2f8ed17e…`) |
| `observe_perceive_core.py`| `observe/sentinel_os/observe_perceive_core.py` (identical in 5 locations) | byte-identical (md5 `32ab74f9…`) |

`observe_perceive_core` was never named in the list above -- that
omission is why its absence went unnoticed. It is imported by
`production_harness.py` and `iceberg_complete_simulator.py`. It was
deliberately removed from the kernel in sentinel_os commit `e50edc3`
("moved to observe/imports/…"), so it is *not* coming back from the
kernel; this repo now carries it. Its only non-stdlib import is
`twilio_log_ingestion` (already here).

Note -- two copies for now: the kernel still carries `sentinel_core`,
`metrics_prometheus`, and `grafana_dashboard` (its own
`production_harness.py` / `api_server_resilient.py` and ~9 kernel test
files still import them). Removing the kernel's copies is a separate
sentinel_os task with its own test burden; this repo does not depend on
those kernel copies any more.

## `governance/` package (2026-08-27)

`governance/__init__.py` was removed. It made `governance/` a *regular*
package that shadowed the kernel's `governance/` package on `sys.path`,
so `from governance.ledger_postgres import …` (and `drift_core_v1`,
`self_heal_v1`, `log_rotation_v1`) could not resolve -- the production
spine and two test files did not import at all. With the `__init__.py`
gone, `governance.*` resolves to the kernel package as intended.

`governance/perceive_gate.py` is left in place but is **orphaned and was
already broken**: it imports `governance_contracts` from a hard-coded
`../../../observe-perceive` path that does not exist here, and nothing
imports `perceive_gate`. Whoever owns the PERCEIVE integration should
relocate it (e.g. to repo root as `perceive_gate.py`) or remove it.

## Running it

From a checkout with the `sentinel_os` kernel on `PYTHONPATH`:

    PYTHONPATH=/path/to/sentinel_os/sentinel_os python3 -m pytest Tests/

gives **60 passed, 3 errors**. The 3 errors are
`Tests/test_production_harness_breakers.py::test_real_*` -- they need a
live `iceberg` Postgres DB, a valid `ICEBERG_LEDGER_RUNTIME_USER`
restricted role, and real outbound HTTPS to `api.anthropic.com` (they are
explicitly "REAL infrastructure … no mock"). They are environment-gated,
not code-blocked.
