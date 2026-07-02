"""Founder request (3 Juli 2026): predict not just direction/target but how
long a trade takes to resolve -- capability #1 of the "trade journey
prediction" roadmap (docs/fib-gann-validation-brief.md Section 9), chosen
by the founder as the next round to build.

**Standing gate-vs-score principle applies (Section 10)**: predict_duration()
is INFORMATIONAL ONLY -- it never rejects a signal. Empirical evidence for
why this matters: on real BTC/USDT data, a single existing gate (R:R >= 1.5)
already rejects 96% of genuine fib/gann touches (70 touches -> 3 signals).
Adding this as a new hard gate ("only signal if predicted duration is
short enough") would compound that toward zero signals. It returns an
estimate a caller can attach to a Signal (bar-count percentiles + outcome
probabilities), exactly like `confidence` is a score, not a filter.

Deterministic-now/ML-fit-later (same sequencing as ConfluenceWeights and
level_strength.py): build_duration_profile() aggregates historical
fib_gann_timing.TripleBarrierLabel samples into empirical bar-count
distributions and outcome-probability counts -- plain counting and
quantiles, no fitted model. A future round can replace the confidence-
bucket lookup with a real regression once trade_annotation volume exists.

NOT wired into signal_runner.generate_signals() this round -- doing that
would require a historical resolved-signal dataset (walking forward,
labeling each past signal via label_triple_barrier()), which is
trade_simulator.py's job (validation/README.md: not built yet). This
module only provides the aggregator/predictor; wiring it into live signal
generation is a later round once that pipeline exists.

Scoped to STATIC bucketing on (direction, confidence) for this round --
richer bucketing (session, confluence sub-scores) can be added once real
volume justifies finer buckets; too many buckets with too little data
just produces noisy single-sample "distributions", not a real one.
"""

import dataclasses
import statistics

import fib_gann_timing as fgt

# (low, high) edges splitting confidence into 3 buckets: LOW < 0.5 <= MEDIUM
# < 0.75 <= HIGH. Matches the observed real-data confidence range from
# signal_runner.py (0.59-0.78 across the 3 real BTC signals) without being
# so fine-grained that every bucket ends up with a single sample.
DEFAULT_CONFIDENCE_BUCKET_EDGES = (0.5, 0.75)


def confidence_bucket(confidence: float, bucket_edges: tuple[float, float] = DEFAULT_CONFIDENCE_BUCKET_EDGES) -> str:
    low, high = bucket_edges
    if confidence < low:
        return "low"
    if confidence < high:
        return "medium"
    return "high"


@dataclasses.dataclass(frozen=True)
class DurationSample:
    """One resolved signal's outcome, as produced by
    fib_gann_timing.label_triple_barrier() plus the signal-level metadata
    (direction, confidence) needed to bucket it. Caller builds these --
    this module has no opinion on how a Signal became a TripleBarrierLabel."""

    outcome: fgt.BarrierOutcome
    bars_held: int
    direction: fgt.TradeDirection
    confidence: float
    # Excluded from percentile/probability math below -- a right-censored
    # sample's bars_held is "ran out of data", not a genuine resolution
    # time, same reasoning as label_triple_barrier()'s own censored field.
    censored: bool


@dataclasses.dataclass(frozen=True)
class DurationProfile:
    samples: tuple[DurationSample, ...]


def build_duration_profile(samples: list[DurationSample]) -> DurationProfile:
    if not samples:
        raise ValueError("samples must not be empty")
    return DurationProfile(samples=tuple(samples))


@dataclasses.dataclass(frozen=True)
class DurationEstimate:
    sample_count: int  # how many historical samples this estimate is based on -- 0 means no historical basis at all
    outcome_probabilities: dict[fgt.BarrierOutcome, float]  # empirical P(outcome), sums to 1.0 when sample_count > 0
    bars_held_p25: float | None
    bars_held_median: float | None
    bars_held_p75: float | None
    matched_bucket: str  # "direction+confidence_bucket" or "direction_only" (fallback) or "none"


def _quantiles_or_degenerate(bars: list[int]) -> tuple[float, float, float]:
    if len(bars) == 1:
        value = float(bars[0])
        return value, value, value
    p25, median, p75 = statistics.quantiles(bars, n=4, method="inclusive")
    return p25, median, p75


def predict_duration(
    profile: DurationProfile,
    direction: fgt.TradeDirection,
    confidence: float,
    bucket_edges: tuple[float, float] = DEFAULT_CONFIDENCE_BUCKET_EDGES,
) -> DurationEstimate:
    """Looks up historical samples matching (direction, confidence bucket)
    first; if that bucket is empty, falls back to direction-only (an
    explicit, visible fallback -- not a silent one, callers can tell which
    happened from matched_bucket). Returns sample_count=0 (no bars_held/
    probabilities) rather than fabricating a number when there's no
    historical basis at all for this direction -- an empty estimate is
    honest, a guessed one isn't."""
    target_bucket = confidence_bucket(confidence, bucket_edges)
    same_direction = [s for s in profile.samples if s.direction is direction and not s.censored]

    bucketed = [s for s in same_direction if confidence_bucket(s.confidence, bucket_edges) == target_bucket]
    if bucketed:
        matching, matched_bucket = bucketed, f"direction+{target_bucket}"
    elif same_direction:
        matching, matched_bucket = same_direction, "direction_only"
    else:
        matching, matched_bucket = [], "none"

    if not matching:
        return DurationEstimate(
            sample_count=0,
            outcome_probabilities={},
            bars_held_p25=None,
            bars_held_median=None,
            bars_held_p75=None,
            matched_bucket=matched_bucket,
        )

    total = len(matching)
    outcome_counts: dict[fgt.BarrierOutcome, int] = {}
    for s in matching:
        outcome_counts[s.outcome] = outcome_counts.get(s.outcome, 0) + 1
    outcome_probabilities = {outcome: count / total for outcome, count in outcome_counts.items()}

    bars = sorted(s.bars_held for s in matching)
    p25, median, p75 = _quantiles_or_degenerate(bars)

    return DurationEstimate(
        sample_count=total,
        outcome_probabilities=outcome_probabilities,
        bars_held_p25=p25,
        bars_held_median=median,
        bars_held_p75=p75,
        matched_bucket=matched_bucket,
    )
