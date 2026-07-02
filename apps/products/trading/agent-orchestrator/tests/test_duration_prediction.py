import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import duration_prediction as dp  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402

LONG = fgt.TradeDirection.LONG
SHORT = fgt.TradeDirection.SHORT
TP = fgt.BarrierOutcome.TAKE_PROFIT
SL = fgt.BarrierOutcome.STOP_LOSS
TIMEOUT = fgt.BarrierOutcome.TIMEOUT


def sample(outcome=TP, bars_held=5, direction=LONG, confidence=0.6, censored=False) -> dp.DurationSample:
    return dp.DurationSample(outcome=outcome, bars_held=bars_held, direction=direction, confidence=confidence, censored=censored)


# --- confidence_bucket ---


def test_confidence_bucket_boundaries():
    assert dp.confidence_bucket(0.49) == "low"
    assert dp.confidence_bucket(0.5) == "medium"
    assert dp.confidence_bucket(0.74) == "medium"
    assert dp.confidence_bucket(0.75) == "high"


# --- build_duration_profile ---


def test_build_duration_profile_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        dp.build_duration_profile([])


def test_build_duration_profile_preserves_samples():
    samples = [sample(), sample(outcome=SL)]
    profile = dp.build_duration_profile(samples)
    assert profile.samples == tuple(samples)


# --- predict_duration ---


def test_predict_duration_no_historical_basis_returns_empty_estimate():
    profile = dp.build_duration_profile([sample(direction=LONG)])
    estimate = dp.predict_duration(profile, direction=SHORT, confidence=0.6)
    assert estimate.sample_count == 0
    assert estimate.outcome_probabilities == {}
    assert estimate.bars_held_p25 is None
    assert estimate.bars_held_median is None
    assert estimate.bars_held_p75 is None
    assert estimate.matched_bucket == "none"


def test_predict_duration_matches_direction_and_confidence_bucket():
    samples = [
        sample(direction=LONG, confidence=0.8, bars_held=3, outcome=TP),
        sample(direction=LONG, confidence=0.8, bars_held=5, outcome=TP),
        sample(direction=LONG, confidence=0.3, bars_held=20, outcome=SL),  # different bucket -- must not pollute
    ]
    profile = dp.build_duration_profile(samples)
    estimate = dp.predict_duration(profile, direction=LONG, confidence=0.78)
    assert estimate.matched_bucket == "direction+high"
    assert estimate.sample_count == 2
    assert estimate.outcome_probabilities == {TP: 1.0}
    assert estimate.bars_held_median == pytest.approx(4.0)


def test_predict_duration_falls_back_to_direction_only_when_bucket_empty():
    samples = [sample(direction=LONG, confidence=0.3, bars_held=10, outcome=TP)]
    profile = dp.build_duration_profile(samples)
    estimate = dp.predict_duration(profile, direction=LONG, confidence=0.9)  # "high" bucket has no samples
    assert estimate.matched_bucket == "direction_only"
    assert estimate.sample_count == 1


def test_predict_duration_excludes_censored_samples():
    samples = [
        sample(direction=LONG, confidence=0.6, bars_held=5, outcome=TP, censored=False),
        sample(direction=LONG, confidence=0.6, bars_held=999, outcome=TIMEOUT, censored=True),
    ]
    profile = dp.build_duration_profile(samples)
    estimate = dp.predict_duration(profile, direction=LONG, confidence=0.6)
    assert estimate.sample_count == 1
    assert estimate.bars_held_median == pytest.approx(5.0)


def test_predict_duration_single_sample_gives_degenerate_quantiles_not_a_crash():
    profile = dp.build_duration_profile([sample(direction=LONG, confidence=0.6, bars_held=7)])
    estimate = dp.predict_duration(profile, direction=LONG, confidence=0.6)
    assert estimate.sample_count == 1
    assert estimate.bars_held_p25 == estimate.bars_held_median == estimate.bars_held_p75 == pytest.approx(7.0)


def test_predict_duration_outcome_probabilities_sum_to_one():
    samples = [
        sample(direction=LONG, confidence=0.6, outcome=TP, bars_held=3),
        sample(direction=LONG, confidence=0.6, outcome=SL, bars_held=2),
        sample(direction=LONG, confidence=0.6, outcome=SL, bars_held=4),
        sample(direction=LONG, confidence=0.6, outcome=TIMEOUT, bars_held=10),
    ]
    profile = dp.build_duration_profile(samples)
    estimate = dp.predict_duration(profile, direction=LONG, confidence=0.6)
    assert sum(estimate.outcome_probabilities.values()) == pytest.approx(1.0)
    assert estimate.outcome_probabilities[SL] == pytest.approx(0.5)
    assert estimate.outcome_probabilities[TP] == pytest.approx(0.25)
    assert estimate.outcome_probabilities[TIMEOUT] == pytest.approx(0.25)


def test_predict_duration_direction_isolation_long_and_short_never_mix():
    samples = [sample(direction=LONG, bars_held=100, confidence=0.6), sample(direction=SHORT, bars_held=1, confidence=0.6)]
    profile = dp.build_duration_profile(samples)
    long_estimate = dp.predict_duration(profile, direction=LONG, confidence=0.6)
    assert long_estimate.sample_count == 1
    assert long_estimate.bars_held_median == pytest.approx(100.0)
