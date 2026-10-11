import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from queue_staffing_bayes_integration import (
    BayesianIntentEngine, IVRCapacity, integrate_all_three
)


def _erlang_b_closed_form(lines: int, traffic: float) -> float:
    """Independent check: the textbook formula, not the recurrence under test."""
    num = traffic ** lines / math.factorial(lines)
    den = sum(traffic ** k / math.factorial(k) for k in range(lines + 1))
    return num / den


def test_erlang_b_known_value():
    # 10 lines carrying 8 erlangs: about 12.2% of calls find every line busy.
    b = IVRCapacity.erlang_b(10, 8.0)
    assert abs(b - 0.121661) < 1e-4, f"expected Erlang B ~0.1217, got {b:.6f}"
    assert abs(b - _erlang_b_closed_form(10, 8.0)) < 1e-9


def test_erlang_b_edges():
    assert IVRCapacity.erlang_b(10, 0.0) == 0.0  # no load, nothing blocked
    assert IVRCapacity.erlang_b(0, 8.0) == 1.0   # no lines, everything blocked


def test_lines_needed_meets_target_exactly():
    # 8 erlangs at 1% blocking needs 15 lines. 14 lines is just over the target.
    n = IVRCapacity.lines_needed(8.0, 0.01)
    assert n == 15, f"expected 15 lines, got {n}"
    assert _erlang_b_closed_form(n, 8.0) <= 0.01
    assert _erlang_b_closed_form(n - 1, 8.0) > 0.01


def test_lines_needed_zero_traffic():
    assert IVRCapacity.lines_needed(0.0, 0.01) == 0


def test_lines_needed_rejects_bad_target():
    for bad in (0.0, 1.0, -0.1, 1.5):
        try:
            IVRCapacity.lines_needed(8.0, bad)
        except ValueError:
            continue
        raise AssertionError(f"max_blocking={bad} should be rejected")


def test_bayes_intent():
    # Unreachable URL -> forces in-memory-only, so this stays deterministic
    # regardless of whether a real Redis happens to be available (CI now
    # runs one; see Tests/test_bayes_learning_loop.py for the Redis-backed
    # persistence coverage).
    bayes = BayesianIntentEngine(redis_url="redis://localhost:1/0")

    # Simulate 20 billing calls: 15 resolved, 5 not
    for i in range(15):
        bayes.observe_outcome("billing", True, 4.0)
    for i in range(5):
        bayes.observe_outcome("billing", False, 6.0)

    posterior = bayes.get_posterior("billing")

    assert posterior.success_rate == 0.75, f"Should be 75% success, got {posterior.success_rate}"
    assert posterior.confidence > 0.15, "Should have some confidence"
    assert posterior.avg_handling_time < 5.0, "Avg should decrease with more successes"


def test_full_integration():
    call_outcomes = [
        {"intent": "billing", "resolved": True, "handle_time": 4.0},
        {"intent": "billing", "resolved": True, "handle_time": 5.0},
        {"intent": "technical", "resolved": False, "handle_time": 10.0},
        {"intent": "technical", "resolved": True, "handle_time": 8.0},
    ]

    result = integrate_all_three(call_outcomes)

    assert "staffing_adjustments" not in result, "Agent staffing was removed"
    assert {"billing", "technical"} <= set(result["bayesian_posteriors"])


if __name__ == "__main__":
    tests = [
        test_erlang_b_known_value,
        test_erlang_b_edges,
        test_lines_needed_meets_target_exactly,
        test_lines_needed_zero_traffic,
        test_lines_needed_rejects_bad_target,
        test_bayes_intent,
        test_full_integration,
    ]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"PASSED {fn.__name__}")
        except Exception as exc:
            print(f"FAILED {fn.__name__}: {exc}")
            failed.append(fn.__name__)
    sys.exit(1 if failed else 0)
