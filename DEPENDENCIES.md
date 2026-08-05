# External dependencies (not vendored on purpose)

This repo is the IVR/Iceberg side, extracted out of `sentinel_os`. It is not
meant to run standalone. It depends on the following modules from the
`sentinel_os` kernel repo, which are deliberately NOT copied in here --
one copy of the kernel, not two that can quietly drift apart:

- episode
- event_v1
- sentinel_core
- cassette_interface, cassette_loader, cassette_schema, cassette_capabilities, cassette_forensics
- governance/ (ledger_postgres, etc.)
- governor_injection_defense
- queue_schema
- circuit_breaker, operational_resilience, api_key_auth, tracing
- metrics_prometheus, grafana_dashboard
- array_ops

Until the kernel repo is packaged as something this repo can install
(pip package, git submodule, or similar), the practical path is running
this repo's code from inside a checkout that also has those files on
PYTHONPATH -- same as it worked inside sentinel_os today.

Also dropped entirely, not carried forward: `gallm_coordinator.py` --
zero importers anywhere in the original repo.
