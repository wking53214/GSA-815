"""
CallerState.py
--------------

Canonical caller state representation for the GSA.

Best–in–Class Notes:
- Integrated LatentPayload ensures emotional drift is tracked.
- Pure data container; mutated only via simulator step updates.
"""

from __future__ import annotations

# DynamicState and CallerState are contracts this repo shares with the
# library and live in the private CNS package (cns.caller). The copy carried
# here until 2026-09-11 was byte-identical to the one extracted. Re-exported
# so `from Domain.CallerState import CallerState` keeps working.
from cns.caller import CallerState, DynamicState  # noqa: F401

__all__ = ["CallerState", "DynamicState"]
