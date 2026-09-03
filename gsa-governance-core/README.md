# GSA Governance Operating Core (Enterprise)

**Version:** 5.0.0  
**Architecture Family:** GSA / Citadel / AEGIS Unified Governance Runtime  
**Classification:** Enterprise Deterministic Governance Control Plane

---

## Overview

Unified Governance Operating Core that converts untrusted execution requests into verified, traceable, governed execution artifacts.

### Implemented Layers

| Layer | Status |
|-------|--------|
| Data Governance | ✓ |
| Integrity Validation | ✓ |
| Provenance Tracking | ✓ |
| Zero Trust Execution | ✓ |
| Identity Governance | ✓ |
| Policy Enforcement | ✓ |
| Human Approval Workflow | ✓ |
| Cryptographic Sealing | ✓ |
| Immutable Audit Ledger | ✓ |
| Universal Adapter Boundary | ✓ |
| Kernel Registry | ✓ |
| Module Attestation | ✓ |
| Capability Discovery | ✓ |
| Runtime Health Monitoring | ✓ |
| Circuit Breaker Protection | ✓ |
| Rate Limiting | ✓ |
| Adaptive Threshold Control | ✓ |
| Resilience Plane | ✓ |
| Unified Execution Orchestration | ✓ |
| Diagnostics & Self-Testing | ✓ |
| Production Entrypoint | ✓ |

**Architectural Principle:**  
> Governance is not a feature.  
> Governance is the execution substrate.

---

## Status — read before relying on this

This file is a **self-contained reference runtime**, not the production
governance path for the GSA / Iceberg platform. That path is `sentinel_os`'s
`governance/ledger_postgres.py` — a persistent Postgres ledger with a global
hash chain, DB-level immutability triggers, a witness ("twin"), and keyed
HMAC attestation of the `authorized_by` field. GSA-815 depends on it directly
(see `../DEPENDENCIES.md`); it is not reimplemented here.

**Nothing in GSA-815 imports this module.** It is kept as a design reference
and a runnable demo (`python GSA_Governance_Operating_Core_Enterprise.py`,
`python test_harness.py`), not as a dependency of the live path. Three
identical/near-identical copies elsewhere in the repo (`GSA.py`, `GSA/GSA.py`,
a root copy) were removed 2026-09-03; this is the one kept copy. It descends
from a Gemini design transcript, now archived at
[wking53214/GSA-Master-Kernel](https://github.com/wking53214/GSA-Master-Kernel)
(see `../PROVENANCE.md`).

A `✓` in the table above means "a layer object exists and runs in the
self-test," not "production-hardened." Specifically, in this file:

- **`GovernanceLedger`** ("Immutable Audit Ledger") is an in-memory `dict`
  (`self.chain = {}`). It does not persist — every entry is gone on process
  exit — and each entry is an independent per-`execution_id` SHA-256 digest,
  not a global append-only chain linking one execution to the next. Nothing
  makes it immutable.
- **`AttestationService.attest()`** ("Module Attestation") hashes a module's
  name/version/description and records `verified=True` unconditionally;
  `verify()` returns that stored flag. It attests that a record was created,
  not that anything was independently checked.
- **`CryptographicSealEngine.seal()`** ("Cryptographic Sealing") wraps a
  digest in a dataclass with a timestamp; it does not sign or seal.

These are fine for a deterministic reference/simulation runtime. They are not
an audit trail. Use the kernel ledger for anything that has to survive a
restart or an examiner.

---

## Requirements

- Python 3.10+ (uses `dataclasses.slots`, `from __future__ import annotations`)
- No external dependencies — pure standard library (`asyncio`, `hashlib`, `json`, `uuid`, etc.)

---

## Quick Start

```bash
python GSA_Governance_Operating_Core_Enterprise.py
```

This runs:

1. Runtime diagnostics
2. Governance self-test
3. Short simulation (5 executions)
4. One full production governed execution

Expected output includes:

```
GSA GOVERNANCE CORE ONLINE
```

followed by diagnostic results, self-test pass, simulation report, and a sealed `UnifiedExecutionResult`.

---

## Core Execution Flow

```
Request
  │
  ▼
Identity Verification
  │
  ▼
Envelope Creation
  │
  ▼
Data Governance (sanitize + hash)
  │
  ▼
Policy Evaluation
  │
  ▼
Integrity Validation (Citadel Diamond)
  │
  ▼
Adapter / Router
  │
  ▼
Execution
  │
  ▼
Output Governance Gate
  │
  ▼
Cryptographic Seal
  │
  ▼
Immutable Ledger Commit
```

---

## Project Layout

```
gsa-governance-core/
├── GSA_Governance_Operating_Core_Enterprise.py   # Full runtime
├── README.md
└── .gitignore
```

---

## License

Proprietary / Internal use unless otherwise specified by the architecture owner.
