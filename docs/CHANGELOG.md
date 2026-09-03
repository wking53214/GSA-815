# Changelog

Dated, human-readable summary of notable changes. Git history has the full
detail; this is the skim version.

## 2026-09-03

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
