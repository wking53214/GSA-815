"""
IVR FRICTION ENGINE  (candidate, not wired in)
==============================================

Origin
------
Ported on 2026-10-10 from the ICEBURG repo's `Iceburg/Latent/LatentPayload.py`
when ICEBURG was buried in the Graveyard. In ICEBURG the class was named
`LatentPayload` and was the one subsystem its own scorecard called hardened
(19 tests: clamping, convex accrual, the relief cap, non-decaying memory and
peak, hash separation, trajectory determinism). It is renamed here
(`IvrFrictionEngine`) for the same reason the sibling module renamed its
copy: so it does not read as an alternative to this repo's canonical
`Latent/LatentPayload.py`. ICEBURG's own source was recovered from
`Claude_History` conversation `6ac96fa8` (2026-07-01) and extended there.

Relationship to `ivr_perceived_wait_model.py`
---------------------------------------------
That sibling is an earlier copy of the same idea, relocated from
CODE/content-pipeline. This module is the later, hardened version of it.
Both are parked and unwired. Nothing in GSA-815 imports either one.

What this version does that the sibling does not
------------------------------------------------
1. Friction and resolution are not mutually exclusive. A caller can misroute
   and reach the right place in the same step. The sibling uses `elif`, so
   on that step the friction branch always wins and relief never fires.
2. Relief climbs toward `trust_baseline` plus a bounded overshoot
   (`_TRUST_OVERSHOOT_CAP`), not toward 1.0. A well-handled failure can end
   a call above its starting trust, by a bounded amount.
3. On a step that also took friction, relief may at most undo that step's
   trust damage. Without this cap a misroute-then-resolve step nets higher
   trust than a step where nothing happened, which rewards manufacturing a
   small fixable stumble over running clean.
4. Resolution earns tolerance back (`_FRICTION_DECAY_PER_RELIEF`). In the
   sibling `friction_count` only ever grows.
5. `actual_wait` is documented as seconds and normalized against
   `_WAIT_NORMALIZATION_SECONDS`. The sibling clamps the raw value, so any
   real wait above one second saturates perceived wait at 1.0.
6. `peak_frustration` is a never-decaying high-water mark. Relief pulls final
   frustration down, so a caller who spiked and was then smoothed reads calm
   at call end, which is exactly the caller an end-state check misses. It is
   a severity signal (how bad), never a classifier (whether).
7. A negative `friction_event` cannot corrupt the count.
8. `load_from_dict` keeps types (the first version clamped every field as a
   unit float, turning `friction_count=5` into 1.0 and crashing on a `None`
   baseline), and there are two labelled hashes: `structural_hash` (all
   state, moves every step, for replay equivalence) and `content_hash`
   (excludes `step_index`, moves only when something meaningful did).

Differences from the ICEBURG original
-------------------------------------
- `update_after_step` leaves its argument untouched and RETURNS a new
  `IvrPerceivedWaitDynamics`, matching the sibling and the canonical latent
  layer's read-only treatment of that object. ICEBURG mutated the argument
  in place. The arithmetic is otherwise identical, step for step; the
  Graveyard entry's equivalence check ran both over randomized scripts.
- The dynamics type is the sibling's `IvrPerceivedWaitDynamics`, which has
  the same six fields as ICEBURG's `DynamicState`.

Status of the constants
-----------------------
None of the tunables below is validated against real call data. They produce
sane-looking behavior and nothing more. Treat every one as "needs domain
expertise before this goes anywhere near production". ICEBURG's calibration
harness (kept in the Graveyard) found that expected-wait policies built only
from observable data cap near AUC 0.73 for separating callers who abandon
from callers who complete, against a synthetic cohort.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Optional

from Latent.ivr_perceived_wait_model import IvrPerceivedWaitDynamics


@dataclass
class IvrFrictionEngine:
    """
    Event-driven friction state for one caller.

    Governance Notes:
    - All floating point variables are subject to [0.0, 1.0] clamping.
    - Fields are dynamically mapped to ensure serializability.
    - The argument to update_after_step is never mutated; the recomputed
      frustration and perceived_wait come back in a new dynamics object.
    """

    # Core latent dimensions
    capability_score: float = 0.5
    patience: float = 0.5
    volatility: float = 0.3
    memory_flag: float = 0.0
    trust_scalar: float = 0.5

    # Emotional priors
    baseline_frustration: float = 0.1
    escalation_rate: float = 0.05

    # Routing priors
    menu_compliance: float = 0.7
    navigation_depth_prior: float = 0.4

    # Fraud / risk priors
    fraud_risk: float = 0.1

    # Friction-causality substrate (event-driven, replaces flat per-step drift)
    friction_count: int = 0          # running count of adverse events (fork-1 threshold state)
    step_index: int = 0              # monotone step counter; hash changes every call without saturating a signal
    trust_baseline: Optional[float] = None  # captured at construction; relief climbs toward this + overshoot, not toward 1.0
    peak_frustration: float = 0.0    # never-decaying high-water mark of frustration.
                                     # Relief pulls frustration back down, so a
                                     # caller who spiked to distress then got smoothed reads calm
                                     # at call-end -- exactly the caller an end-state check misses.
                                     # Recorded at termination as a SEVERITY signal for triage
                                     # (how bad), never as the abandonment classifier (whether):
                                     # classification is structural.

    # deterministic tunables -- NONE of these are validated against real call
    # data. They are placeholders that produce sane-looking behavior, not
    # calibrated constants. Treat every value below as "needs your domain
    # expertise before this goes anywhere near production," not as settled.
    _TOLERANCE: int = 1
    _FRICTION_CAP: int = 20
    _DILATION_K: float = 0.5
    _RELIEF_RATE: float = 0.1
    _TRUST_OVERSHOOT_CAP: float = 0.1   # max a well-handled recovery can lift trust above its call-start baseline
    _FRICTION_DECAY_PER_RELIEF: int = 1 # friction_count earned back per sustained relief step
    _WAIT_NORMALIZATION_SECONDS: float = 300.0  # actual_wait/expected_wait are assumed to arrive in seconds;
                                                  # this is the reference duration that maps to "feels maximal" (1.0)

    def __post_init__(self):
        if self.trust_baseline is None:
            self.trust_baseline = self.trust_scalar

    def reset_for_new_call(self):
        """
        Re-anchor state at a call boundary. NOT wired to anything yet -- the
        Simulator has no concept of "a new call started for this caller" to
        call this from. Exists so the object itself is capable of
        representing session boundaries; wiring it in is separate, later work.

        - trust_baseline re-anchors to the caller's trust AS OF NOW, so relief
          during the next call targets "recover from how this call went,"
          not "recover all the way back to day one."
        - friction_count resets to 0: tolerance for navigation friction is a
          per-call concept, not a lifetime scar.
        - memory_flag and trust_scalar themselves are NOT reset. Those are the
          actual relationship state and are meant to persist and compound
          across calls -- only the per-call tracking variables reset.
        """
        self.trust_baseline = self.trust_scalar
        self.friction_count = 0
        self.peak_frustration = 0.0

    def _clamp(self, val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """Enforces governance boundaries on all latent state updates."""
        return max(min_val, min(val, max_val))

    def to_dict(self) -> Dict[str, Any]:
        """Governance-safe dictionary serialization."""
        d = asdict(self)
        return {k: v for k, v in d.items() if not k.startswith("_")}  # keep tunables out of the hash surface

    def load_from_dict(self, data: Dict[str, Any]):
        """
        Dynamically update attributes based on incoming dictionary.

        Fixed 2026-07-01 in the original: previously ran self._clamp(value) --
        a [0.0,1.0] float clamp -- on EVERY field regardless of type. Verified
        corruption: friction_count=5 silently became 1.0 (wrong type AND wrong
        value, clamped into a range meant for emotional scalars); step_index=42
        became 1.0 the same way; trust_baseline=None crashed outright
        (TypeError comparing None to a float). This method is unused
        elsewhere, but it is exactly what a future replay/deserialization path
        would reach for given its own docstring.
        """
        for f in fields(self):
            if f.name not in data or f.name.startswith("_"):
                continue
            value = data[f.name]
            if f.name == "trust_baseline":
                setattr(self, f.name, None if value is None else self._clamp(float(value)))
            elif f.name == "friction_count":
                setattr(self, f.name, max(0, min(int(value), self._FRICTION_CAP)))
            elif f.name == "step_index":
                setattr(self, f.name, max(0, int(value)))
            else:
                # every remaining declared field is a bounded [0,1] float
                setattr(self, f.name, self._clamp(float(value)))

    def structural_hash(self) -> str:
        """
        Compute drift-detecting hash over ALL state, including step_index.

        - JSON sort_keys=True ensures consistent output across sessions.
        - This hash changes on every call to update_after_step, including
          quiet steps where nothing emotionally meaningful moved, because
          step_index always increments. For replay-equivalence (did two runs
          of the identical sequence produce identical results) that's correct.
          For "did anything real just happen," use content_hash() instead.
        """
        raw = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def content_hash(self) -> str:
        """
        Drift-detecting hash over emotionally-meaningful state only, excluding
        step_index. structural_hash alone can't distinguish "a step elapsed
        with no real movement" from "state genuinely changed," since
        step_index increments unconditionally. content_hash changing means
        frustration, trust, volatility, memory, or friction_count actually moved.
        """
        d = {k: v for k, v in self.to_dict().items() if k != "step_index"}
        raw = json.dumps(d, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def update_after_step(self, caller_dynamic: Any) -> IvrPerceivedWaitDynamics:
        """
        Update latent variables deterministically, driven by actual friction
        events rather than a flat per-step clock. Returns the recomputed
        dynamics; the argument is left untouched.

        Governance Notes:
        - Emotional channels (frustration, trust, volatility, memory) move only
          on adverse events or explicit resolution -- quiet steps move nothing,
          which prevents the saturation the old flat-drift version produced
          (memory pinned to 1.0 by step ~100 regardless of what happened).
        - perceived_wait is computed here. Frustration distorts perceived_wait,
          not the reverse -- a frustrated caller experiences the same clock
          time as longer.
        - Resolution triggers relief: frustration decays, trust recovers,
          volatility relaxes. Trust may end a call above its pre-call value
          (a well-handled failure can raise trust above no-failure baseline --
          [REDACTED_NAME]'s call: this is intended, not a bug).
        - memory_flag never decays. It is the permanent record that friction
          occurred, independent of whether the call ultimately felt resolved.
        """
        event    = int(getattr(caller_dynamic, "friction_event", 0))
        actual   = float(getattr(caller_dynamic, "actual_wait", 0.0))
        expected = float(getattr(caller_dynamic, "expected_wait", 0.0))
        frust_in = float(getattr(caller_dynamic, "frustration", 0.0))
        resolved = bool(getattr(caller_dynamic, "resolved", False))
        frustration = frust_in
        self.step_index += 1  # a step genuinely elapsed; unbounded, no encoder reads it
        trust_at_step_start = self.trust_scalar  # snapshot before any mutation, for the relief cap

        wait_overrun = 1 if actual > expected else 0
        friction_this_step = max(0, event + wait_overrun)  # guard: negative input doesn't corrupt count
        self.friction_count = min(self.friction_count + friction_this_step, self._FRICTION_CAP)
        over_tol = max(0, self.friction_count - self._TOLERANCE)

        # Friction and resolution are not mutually exclusive. A step can both
        # take a hit AND earn resolution credit -- verified case: caller
        # misroutes once, then the SAME step reaches the correct agent. With
        # an elif, the friction branch always won and relief silently never
        # fired. Now both apply, in sequence, so a rocky landing still costs
        # something but the resolution isn't erased.
        if friction_this_step > 0:
            # Convex accrual past tolerance: the first adverse event costs less
            # than the fifth. Drift only on friction steps.
            d_frust = self.escalation_rate * (1.0 + over_tol) * (1.0 - self.patience)
            frustration = frust_in + d_frust
            self.trust_scalar = self._clamp(self.trust_scalar - 0.01 * frustration)
            self.volatility   = self._clamp(self.volatility + 0.005 * (1.0 + over_tol) * (1.0 - self.patience))
            self.memory_flag  = self._clamp(self.memory_flag + 0.01 * (1.0 + over_tol))

        if resolved:
            # Relief climbs toward trust_baseline + a small bounded overshoot,
            # NOT toward 1.0. Reads whatever frustration/trust the friction
            # branch above just produced this step, so relief is credit ON TOP
            # of any same-step friction, not instead of it.
            frustration = max(0.0, frustration - self._RELIEF_RATE)
            relief_ceiling = self._clamp(self.trust_baseline + self._TRUST_OVERSHOOT_CAP)
            relieved = self._clamp(self.trust_scalar + self._RELIEF_RATE * (relief_ceiling - self.trust_scalar))
            # On a step that ALSO took friction, relief may at most undo this
            # step's trust damage -- it cannot lift trust above where it stood
            # at the START of this step. Without this cap, a misroute-then-
            # resolve step netted HIGHER trust (0.50977) than a step where
            # nothing happened at all (0.50000), because relief's magnitude
            # outweighs a single event's friction. That would reward
            # manufacturing a small fixable stumble over running clean -- the
            # "game the metric" family this substrate exists to prevent.
            # On a clean resolved step (no friction), trust_at_step_start ==
            # the trust before relief, so this cap is inert and relief is
            # unbounded up to the ceiling as before.
            if friction_this_step > 0:
                relieved = min(relieved, trust_at_step_start)
            self.trust_scalar = relieved
            self.volatility   = self._clamp(self.volatility - self._RELIEF_RATE * self.volatility)
            # friction_count decay: sustained resolution earns back
            # tolerance. Only decays on genuine resolution, not on merely quiet
            # steps -- you have to demonstrate things are working, not just wait.
            self.friction_count = max(0, self.friction_count - self._FRICTION_DECAY_PER_RELIEF)
        # else (no friction, not resolved): quiet step -- nothing moves.

        # Frustration distorts perceived_wait. actual_wait/expected_wait are
        # documented as arriving in seconds and are normalized here against a
        # reference duration rather than assumed pre-normalized by the caller.
        actual_norm = self._clamp(actual / self._WAIT_NORMALIZATION_SECONDS)
        perceived_wait = self._clamp(actual_norm * (1.0 + self._DILATION_K * frustration))

        # High-water mark, taken AFTER this step's frustration is final and
        # BEFORE any later relief can pull it back down. Monotone by
        # construction: max() never lowers it, and nothing else writes it.
        self.peak_frustration = max(
            self.peak_frustration,
            self._clamp(float(frustration)),
        )

        return IvrPerceivedWaitDynamics(
            perceived_wait=perceived_wait,
            frustration=frustration,
            friction_event=event,
            actual_wait=actual,
            expected_wait=expected,
            resolved=resolved,
        )
