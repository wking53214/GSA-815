# Changelog

Dated, human-readable summary of notable changes. Git history has the full
detail; this is the skim version.

## 2026-10-29

- **The ledger now attests an IVR episode against its events.** The IVR pack already
  built the events an episode is folded from but kept only their ids. It now keeps the
  events too, and the pipeline hands them to the ledger with the episode. The kernel
  (sentinel_os #88, pinned in Step 1) then registers the episode's root only if those
  events reproduce it, so an episode that says more than its events support is
  refused as `ROOT_NOT_ATTESTED`, and the event stream is written beside the
  decision. This is a limit as well as a gain: the events are built here from the same
  Twilio record as the episode, so they do not show the call really happened that
  way. A pack whose assembly carries no events is called exactly as before. Two
  stand-in ledgers in `test_domain_pack_contract.py` and
  `test_process_call_characterization.py` gained the `observed_events` argument
  (signature only).
- **Production now requires the ledger attestation key.** The kernel refuses
  to start a ledger without one, but `docker-compose-prod.yml` defaulted it to
  empty, so compose started a container that then died at boot. Compose now
  stops up front with a message, the same way it does for
  `POSTGRES_PASSWORD`. The comments in `docker-compose-prod.yml`,
  `k8s/deployment.yaml` and `k8s/secret.yaml.example` said an unset key meant
  unattested rows; that stopped being true with the kernel pin bump and is
  corrected. The Kubernetes key stays optional in the manifest because a
  mounted key file is the alternative.

- **Kernel pin bumped to sentinel_os `51f0e09` (its `main`).** The ledger now
  verifies each governed decision against its episode (sentinel_os PR #85),
  which `governed_pipeline.py` already passes. On the old pin (`3cc0452`) that
  argument was rejected and every governed write failed closed. The new
  kernel also requires an attestation signing key: production must set
  `ICEBERG_LEDGER_ATTESTATION_KEY`, and `conftest.py` generates a random one
  per test session when none is configured.

## 2026-10-28

- **A governance-blocked call no longer reports `success: true`.** `POST
  /process` in `api_server_resilient.py` returned `{"success": true, "result":
  ...}` for every returned dict, so a blocked call looked like a success. It
  now sets `success` to `false` when `result.governance_blocked` is true. The
  HTTP status stays 200 and the `result` body is unchanged. `POST /batch` and
  the batch summary in `production_harness.py` are unchanged. New
  `Tests/test_api_blocked_call_success.py`.

- **The kernel's judgment is mandatory for a governed call.** In
  `governed_pipeline.py`, when the kernel could not judge a case that needs
  sign-off (`EpisodeIntegrityError`, `EventIntegrityError` or `KeyError`), the
  decision is now a refusal (`safe: False`, reasoning `Kernel judgment
  unavailable: <error>: <detail>`) and the governor is not asked. The result
  reports `governance_approved: False` and `governance_blocked: True`, and the
  refused decision is still written to the ledger with the kernel error in its
  input. Before, such a call could be approved on the pack's own scoring
  ("legacy scoring stands"). An ungoverned call is unchanged. Any other
  exception from the kernel step still propagates out of `process()` as
  before. New `Tests/test_kernel_judgment_mandatory.py`.

- **The process_call response labels estimated fields.** `governed_pipeline.py`
  now returns `estimated_fields` and `field_provenance` next to
  `cassette_version`: the same values the ledger row already carried under
  `kernel`, so a caller can tell an estimated field from a measured one. Both
  are `None` when the kernel could not judge the call. `Tests/golden/process_call_golden.json`
  regenerated (the diff is only the two new keys), the exact-dict assertion in
  `Tests/test_toy_pack_end_to_end.py` extended, and
  `test_the_response_labels_estimated_fields` added.

## 2026-10-09

- **Loop guard is observe-only.** `production_harness.py` used to replace the
  governor's decision with a refusal when its reasoning text matched one of the
  last 1000 it had seen. A healthy governor repeats short verdicts across
  different calls and on retries, so the second call with the same wording was
  refused, and so was every later one. The repeat is now counted
  (`loop_repeats_seen`), set as the `decision.loop_repeat` trace attribute and
  logged, and the decision is left alone. The `decision.loop_blocked` trace
  attribute is no longer set. New `Tests/test_loop_guard_observe_only.py`.

## 2026-09-03

- **Kernel as a git submodule + CI + ruff gate.** `sentinel_os` is now pinned
  as a git submodule at `vendor/sentinel_os` (SHA `3cc0452`) instead of an
  ambient `PYTHONPATH`. Root `conftest.py` appends
  `vendor/sentinel_os/sentinel_os` to `sys.path` — *appended*, so this repo's
  own IVR-shaped copies of `sentinel_core` / `metrics_prometheus` /
  `grafana_dashboard` / `observe_perceive_core` / `telemetry_pipeline` still
  win; only the owed kernel modules resolve from the submodule (verified).
  New `requirements.txt` (`-r vendor/.../requirements.txt` + `httpx<0.28`).
  New `.github/workflows/tests.yml` — GSA-815's **first CI**: native Postgres
  + `redis-server` binary + submodule checkout + `pytest Tests/` (127 passed)
  + a `ruff check . --exclude vendor` **hard gate**. Fixed the 9 ruff findings
  that gate surfaced (all in `gsa-governance-core/`: 2 unused imports, 1
  unused local, 6 compound-statement lines in `test_harness.py`).
  `DEPENDENCIES.md` "Running it" rewritten for the submodule flow.

- **`GSA-2/` split out to its own archived repo.** The `GSA-2/` subdirectory
  was a full archived-transcript trio (178 KB `TRANSCRIPT.md`, a detailed
  `PROVENANCE.md`, 15 extracted `artifact_*.py`) for a Gemini "GSA Master
  Kernel" design conversation — no GSA-815 code imports it. Moved verbatim to
  **[wking53214/GSA-Master-Kernel](https://github.com/wking53214/GSA-Master-Kernel)**
  (public, born archived; a `README.md` + Apache-2.0 `LICENSE` added) and
  removed from GSA-815. `gsa-governance-core/` and the deleted root `gsa-*.py`
  artifacts descend from this transcript.

- **Dead-weight sweep + governance-core consolidation.** Removed 14 files,
  all zero-importer, none on the live path (`PYTHONPATH=<kernel> pytest
  Tests/` stays at 127 passed / 0 errors):
  - 3 further copies of the ~5,000-line "governance core" (`GSA.py`,
    `GSA/GSA.py`, root `GSA_Governance_Operating_Core_Enterprise.py`);
    `gsa-governance-core/` kept as the one canonical copy, with a README note
    that nothing imports it.
  - 4 flattened root artifacts from the same Gemini transcript
    (`gsa-master-kernel-base-flattened.py`, three `*interlock-wrapper*.py`).
  - `conservation/` (orphaned "return gateway"; also pulled an undeclared
    `conservation_kernel` dep), `governance-control-plane/` + `INTEGRATION.md`
    (dead "GOV4" skeleton), `governance/perceive_gate.py` (broken import,
    orphaned). `governance/` is now empty and gone; `governance.*` still
    resolves to the kernel package.
  - The uncommitted 2026-09-02 `_canonicalize`/`compute_state_signature` edit
    across the four cores was investigated and dropped (never ran; duplicated
    `sage_k` hash-chaining; see `PROVENANCE.md`).
  - `ruff` drops from 814 to 772 here; the remaining count is 763 in `GSA-2/`
    (removed in the next PR) + 9 in `gsa-governance-core/` (fixed with the
    CI gate).

- **README + PROVENANCE reality-align.** The README opened with a
  general-purpose-architecture-framework framing that never stated what
  `DEPENDENCIES.md` says plainly: GSA-815 is the IVR/Iceberg application
  extracted from `sentinel_os`, it consumes the kernel, and it does not run
  standalone. Added a "What this repo actually is" section up front. New root
  `PROVENANCE.md` — extraction history, the Gemini-transcript lineage of the
  `gsa-*` root files and `gsa-governance-core/`, what is vendored on purpose
  vs owed from the kernel, and a known-gaps list. `DEPENDENCIES.md`: added the
  two owed kernel modules the list omitted (`canonical_fields`,
  `governance_loop_guard`) and corrected the stale "60 passed / 3 errors"
  test result to the current 127 / 0. This CHANGELOG created.
