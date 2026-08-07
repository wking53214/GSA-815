"""Coverage for SimpleRLTrainer.choose_action's selection behavior (F3).

choose_action previously computed a softmax and then selected via
argmax, making the policy deterministic-greedy with no exploration.
Nothing in the repo called the method and no test touched it, so the
defect was invisible in both directions. These tests pin the fixed
behavior so it cannot silently regress to greedy again.

Every test asserts. None returns a value and none swallows an
exception -- the same antipattern already corrected kernel-side, kept
out of new code here deliberately.
"""

import os
import sys

import array_ops as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from Engines.simple_rl_trainer import SimpleRLTrainer


def _skewed_trainer(seed=42):
    """A trainer whose policy is deliberately lopsided.

    Weights are overwritten after construction so the action
    distribution is a known ~0.88/0.12 rather than the near-coin-flip
    that 0.01-scale random init produces. A near-uniform policy cannot
    distinguish sampling from the distribution against sampling
    uniformly, so the skew is what gives the frequency test its teeth.
    """
    trainer = SimpleRLTrainer(state_dim=10, action_dim=2, lr=0.001, seed=seed)
    trainer.policy_weights = np.array([[0.2] * 10, [0.0] * 10])
    state = np.array([1.0] * 10)
    return trainer, state


def test_exploration_reaches_both_actions():
    """The core F3 regression: sampling must try the unfavored action.

    Under the old argmax selection this loop returned action 0 all 200
    times regardless of seed, so a single observation of action 1 is
    enough to prove the greedy path is gone.
    """
    trainer, state = _skewed_trainer()
    seen = {trainer.choose_action(state)[0] for _ in range(200)}
    assert seen == {0, 1}, f"expected both actions to be sampled, saw {seen}"


def test_sampling_frequency_tracks_the_distribution():
    """Sampling must follow the softmax, not just be noisy.

    Proving both actions appear is not enough on its own -- a uniform
    coin flip would also pass that. This pins the observed rate to the
    probability the policy actually reports.
    """
    trainer, state = _skewed_trainer()
    _, reported_prob, _ = trainer.choose_action(state, explore=False)

    draws = [trainer.choose_action(state)[0] for _ in range(4000)]
    observed = draws.count(0) / len(draws)

    assert abs(observed - reported_prob) < 0.03, (
        f"sampled rate {observed:.3f} should track reported probability "
        f"{reported_prob:.3f}"
    )


def test_explore_false_is_greedy_and_deterministic():
    """Evaluation behavior stays available and stays stable."""
    trainer, state = _skewed_trainer()
    actions = {trainer.choose_action(state, explore=False)[0] for _ in range(50)}
    assert actions == {0}, f"greedy selection should never vary, saw {actions}"


def test_greedy_matches_argmax_of_the_reported_probability():
    """explore=False must pick the highest-probability action.

    Guards against the greedy branch drifting away from the softmax it
    is supposed to be reading.
    """
    trainer, state = _skewed_trainer()
    action, prob, _ = trainer.choose_action(state, explore=False)

    logits = trainer.policy_weights @ state
    logits = logits - np.max(logits)
    expected = np.exp(logits) / np.sum(np.exp(logits))

    assert action == int(np.argmax(expected))
    assert abs(prob - float(expected[action])) < 1e-9


def test_same_seed_reproduces_the_same_explored_sequence():
    """Exploration must not cost reproducibility.

    Sampling introduces randomness, and randomness that cannot be
    replayed from a seed would make any RL result unauditable. Two
    identically-seeded trainers must walk the same path.
    """
    trainer_a, state = _skewed_trainer(seed=7)
    trainer_b, _ = _skewed_trainer(seed=7)

    seq_a = [trainer_a.choose_action(state)[0] for _ in range(100)]
    seq_b = [trainer_b.choose_action(state)[0] for _ in range(100)]

    assert seq_a == seq_b, "same seed must produce the same action sequence"


def test_different_seeds_diverge():
    """Confirms the seed is actually driving sampling.

    Without this, a hardcoded or shared generator would still pass the
    reproducibility test above while ignoring the seed entirely.
    """
    trainer_a, state = _skewed_trainer(seed=7)
    trainer_b, _ = _skewed_trainer(seed=99)

    seq_a = [trainer_a.choose_action(state)[0] for _ in range(200)]
    seq_b = [trainer_b.choose_action(state)[0] for _ in range(200)]

    assert seq_a != seq_b, "different seeds should not produce identical sequences"


def test_returned_probability_belongs_to_the_chosen_action():
    """The reported probability must describe the action actually taken.

    choose_action returns (action, prob, value) together, and a
    mismatch here would corrupt any downstream log-probability the
    caller records for that decision.
    """
    trainer, state = _skewed_trainer()

    logits = trainer.policy_weights @ state
    logits = logits - np.max(logits)
    expected = np.exp(logits) / np.sum(np.exp(logits))

    for _ in range(100):
        action, prob, _ = trainer.choose_action(state)
        assert abs(prob - float(expected[action])) < 1e-9


def test_action_is_a_plain_int():
    """Both branches return a usable index.

    The old argmax path returned a numpy integer. Callers index
    policy_weights and Trajectory.action with this value, so the two
    branches returning different types would be a latent trap.
    """
    trainer, state = _skewed_trainer()
    assert type(trainer.choose_action(state)[0]) is int
    assert type(trainer.choose_action(state, explore=False)[0]) is int
