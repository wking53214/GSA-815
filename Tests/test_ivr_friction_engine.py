"""IvrFrictionEngine: determinism, clamping, and the anti-gaming properties
the engine exists to guarantee.

Ported from ICEBURG's test_latent.py when that repo was buried. ICEBURG's
engine mutated the dynamics object it was given; this one returns a new
IvrPerceivedWaitDynamics and leaves its argument alone, so these tests read
results from the return value and thread frustration through by hand.
"""
import pytest

from Latent.ivr_friction_engine import IvrFrictionEngine
from Latent.ivr_perceived_wait_model import IvrPerceivedWaitDynamics


def dyn(**kw):
    return IvrPerceivedWaitDynamics(**kw)


def test_trust_baseline_anchors_at_construction():
    p = IvrFrictionEngine(trust_scalar=0.42)
    assert p.trust_baseline == pytest.approx(0.42)


def test_update_leaves_its_argument_untouched():
    p = IvrFrictionEngine()
    d = dyn(friction_event=2, actual_wait=120.0, expected_wait=10.0, frustration=0.3)
    snapshot = (d.perceived_wait, d.frustration, d.friction_event,
                d.actual_wait, d.expected_wait, d.resolved)
    out = p.update_after_step(d)
    assert (d.perceived_wait, d.frustration, d.friction_event,
            d.actual_wait, d.expected_wait, d.resolved) == snapshot
    assert out is not d
    assert out.frustration > d.frustration


def test_quiet_step_moves_nothing():
    """Event-driven, not flat-drift: the old version pinned memory to 1.0 by
    step ~100 regardless of what happened."""
    p = IvrFrictionEngine()
    before = p.to_dict()
    p.update_after_step(dyn())
    after = p.to_dict()
    for k in ("trust_scalar", "volatility", "memory_flag", "friction_count"):
        assert before[k] == after[k], k
    assert after["step_index"] == before["step_index"] + 1


def test_friction_raises_frustration_and_costs_trust():
    p = IvrFrictionEngine()
    out = p.update_after_step(dyn(friction_event=1))
    assert out.frustration > 0.0
    assert p.friction_count == 1
    assert p.trust_scalar < 0.5


def test_friction_accrual_grows_past_tolerance():
    """The first adverse event costs less than the fifth: below _TOLERANCE the
    accrual is flat, and past it each further event costs strictly more."""
    p = IvrFrictionEngine()
    deltas = []
    for _ in range(5):
        out = p.update_after_step(dyn(friction_event=1))
        deltas.append(out.frustration)
    assert deltas == sorted(deltas)
    assert deltas[-1] > deltas[0]
    # Accrual is linear in the overage past tolerance, by construction:
    # escalation_rate * (1 + over_tol) * (1 - patience).
    steps = [round(b - a, 12) for a, b in zip(deltas, deltas[1:])]
    assert len(set(steps)) == 1 and steps[0] > 0


def test_friction_count_is_capped():
    p = IvrFrictionEngine()
    for _ in range(100):
        p.update_after_step(dyn(friction_event=1))
    assert p.friction_count == p._FRICTION_CAP


def test_negative_friction_event_cannot_corrupt_the_count():
    p = IvrFrictionEngine()
    p.update_after_step(dyn(friction_event=-5))
    assert p.friction_count == 0


def test_wait_overrun_counts_as_one_friction_event():
    p = IvrFrictionEngine()
    p.update_after_step(dyn(actual_wait=60.0, expected_wait=10.0))
    assert p.friction_count == 1
    q = IvrFrictionEngine()
    q.update_after_step(dyn(actual_wait=10.0, expected_wait=10.0))
    assert q.friction_count == 0


def test_memory_flag_never_decays():
    """memory_flag is the permanent record that friction occurred,
    independent of whether the call ultimately felt resolved."""
    p = IvrFrictionEngine()
    p.update_after_step(dyn(friction_event=1))
    marked = p.memory_flag
    assert marked > 0.0
    for _ in range(20):
        p.update_after_step(dyn(resolved=True))
    assert p.memory_flag >= marked


def test_friction_and_resolution_can_both_apply_in_one_step():
    """Verified case: caller misroutes once, then the SAME step reaches the
    correct agent. An elif meant the friction branch always won and relief
    silently never fired."""
    p = IvrFrictionEngine()
    out = p.update_after_step(dyn(friction_event=1, resolved=True))
    # memory_flag is the permanent, un-relievable record that the hit landed.
    assert p.memory_flag > 0.0
    # Relief then applied ON TOP of it, rather than the friction branch
    # silently winning: this step's frustration is fully relieved and the
    # earned tolerance is handed back (_FRICTION_DECAY_PER_RELIEF).
    assert out.frustration == pytest.approx(0.0)
    assert p.friction_count == 0
    # And the cap holds: relief undid this step's trust damage but did not
    # lift trust above where it stood at the start of the step.
    assert p.trust_scalar == pytest.approx(IvrFrictionEngine().trust_scalar)


def test_relief_cannot_exceed_step_start_trust_when_friction_occurred():
    """Anti-gaming: a misroute-then-resolve step must not net HIGHER trust
    than a step where nothing happened at all -- that would reward
    manufacturing a small fixable stumble over running clean."""
    clean = IvrFrictionEngine()
    clean.update_after_step(dyn())

    rocky = IvrFrictionEngine()
    rocky.update_after_step(dyn(friction_event=1, resolved=True))

    assert rocky.trust_scalar <= clean.trust_scalar


