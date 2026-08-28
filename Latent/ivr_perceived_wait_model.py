"""
IVR PERCEIVED-WAIT MODEL  (candidate, not wired in)
==================================================

Origin
------
Relocated verbatim from CODE/content-pipeline-modularized.py, the
`telemetry_simulator.py` section of an archived Gemini transcript. In that
source the two classes below were named `LatentPayload` and `DynamicState`.
They have been renamed here (`IvrPerceivedWaitModel`, `IvrPerceivedWaitDynamics`)
so they do not read as alternatives to this repo's canonical
`Latent/LatentPayload.py` and `Domain/CallerState.py::DynamicState`.

Why it is landed beside, not merged (Option B)
----------------------------------------------
GSA-815 already has a working, wired-in latent layer:
`Latent/LatentPayload.py` (trust / volatility / frustration_memory / drift)
and `Domain/CallerState.py::DynamicState` (perceived_wait, frustration),
evolved once per step by `Sim/Simulator.py::_evolve_latent_state`.

This model is a DIFFERENT, richer thing: an IVR-specific perceived-wait
dilation model. `update_after_step` reads `friction_event`, `actual_wait`,
`expected_wait` and `resolved` off the dynamic object - fields the canonical
`DynamicState` does not have. It therefore cannot be dropped onto the existing
simulator path as-is; promoting it is a deliberate design decision (extend
`DynamicState`, decide whether perceived-wait dilation belongs in the wired
path), not a wiring change. Until that decision is made it stays here,
unimported, as a reference implementation.

Defects corrected on landing (2026-08-27, at William's direction)
----------------------------------------------------------------
The source had two defects. The decision was to keep this file parked and
unwired (Option B) but fix the defects rather than carry them. Both fixes are
minimal - no field, math, or coefficient was changed.

1. `to_dict()` filtered on `k.startswith("")`, which is True for every string,
   so it always returned `{}`. Changed to `k.startswith("_")`, the evident
   intent - it now returns the public fields and hides `_TOLERANCE`,
   `_FRICTION_CAP`, `_DILATION_K`.
2. `update_after_step` mutated the dynamics object passed to it
   (`caller_dynamic.frustration`, `caller_dynamic.perceived_wait`). The
   canonical latent layer treats that object as read-only input. It now
   leaves the argument untouched and RETURNS a new `IvrPerceivedWaitDynamics`
   carrying the recomputed `frustration` and `perceived_wait`; the model's own
   scalars (trust_scalar, volatility, memory_flag, friction_count, step_index)
   are still updated in place on `self`, which is the single-writer pattern the
   canonical layer uses. The arithmetic is identical to the source.

Nothing in GSA-815 imports this module.
"""

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class IvrPerceivedWaitDynamics:
    perceived_wait: float = 0.0
    frustration: float = 0.0
    friction_event: int = 0
    actual_wait: float = 0.0
    expected_wait: float = 0.0
    resolved: bool = False


@dataclass
class IvrPerceivedWaitModel:
    baseline_frustration: float = 0.1
    escalation_rate: float = 0.05
    menu_compliance: float = 0.7
    navigation_depth_prior: float = 0.4
    fraud_risk: float = 0.1
    friction_count: int = 0
    step_index: int = 0
    patience: float = 0.5
    trust_scalar: float = 1.0
    volatility: float = 0.0
    memory_flag: float = 0.0
    _TOLERANCE: int = 1
    _FRICTION_CAP: int = 20
    _DILATION_K: float = 0.5
    RELIEF_RATE: float = 0.1

    def _clamp(self, val: float) -> float:
        return max(0.0, min(1.0, val))

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if not k.startswith("_")}

    def update_after_step(self, caller_dynamic: Any) -> "IvrPerceivedWaitDynamics":
        """Advance the model one step; return updated dynamics, argument unchanged."""
        resolved = bool(getattr(caller_dynamic, "resolved", False))
        self.step_index += 1
        event = int(getattr(caller_dynamic, "friction_event", 0))
        actual = float(getattr(caller_dynamic, "actual_wait", 0.0))
        expected = float(getattr(caller_dynamic, "expected_wait", 0.0))
        frust_in = float(getattr(caller_dynamic, "frustration", 0.0))

        wait_overrun = 1 if actual > expected else 0
        friction_this_step = event + wait_overrun
        self.friction_count = min(self.friction_count + friction_this_step, self._FRICTION_CAP)
        over_tol = max(0, self.friction_count - self._TOLERANCE)

        new_frustration = frust_in
        if friction_this_step > 0:
            d_frust = self.escalation_rate * (1.0 + over_tol) * (1.0 - self.patience)
            new_frustration = frust_in + d_frust
            self.trust_scalar = self._clamp(self.trust_scalar - 0.01 * new_frustration)
            self.volatility = self._clamp(self.volatility + 0.005 * (1.0 + over_tol) * (1.0 - self.patience))
            self.memory_flag = self._clamp(self.memory_flag + 0.01 * (1.0 + over_tol))
        elif resolved:
            new_frustration = max(0.0, frust_in - self.RELIEF_RATE)
            self.trust_scalar = self._clamp(self.trust_scalar + self.RELIEF_RATE * (1.0 - self.trust_scalar))
            self.volatility = self._clamp(self.volatility - self.RELIEF_RATE * self.volatility)

        new_perceived_wait = self._clamp(actual * (1.0 + self._DILATION_K * new_frustration))
        return IvrPerceivedWaitDynamics(
            perceived_wait=new_perceived_wait,
            frustration=new_frustration,
            friction_event=event,
            actual_wait=actual,
            expected_wait=expected,
            resolved=resolved,
        )


def execute_simulator_step(caller: dict) -> None:
    payload = caller.get("latent_payload")
    dynamic = caller.get("dynamic_state")
    if payload and dynamic and hasattr(payload, "update_after_step"):
        caller["dynamic_state"] = payload.update_after_step(dynamic)
