# Changelog

Dated, human-readable summary of notable changes. Git history has the full
detail; this is the skim version.

## 2026-09-03

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