def test_clean_resolution_can_end_above_baseline_by_a_bounded_amount():
    """A well-handled recovery may lift trust above its call-start baseline,
    but never past baseline + _TRUST_OVERSHOOT_CAP."""
    p = IvrFrictionEngine()
    for _ in range(200):
        p.update_after_step(dyn(resolved=True))
    ceiling = p.trust_baseline + p._TRUST_OVERSHOOT_CAP
    assert p.trust_scalar > p.trust_baseline
    assert p.trust_scalar <= ceiling + 1e-12


def test_trust_never_leaves_the_unit_interval():
    p = IvrFrictionEngine()
    for i in range(200):
        p.update_after_step(dyn(friction_event=i % 3, resolved=bool(i % 2)))
        assert 0.0 <= p.trust_scalar <= 1.0
        assert 0.0 <= p.volatility <= 1.0
        assert 0.0 <= p.memory_flag <= 1.0


def test_peak_frustration_is_a_never_decaying_high_water_mark():
    """The caller who spiked to distress then got smoothed by relief before
    quitting is exactly the caller a final-value check misses."""
    p = IvrFrictionEngine()
    frustration = 0.0
    for _ in range(6):
        out = p.update_after_step(dyn(friction_event=2, frustration=frustration))
        frustration = min(1.0, out.frustration + 0.25)
    peak = p.peak_frustration
    assert peak > 0.0
    for _ in range(30):
        p.update_after_step(dyn(resolved=True, frustration=0.0))
    assert p.peak_frustration == peak


def test_reset_for_new_call_clears_per_call_state_only():
    p = IvrFrictionEngine()
    p.update_after_step(dyn(friction_event=1))
    p.memory_flag = 0.7
    trust = p.trust_scalar
    p.reset_for_new_call()
    assert p.friction_count == 0
    assert p.peak_frustration == 0.0
    assert p.trust_baseline == pytest.approx(trust)
    assert p.memory_flag == 0.7          # relationship state persists
    assert p.trust_scalar == pytest.approx(trust)


def test_step_index_is_monotone():
    p = IvrFrictionEngine()
    for i in range(1, 25):
        p.update_after_step(dyn())
        assert p.step_index == i


def test_perceived_wait_is_dilated_by_frustration():
    """A frustrated caller experiences the same clock time as longer."""
    calm, cross = IvrFrictionEngine(), IvrFrictionEngine()
    oc = calm.update_after_step(dyn(actual_wait=150.0, frustration=0.0))
    ox = cross.update_after_step(dyn(actual_wait=150.0, frustration=0.9))
    assert ox.perceived_wait > oc.perceived_wait


def test_perceived_wait_normalizes_seconds_instead_of_saturating():
    """A 30 second wait must not read as maximal: actual_wait is seconds and
    is divided by _WAIT_NORMALIZATION_SECONDS before dilation."""
    p = IvrFrictionEngine()
    out = p.update_after_step(dyn(actual_wait=30.0, expected_wait=30.0))
    assert 0.0 < out.perceived_wait < 0.2


def test_tunables_are_excluded_from_the_serialized_surface():
    d = IvrFrictionEngine().to_dict()
    assert not [k for k in d if k.startswith("_")]


def test_hashes_are_deterministic_across_instances():
    a, b = IvrFrictionEngine(), IvrFrictionEngine()
    assert a.content_hash() == b.content_hash()
    assert a.structural_hash() == b.structural_hash()


def test_quiet_step_moves_structural_hash_but_not_content_hash():
    """Two explicitly labelled hashes, because 'the hash changed' has to mean
    something specific. structural_hash covers ALL state including
    step_index, so it moves on every step -- that is what replay equivalence
    needs. content_hash excludes step_index, so it moves only when something
    emotionally meaningful actually did."""
    p = IvrFrictionEngine()
    s0, c0 = p.structural_hash(), p.content_hash()
    p.update_after_step(dyn())                  # quiet step
    assert p.structural_hash() != s0            # a step elapsed
    assert p.content_hash() == c0               # nothing real happened
    p.update_after_step(dyn(friction_event=1))  # real step
    assert p.content_hash() != c0


def test_load_from_dict_preserves_int_and_none_types():
    """Previously ran _clamp() over everything: friction_count=5 silently
    became 1.0 and trust_baseline=None crashed outright."""
    p = IvrFrictionEngine()
    p.load_from_dict({"friction_count": 5, "step_index": 42,
                      "trust_baseline": None, "volatility": 1.7})
    assert p.friction_count == 5 and isinstance(p.friction_count, int)
    assert p.step_index == 42 and isinstance(p.step_index, int)
    assert p.trust_baseline is None
    assert p.volatility == pytest.approx(1.0)      # float clamping still bounds


def test_identical_inputs_produce_identical_trajectories():
    """Replay safety: identical inputs -> identical latent evolution."""
    script = [dict(friction_event=i % 3, resolved=bool(i % 4 == 0),
                   actual_wait=float(i), expected_wait=2.0) for i in range(40)]
    outs = []
    for _ in range(2):
        p = IvrFrictionEngine()
        for s in script:
            p.update_after_step(dyn(**s))
        outs.append(p.content_hash())
    assert outs[0] == outs[1]
