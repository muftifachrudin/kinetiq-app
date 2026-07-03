"""Formalization of the founder's Fib+Gann entry-timing method (docs/prd.md
Section B.6 + the fib_gann_timing validation-harness design brief). Pure
functions over an explicit candle list -- no DB/ccxt coupling, no LangGraph
-- so this module can be called identically from a live signal path and
from a backtest's signal_runner.py (agent-orchestrator/validation/, not
yet built). Every function that walks time takes an `as_of` cutoff and
strictly ignores any candle after it: this is what "no-lookahead" means in
practice, not just a docstring promise -- see _filter_as_of().

Gann Fan (gann_fan_prices) uses the founder-confirmed calibration (design
brief Section 2c, Option 1): price_per_time_unit = swing_price_range /
swing_duration_in_bars, derived from the same swing leg detect_swings()
already produced -- one source of truth, not a separate calibration
system. VISUALLY VALIDATED against the founder's own TradingView chart
(3 Juli 2026) with TWO real drawings, uptrend and downtrend, using exact
(price, bar) coordinates TradingView itself stored (not visual estimates):
58005.0 @ bar 127 -> 60908.9 @ bar 177 (LOW origin, +58.078/bar), and
67284.8 @ bar 197 -> 62233.3 @ bar 214 (HIGH origin, -297.147/bar). Both
matched TradingView's own 1x1 line exactly -- see docs/prd.md's Fase 2
status for the full trail, including a red herring where a *parallel
channel* drawing (a separate tool, unrelated to Gann Fan) was initially
misread as the 1x1 line.

The second real drawing also surfaced a real generalization gann_base_rate
needed: basis_leg_start can be EITHER chronologically before OR after
pivot -- live/backtest usage always has it before (the swing immediately
preceding the most-recent confirmed pivot from detect_swings()), but the
founder's manual charting anchors the fan's origin at an older, more
significant swing and picks a LATER point just to set the slope. Both
orderings are supported now; only a shared index is rejected.

Market structure (BOS/CHoCH) is a separate skill --
see skills/strategy/market_structure.py, which plugs into
score_confluence()'s regime_alignment slot rather than living here.

Exit management (compute_stop_loss/compute_take_profit_levels/
build_exit_plan/passes_risk_reward_gate) implements design brief Section
5a-5c: structural SL behind the pivot swing, tiered TP from Gann-confluent
Fib extensions, and a binary R:R gate.

label_triple_barrier() implements Section 5d's labeling rule itself (walk
forward from entry, check which of TP1/SL/timeout is touched first) -- this
part needs no scikit-learn, it's a pure walk over an explicit candle list
like everything else here. It's the one function in this module that
deliberately looks at candles AFTER the entry decision on purpose (it's
labeling a completed signal's outcome, not generating a new one) -- the
no-lookahead/as_of discipline above is about signal generation, not this.
FITTING model weights against these labels (the brief's ConfluenceWeights
w1-w5 calibration, and trader_profile, PRD B.6b) is the separate
scikit-learn piece and does NOT live here -- see docs/fib-gann-validation-
brief.md Section 5d's verification note on why MARKOVIZ's pipeline isn't
reusable for that part.
"""

import dataclasses
import datetime
import enum

# Founder's actual Fibonacci levels (confirmed from live chart + settings,
# NOT textbook standard 0.236/0.382/0.5/0.618/0.786 + 1.272/1.618) -- a
# tighter set, especially in the 0.786-1.13 and 1.272-2.272 zones, used for
# more granular target/invalidation precision than the standard spacing
# gives. Callers may override per-instrument; these are the defaults.
# Re-verified against the founder's live TradingView Fib tool Style panel
# (3 Juli 2026) -- 3.618 was enabled there but missing from this set, added.
DEFAULT_FIB_RETRACEMENT_LEVELS = (0.382, 0.5, 0.618, 0.786, 0.886)
DEFAULT_FIB_EXTENSION_LEVELS = (1.13, 1.272, 1.414, 1.618, 2.0, 2.272, 2.618, 3.618)

# Weekly -> Daily -> 4h -> 1h, weight decreasing with timeframe size --
# confirmed to match the original PRD B.6 draft exactly, no correction
# needed (unlike the Fib levels above).
DEFAULT_TIMEFRAME_WEIGHTS = {"1w": 0.4, "1d": 0.3, "4h": 0.2, "1h": 0.1}

DEFAULT_ATR_PERIOD = 14
# 1.5-2x ATR(14) starting point per the design brief -- tuned later via
# trader_profile calibration (agreement rate vs trade_annotation), not
# fixed forever.
DEFAULT_ZIGZAG_ATR_MULTIPLIER = 1.75

# Design brief Section 5a: 0.25-0.5x ATR(14) buffer behind the basis swing,
# midpoint used as the starting default -- tuned later via calibration like
# DEFAULT_ZIGZAG_ATR_MULTIPLIER above, not fixed forever.
DEFAULT_SL_ATR_BUFFER_MULTIPLIER = 0.375

# Design brief Section 5c: binary R:R gate, default 1.5, configurable &
# calibrated later (same "start conservative, tune from real outcomes"
# pattern as MARKOVIZ's LIVE_META_MIN_PROBA staged rollout -- see
# docs/fib-gann-validation-brief.md Section 5d's verification note).
DEFAULT_MIN_RR_THRESHOLD = 1.5

# Fase 5 (docs/sonnet5-implementation-roadmap.md): a NEW upper cap on the
# R:R gate, tested as a controlled A/B variant rather than assumed correct
# -- an implausibly high R:R usually means take_profits[0] landed far from
# entry relative to a thin stop (e.g. a barely-confirmed pivot with a tiny
# ATR buffer), which is a fragile setup, not a genuinely great one. None
# (the default) preserves every existing caller's behavior exactly --
# passes_risk_reward_gate()/generate_signals() are both no-ops for this
# unless a caller opts in.
DEFAULT_MAX_RR_THRESHOLD = 5.0


def _require_utc(value: datetime.datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware (UTC): {value!r}")


@dataclasses.dataclass(frozen=True)
class Candle:
    ts: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        _require_utc(self.ts, "Candle.ts")


class SwingDirection(enum.Enum):
    HIGH = "high"
    LOW = "low"


@dataclasses.dataclass(frozen=True)
class SwingPoint:
    index: int  # position in the input candle list this swing was detected from
    ts: datetime.datetime
    price: float
    direction: SwingDirection
    wick_rejection_score: float  # 0-1, see wick_rejection_score()


def _filter_as_of(candles: list[Candle], as_of: datetime.datetime | None) -> list[Candle]:
    """Strict no-lookahead: drop every candle after as_of. Called at the
    top of every public function that walks time, not just once by the
    caller -- so passing the full candle history plus an as_of cutoff is
    always safe, whether this is live or inside a walk-forward backtest."""
    if as_of is None:
        return candles
    _require_utc(as_of, "as_of")
    return [c for c in candles if c.ts <= as_of]


def compute_atr(candles: list[Candle], period: int = DEFAULT_ATR_PERIOD) -> list[float | None]:
    """Wilder's smoothed ATR (TradingView's default ATR method) -- one
    value per candle, None for indices before the first full period is
    available. True range needs the previous candle's close, so index 0 is
    always None regardless of period.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if len(candles) < 2:
        return [None] * len(candles)

    true_ranges: list[float] = [0.0]  # placeholder for index 0, never read
    for i in range(1, len(candles)):
        c, prev = candles[i], candles[i - 1]
        tr = max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        true_ranges.append(tr)

    atr: list[float | None] = [None] * len(candles)
    if len(candles) <= period:
        return atr

    first_atr = sum(true_ranges[1 : period + 1]) / period
    atr[period] = first_atr
    for i in range(period + 1, len(candles)):
        atr[i] = (atr[i - 1] * (period - 1) + true_ranges[i]) / period

    return atr


def wick_rejection_score(candle: Candle, direction: SwingDirection) -> float:
    """0-1: how much of this candle's range is a wick opposite the swing
    direction. A swing LOW with a long lower wick indicates a stop-hunt/
    rejection already played out before the reversal -- the design brief's
    "bonus confidence" case. Returns 0.0 for a zero-range candle (no
    division by zero)."""
    full_range = candle.high - candle.low
    if full_range <= 0:
        return 0.0
    body_low = min(candle.open, candle.close)
    body_high = max(candle.open, candle.close)
    if direction is SwingDirection.LOW:
        wick = body_low - candle.low
    else:
        wick = candle.high - body_high
    return max(0.0, min(1.0, wick / full_range))


def detect_swings(
    candles: list[Candle],
    as_of: datetime.datetime | None = None,
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_multiplier: float = DEFAULT_ZIGZAG_ATR_MULTIPLIER,
) -> list[SwingPoint]:
    """ZigZag/ATR-based swing detection (design brief Section 3, resolved
    over Fractal-N-bar and manual-visual): a new swing is confirmed once
    price reverses from the current extreme by at least
    atr_multiplier * ATR(period), not on a fixed bar count -- so it scales
    with actual volatility instead of being an easy, uniform target for
    everyone using the same fixed lookback.

    No-lookahead: a swing is only ever confirmed using candles up to and
    including its own index, filtered first by as_of. The threshold ATR
    value used at each step is the ATR at the *current* candle being
    evaluated, never a future one.
    """
    candles = _filter_as_of(candles, as_of)
    if len(candles) < atr_period + 2:
        return []

    atr = compute_atr(candles, atr_period)
    swings: list[SwingPoint] = []

    # Direction is undetermined until the first confirmed reversal -- track
    # both a running highest-high and lowest-low candidate from the start
    # of the series until whichever one triggers a threshold-crossing
    # reversal first; that becomes the first confirmed swing.
    start_idx = atr_period  # first index with a real ATR value
    extreme_high_idx = extreme_low_idx = start_idx
    extreme_high_price = candles[start_idx].high
    extreme_low_price = candles[start_idx].low
    direction: SwingDirection | None = None

    for i in range(start_idx, len(candles)):
        c = candles[i]
        current_atr = atr[i]
        if current_atr is None:
            continue
        threshold = atr_multiplier * current_atr

        # Reversal is checked against the extreme as it stood *before* this
        # candle, then (only if no reversal fired) extended by this candle.
        # Checking against an extreme already-updated-by-this-candle
        # degenerates into comparing a single candle's own high-low range
        # to the threshold -- which trivially trips on every candle of a
        # sustained, purely monotonic move and produces a spurious pivot
        # each time, not a genuine multi-candle reversal. Caught by testing
        # against a synthetic strictly-monotonic decline, which should
        # yield exactly one HIGH and one LOW, not eight alternating pivots.
        if direction is None:
            # undetermined: whichever side trips its threshold first becomes
            # the first confirmed pivot; check HIGH first as a deterministic
            # tie-break on the (rare) candle where both would trip at once.
            if extreme_high_price - c.low >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_high_idx, SwingDirection.HIGH)
                extreme_low_price, extreme_low_idx = c.low, i
                continue
            if c.high - extreme_low_price >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_low_idx, SwingDirection.LOW)
                extreme_high_price, extreme_high_idx = c.high, i
                continue
            if c.high > extreme_high_price:
                extreme_high_price, extreme_high_idx = c.high, i
            if c.low < extreme_low_price:
                extreme_low_price, extreme_low_idx = c.low, i
        elif direction is SwingDirection.HIGH:
            if extreme_high_price - c.low >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_high_idx, SwingDirection.HIGH)
                extreme_low_price, extreme_low_idx = c.low, i
            elif c.high > extreme_high_price:
                extreme_high_price, extreme_high_idx = c.high, i
        elif direction is SwingDirection.LOW:
            if c.high - extreme_low_price >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_low_idx, SwingDirection.LOW)
                extreme_high_price, extreme_high_idx = c.high, i
            elif c.low < extreme_low_price:
                extreme_low_price, extreme_low_idx = c.low, i

    return swings


def _confirm_pivot(
    swings: list[SwingPoint], candles: list[Candle], pivot_idx: int, direction: SwingDirection
) -> SwingDirection:
    """Appends the confirmed pivot and returns the new direction to look
    for next (the opposite of the one just confirmed)."""
    pivot_candle = candles[pivot_idx]
    swings.append(
        SwingPoint(
            index=pivot_idx,
            ts=pivot_candle.ts,
            price=pivot_candle.high if direction is SwingDirection.HIGH else pivot_candle.low,
            direction=direction,
            wick_rejection_score=wick_rejection_score(pivot_candle, direction),
        )
    )
    return SwingDirection.LOW if direction is SwingDirection.HIGH else SwingDirection.HIGH


def compute_fib_levels(
    swing_low: float,
    swing_high: float,
    retracement_levels: tuple[float, ...] = DEFAULT_FIB_RETRACEMENT_LEVELS,
    extension_levels: tuple[float, ...] = DEFAULT_FIB_EXTENSION_LEVELS,
) -> dict[str, dict[float, float]]:
    """Retracement/extension prices for one swing leg: 0% = swing_low,
    100% = swing_high, extensions beyond 100% continue ABOVE swing_high --
    direction-agnostic in the sense that it doesn't matter which of the
    two prices was reached first chronologically, only which is
    numerically lower/higher.

    VERIFIED against the founder's real TradingView Fib Retracement tool
    (3 Juli 2026, BTCUSDT 1h): exact (price, bar) coordinates from the
    tool's own Coordinates panel (60919.9 @ bar 160, 58029.2 @ bar 328)
    plus 9 labeled level prices read straight off the chart fit
    `swing_low + level * leg` with R^2 = 1.000000 -- this is NOT the
    formula this function used before (previously `swing_high -
    level * leg`, which was backwards: it matched the founder's chart
    only up to sign, putting retracements in the same 0-100% price band
    but extensions BELOW swing_low instead of above it). See
    docs/fib-gann-validation-brief.md Section 2a's verification note.
    """
    if swing_high <= swing_low:
        raise ValueError(f"swing_high ({swing_high}) must be greater than swing_low ({swing_low})")

    leg = swing_high - swing_low
    retracements = {level: swing_low + level * leg for level in retracement_levels}
    extensions = {level: swing_low + level * leg for level in extension_levels}
    return {"retracement": retracements, "extension": extensions}


# 9 standard Gann Fan angles, all generated simultaneously from one pivot
# (design brief Section 2b, confirmed from the founder's TradingView
# settings -- every checkbox active, not a config-selected subset). Values
# are the multiplier applied to the base 1x1 rate; Gann's "AxB" notation
# reads "A price units per B time units", so "2x1" (steeper than 1x1) is
# 2.0 and "1x2" (flatter) is 0.5.
GANN_ANGLES = {
    "1x8": 1 / 8,
    "1x4": 1 / 4,
    "1x3": 1 / 3,
    "1x2": 1 / 2,
    "1x1": 1.0,
    "2x1": 2.0,
    "3x1": 3.0,
    "4x1": 4.0,
    "8x1": 8.0,
}


def gann_base_rate(pivot: SwingPoint, basis_leg_start: SwingPoint) -> float:
    """price_per_time_unit for the 1x1 (45-degree) angle -- design brief
    Section 2c, Option 1 (founder-confirmed): swing_price_range /
    swing_duration_in_bars.

    basis_leg_start can be EITHER before or after `pivot` chronologically
    -- both are real usages, confirmed from the founder's own TradingView
    drawings (3 Juli 2026): live/backtest signal generation always has
    basis_leg_start = the swing immediately preceding the most-recent
    confirmed pivot (basis_leg_start.index < pivot.index, from
    detect_swings() output), but the founder's manual charting instead
    anchors the fan's origin (`pivot`) at an older, structurally
    significant swing and picks a LATER point only to define the slope
    (basis_leg_start.index > pivot.index) -- e.g. a downtrend fan
    anchored at an older high, sloped using a more recent low. Both were
    verified against exact (price, bar) coordinates read from
    TradingView's own Gann Fan tool -- see docs/fib-gann-validation-
    brief.md Section 2c. Only a shared index (duration of zero, no time
    elapsed between the two points) is rejected -- there's no rate to
    derive from a single point.
    """
    duration = abs(pivot.index - basis_leg_start.index)
    if duration == 0:
        raise ValueError(f"pivot and basis_leg_start must not share the same index ({pivot.index})")
    price_range = abs(pivot.price - basis_leg_start.price)
    return price_range / duration


def gann_fan_prices(
    pivot: SwingPoint,
    basis_leg_start: SwingPoint,
    bar_index: int,
    angles: dict[str, float] = GANN_ANGLES,
) -> dict[str, float]:
    """Price of each Gann angle at bar_index -- an absolute candle index
    in the same series pivot/basis_leg_start came from (can be before, at,
    or after pivot.index; a fan is a straight line through all time, not
    just forward-projecting). A fan from a LOW pivot projects upward
    (rising support lines, the expected-continuation direction after a
    low); a fan from a HIGH pivot projects downward (falling resistance
    lines after a high).
    """
    base_rate = gann_base_rate(pivot, basis_leg_start)
    sign = 1.0 if pivot.direction is SwingDirection.LOW else -1.0
    bars_from_pivot = bar_index - pivot.index
    return {label: pivot.price + sign * base_rate * ratio * bars_from_pivot for label, ratio in angles.items()}


def swing_quality(
    swing: SwingPoint,
    candles: list[Candle],
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_multiplier: float = DEFAULT_ZIGZAG_ATR_MULTIPLIER,
) -> float:
    """0-1: two equally-weighted components (design brief Section 4):
    displacement of the pivot candle's own true range relative to the ATR-
    scaled threshold that confirmed it (a pivot formed on an unusually
    violent candle is more decisive evidence than one that just barely
    crossed the threshold over several quiet candles), and recency (a
    swing near the end of the series, closer to `as_of`, is more relevant
    to a current entry-timing decision than a stale one further back).
    """
    atr = compute_atr(candles, atr_period)
    if swing.index == 0 or swing.index >= len(atr) or atr[swing.index] is None or atr[swing.index] == 0:
        return 0.0

    pivot, prev = candles[swing.index], candles[swing.index - 1]
    true_range = max(pivot.high - pivot.low, abs(pivot.high - prev.close), abs(pivot.low - prev.close))
    displacement_ratio = min(1.0, true_range / (atr_multiplier * atr[swing.index]))

    recency = (swing.index + 1) / len(candles)
    return 0.5 * displacement_ratio + 0.5 * recency


def volume_confirmation(swing: SwingPoint, candles: list[Candle], lookback: int = 20) -> float:
    """0-1+: the displacement candle's volume vs. the rolling average
    volume of the `lookback` candles before it. A swing formed on
    below-average volume is weaker evidence of real participant
    conviction."""
    if swing.index >= len(candles):
        raise ValueError("swing.index out of range for candles")
    window_start = max(0, swing.index - lookback)
    window = candles[window_start : swing.index]
    if not window:
        return 0.0
    avg_volume = sum(c.volume for c in window) / len(window)
    if avg_volume <= 0:
        return 0.0
    return candles[swing.index].volume / avg_volume


@dataclasses.dataclass(frozen=True)
class ConfluenceWeights:
    swing_quality: float = 0.20
    fib_gann_confluence: float = 0.30
    regime_alignment: float = 0.15
    volume_confirmation: float = 0.15
    wick_rejection: float = 0.10
    # Fase 2 (docs/sonnet5-implementation-roadmap.md) -- htf_bias.py's
    # htf_alignment_score(), a new slot alongside regime_alignment, not
    # blended into it (Daily/4h trend agreement is a distinct signal from
    # BOS/CHoCH structure alignment). Adding this field took 0.05 from
    # swing_quality (0.25->0.20) to keep the sum at 1.0 -- an initial,
    # undisputed rebalancing since none of these weights are fit yet
    # (Fase 3 decides the real numbers via logistic regression).
    htf_alignment: float = 0.10

    def __post_init__(self) -> None:
        total = (
            self.swing_quality
            + self.fib_gann_confluence
            + self.regime_alignment
            + self.volume_confirmation
            + self.wick_rejection
            + self.htf_alignment
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"ConfluenceWeights must sum to 1.0, got {total}")


def score_confluence(
    swing: SwingPoint,
    candles: list[Candle],
    fib_confluence: float,
    regime_alignment: float | None = None,
    htf_alignment: float | None = None,
    weights: ConfluenceWeights = ConfluenceWeights(),
) -> float:
    """Design brief Section 4's confidence formula:
        confidence = w1*swing_quality + w2*fib_gann_confluence
                   + w3*regime_alignment + w4*volume_confirmation
                   + w5*wick_rejection_score + w6*htf_alignment

    fib_confluence is passed in rather than computed here -- callers should
    now pass fib_gann_confluence_score()'s output (Fib+Gann combined, per
    the design brief) rather than fib_confluence_score() alone, since a
    Gann pivot/basis pair is available. This function doesn't compute it
    itself because doing so would require a Gann pivot/basis pair as an
    additional parameter here even when the caller has no swing pair to
    anchor one yet (e.g. scoring the very first swing in a series).

    regime_alignment defaults to a neutral 1.0 (no penalty, no boost) --
    market_regime.py (PRD B.6) doesn't exist yet, so there's no real
    regime signal to align against. This is an explicit stand-in, not a
    considered "neutral is usually right" judgment call.

    htf_alignment (Fase 2, htf_bias.py) defaults the same way -- neutral
    1.0 when the caller has no HTF bias signal to pass at all, distinct
    from htf_bias.htf_alignment_score()'s OWN neutral value (0.5) for when
    a real HTF bias computation comes back UNDEFINED. Callers that DO have
    an htf_bias.py signal (signal_runner.generate_signals() always does)
    should pass its real 0-1 output here, same convention regime_alignment
    already follows with market_structure.structure_alignment_score().

    weights are NOT fit from data yet (design brief: should eventually be
    logistic-regression-fit against trade_annotation outcomes, reusing the
    trader_profile calibration pipeline -- B.6b, which itself doesn't
    exist yet since it needs real annotated trade history). The defaults
    above are a reasonable starting point, not a calibrated result.
    """
    if regime_alignment is None:
        regime_alignment = 1.0
    if htf_alignment is None:
        htf_alignment = 1.0

    vol_conf = min(1.0, volume_confirmation(swing, candles) / 2.0)  # normalize: 2x avg volume -> full score
    quality = swing_quality(swing, candles)

    return (
        weights.swing_quality * quality
        + weights.fib_gann_confluence * fib_confluence
        + weights.regime_alignment * regime_alignment
        + weights.volume_confirmation * vol_conf
        + weights.wick_rejection * swing.wick_rejection_score
        + weights.htf_alignment * htf_alignment
    )


def _nearest_level_confluence(prices: list[float], reference_price: float, atr_value: float) -> float:
    """0-1: how close reference_price sits to the nearest of `prices`,
    normalized by ATR (design brief Section 4: overlap > 0.5x ATR should
    NOT count as confluence -- it's coincidence, not a genuine level
    interaction). Returns 0.0 if no level is within that band, or if
    `prices` is empty."""
    if atr_value <= 0 or not prices:
        return 0.0
    nearest_distance = min(abs(reference_price - p) for p in prices)
    band = 0.5 * atr_value
    if nearest_distance >= band:
        return 0.0
    return 1.0 - (nearest_distance / band)


def fib_confluence_score(
    fib_levels: dict[str, dict[float, float]],
    reference_price: float,
    atr_value: float,
) -> float:
    """Fib-only confluence -- see fib_gann_confluence_score for the
    combined Fib+Gann version the design brief actually calls for
    (Section 2b: confluence must check overlap against all 9 fan lines,
    not just Fib levels alone). Kept standalone since it's still useful on
    its own (e.g. before a Gann pivot/basis pair is available)."""
    all_prices = list(fib_levels["retracement"].values()) + list(fib_levels["extension"].values())
    return _nearest_level_confluence(all_prices, reference_price, atr_value)


def fib_gann_confluence_score(
    fib_levels: dict[str, dict[float, float]],
    gann_prices: dict[str, float],
    reference_price: float,
    atr_value: float,
) -> float:
    """Design brief Section 2b: the candidate level pool for confluence
    must include each of the 9 Gann angle prices at the current bar
    (gann_fan_prices' output), not just the static Fib levels -- same
    normalize-by-ATR, no-overlap-beyond-0.5x-ATR rule as
    fib_confluence_score, just a bigger pool of levels to check distance
    against. This is what score_confluence's `fib_confluence` parameter
    should be filled with now that Gann Fan is implemented."""
    all_prices = (
        list(fib_levels["retracement"].values())
        + list(fib_levels["extension"].values())
        + list(gann_prices.values())
    )
    return _nearest_level_confluence(all_prices, reference_price, atr_value)


def confluence_across_timeframes(
    scores_by_timeframe: dict[str, float],
    weights: dict[str, float] = DEFAULT_TIMEFRAME_WEIGHTS,
) -> float:
    """Weighted average across timeframes present in scores_by_timeframe,
    scaled to 0-100 for the final entry-timing signal (PRD B.6: "skor
    0-100"). scores_by_timeframe values must each be 0-1 (e.g. the output
    of fib_confluence_score/score_confluence) -- passing already-0-100
    values here double-scales the result silently (no range check is
    possible without also rejecting legitimate values near 1.0).

    Missing timeframes are excluded and the remaining weights
    renormalized, rather than silently treating a missing timeframe as a
    zero score (which would understate confluence just because e.g.
    weekly data isn't available yet for a new listing).
    """
    present = {tf: w for tf, w in weights.items() if tf in scores_by_timeframe}
    total_weight = sum(present.values())
    if total_weight <= 0:
        return 0.0
    weighted_sum = sum(scores_by_timeframe[tf] * w for tf, w in present.items())
    return 100.0 * weighted_sum / total_weight


class TradeDirection(enum.Enum):
    LONG = "long"
    SHORT = "short"


def trade_direction_from_pivot(pivot: SwingPoint) -> TradeDirection:
    """A LOW pivot is a just-confirmed support -- the expected continuation
    is upward (LONG). A HIGH pivot is just-confirmed resistance -- SHORT.
    Same directional convention gann_fan_prices() already uses for its fan
    projection sign (LOW pivot -> upward, HIGH pivot -> downward) -- kept
    consistent rather than introducing a second rule for the same idea."""
    return TradeDirection.LONG if pivot.direction is SwingDirection.LOW else TradeDirection.SHORT


def compute_stop_loss(
    pivot: SwingPoint,
    atr_value: float,
    atr_buffer_multiplier: float = DEFAULT_SL_ATR_BUFFER_MULTIPLIER,
) -> float:
    """Design brief Section 5a: SL placed behind the pivot swing itself --
    the same swing that anchors fib/gann (see gann_fan_prices), not a
    separate parameter, so a broken pivot always means a broken trade
    premise. The ATR buffer keeps the SL off the exact swing price (an
    obvious level, prone to a wick-hunt stop run) rather than an arbitrary
    fixed distance. Direction is derived from pivot.direction via
    trade_direction_from_pivot -- LONG (LOW pivot) places SL below,
    SHORT (HIGH pivot) places it above.
    """
    if atr_value <= 0:
        raise ValueError("atr_value must be positive")
    buffer = atr_buffer_multiplier * atr_value
    direction = trade_direction_from_pivot(pivot)
    return pivot.price - buffer if direction is TradeDirection.LONG else pivot.price + buffer


class StopLossMethod(enum.Enum):
    """Fase 5 (docs/sonnet5-implementation-roadmap.md) A/B variant --
    ATR_BUFFER is the existing/default method (compute_stop_loss above),
    NEXT_FIB_LEVEL is the new candidate build_exit_plan can be told to use
    instead. Both are real, tested code paths -- neither is assumed to win
    the experiment; the roadmap's acceptance criterion is a walk-forward
    decision written up in a brief, not a hardcoded default flip here."""

    ATR_BUFFER = "atr_buffer"
    NEXT_FIB_LEVEL = "next_fib_level"


def compute_stop_loss_next_fib_level(
    pivot: SwingPoint,
    basis_leg_start: SwingPoint,
    extension_levels: tuple[float, ...] = DEFAULT_FIB_EXTENSION_LEVELS,
) -> float:
    """Fase 5 SL variant: instead of a fixed ATR buffer behind the pivot,
    place the SL one Fib extension ratio's worth further behind it -- the
    "next fib level" past the swing itself, using the SAME leg-projection
    formula compute_take_profit_levels() already uses for TPs on the
    opposite side of price (this is genuinely the mirror-image
    calculation: "one extension increment beyond the swing, away from the
    leg" is the same geometry whether it's serving as a downstream TP for
    the opposite direction or an upstream SL for this one).

    min(extension_levels) is used as "the next" level -- the smallest
    extension ratio configured (nearest to the swing, e.g. 1.13) rather
    than an arbitrary fixed one, so this stays consistent with whatever
    extension ladder the rest of a call site is already using. Unlike
    compute_stop_loss(), this does not take atr_value at all -- the whole
    point of this variant is replacing the ATR-based distance with a
    structural (leg-based) one instead, not combining both.
    """
    if not extension_levels:
        raise ValueError("extension_levels must not be empty")
    leg = abs(pivot.price - basis_leg_start.price)
    if leg <= 0:
        raise ValueError("pivot and basis_leg_start must have different prices")
    next_level = min(extension_levels)
    direction = trade_direction_from_pivot(pivot)
    swing_low = min(pivot.price, basis_leg_start.price)
    swing_high = max(pivot.price, basis_leg_start.price)
    if direction is TradeDirection.LONG:
        return swing_low - (next_level - 1.0) * leg
    return swing_high + (next_level - 1.0) * leg


def compute_take_profit_levels(
    pivot: SwingPoint,
    basis_leg_start: SwingPoint,
    gann_prices: dict[str, float],
    atr_value: float,
    extension_levels: tuple[float, ...] = DEFAULT_FIB_EXTENSION_LEVELS,
) -> tuple[float, ...]:
    """Design brief Section 5b: tiered TP targets, nearest-first --
    take_profit_levels[0] is TP1 (partial exit), the rest are successive
    trailing targets after TP1 is hit. Only extension levels that are ALSO
    confluent with a Gann fan line (gann_fan_prices' output) count as
    valid targets, per the brief -- not just the nearest extension level
    regardless of Gann overlap. Returns an empty tuple if no extension
    level clears the confluence band (no valid TP1 -- see
    passes_risk_reward_gate, which treats that as a failing signal).

    This does NOT reuse compute_fib_levels' extension dict directly:
    compute_fib_levels (as of 3 Juli 2026's real-chart fix) always
    projects extensions ABOVE swing_high, which is correct for LONG but
    not directly usable for SHORT. The LONG branch below is now
    mathematically identical to compute_fib_levels' own formula (verified
    against real TradingView coordinates -- see compute_fib_levels'
    docstring). The SHORT branch (extensions below swing_low) is a
    mirror-image assumption for symmetry, NOT yet verified against a real
    SHORT-oriented TradingView Fib drawing -- flag this if a future
    validation round surfaces a mismatch, same as the LONG/extension
    direction bug this replaced.
    """
    leg = abs(pivot.price - basis_leg_start.price)
    if leg <= 0:
        raise ValueError("pivot and basis_leg_start must have different prices")
    direction = trade_direction_from_pivot(pivot)
    swing_low = min(pivot.price, basis_leg_start.price)
    swing_high = max(pivot.price, basis_leg_start.price)

    gann_values = list(gann_prices.values())
    confluent_prices = []
    for level in sorted(extension_levels):  # ascending ratio == nearest-to-leg-edge first
        if direction is TradeDirection.LONG:
            price = swing_high + (level - 1.0) * leg
        else:
            price = swing_low - (level - 1.0) * leg
        if _nearest_level_confluence(gann_values, price, atr_value) > 0.0:
            confluent_prices.append(price)

    return tuple(confluent_prices)


@dataclasses.dataclass(frozen=True)
class ExitPlan:
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profits: tuple[float, ...]  # nearest-first; take_profits[0] is TP1
    risk_reward_ratio: float | None  # None when take_profits is empty (no TP1 to measure against)


def build_exit_plan(
    pivot: SwingPoint,
    basis_leg_start: SwingPoint,
    entry_price: float,
    atr_value: float,
    gann_prices: dict[str, float],
    extension_levels: tuple[float, ...] = DEFAULT_FIB_EXTENSION_LEVELS,
    sl_atr_buffer_multiplier: float = DEFAULT_SL_ATR_BUFFER_MULTIPLIER,
    sl_method: StopLossMethod = StopLossMethod.ATR_BUFFER,
) -> ExitPlan:
    """Bundles 5a (SL) + 5b (tiered TP) into one exit plan and computes the
    R:R ratio 5c's gate checks. entry_price is a separate parameter from
    pivot.price since a real signal enters on the current close, not
    necessarily exactly at the pivot price. Position-sizing for TP1's
    partial exit (brief 5b: "porsi configurable, default mis. 50%") is an
    execution-layer concern, not represented here -- this module only
    computes price levels.

    sl_method (Fase 5) defaults to ATR_BUFFER -- the existing behavior,
    unchanged for every caller that predates this option. NEXT_FIB_LEVEL
    swaps in compute_stop_loss_next_fib_level() instead; sl_atr_buffer_
    multiplier is simply unused in that branch (kept as a parameter here
    rather than split into two functions, since every other input stays
    identical between the two variants).
    """
    direction = trade_direction_from_pivot(pivot)
    if sl_method is StopLossMethod.NEXT_FIB_LEVEL:
        stop_loss = compute_stop_loss_next_fib_level(pivot, basis_leg_start, extension_levels)
    else:
        stop_loss = compute_stop_loss(pivot, atr_value, sl_atr_buffer_multiplier)
    take_profits = compute_take_profit_levels(pivot, basis_leg_start, gann_prices, atr_value, extension_levels)

    risk = abs(entry_price - stop_loss)
    risk_reward_ratio = None
    if take_profits and risk > 0:
        risk_reward_ratio = abs(take_profits[0] - entry_price) / risk

    return ExitPlan(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profits=take_profits,
        risk_reward_ratio=risk_reward_ratio,
    )


def passes_risk_reward_gate(
    exit_plan: ExitPlan,
    min_rr_threshold: float = DEFAULT_MIN_RR_THRESHOLD,
    max_rr_threshold: float | None = None,
) -> bool:
    """Design brief Section 5c: a binary gate, separate from confidence
    scoring -- a signal with a high confluence score but a bad R:R
    structure is SKIPPED entirely, never down-weighted. False whenever
    risk_reward_ratio is None (no TP1 was found at all).

    max_rr_threshold (Fase 5, docs/sonnet5-implementation-roadmap.md): an
    OPTIONAL upper cap, tested as a controlled A/B variant against the
    existing uncapped behavior -- None (the default) means no upper cap at
    all, identical to this function's behavior before Fase 5. When set, an
    implausibly high R:R (see DEFAULT_MAX_RR_THRESHOLD's comment) is
    rejected the same way a too-low one already is -- this is still a
    single binary gate, not two different policies."""
    if exit_plan.risk_reward_ratio is None:
        return False
    if exit_plan.risk_reward_ratio < min_rr_threshold:
        return False
    if max_rr_threshold is not None and exit_plan.risk_reward_ratio > max_rr_threshold:
        return False
    return True


class BarrierOutcome(enum.IntEnum):
    """+1/-1/0 exactly as design brief Section 5d specifies -- an IntEnum
    so this is directly usable as the raw ML label (compares equal to,
    and behaves as, its int value) while still being named for
    readability at call sites."""

    STOP_LOSS = -1
    TIMEOUT = 0
    TAKE_PROFIT = 1


@dataclasses.dataclass(frozen=True)
class TripleBarrierLabel:
    outcome: BarrierOutcome
    exit_price: float
    exit_ts: datetime.datetime
    bars_held: int  # count of granular candles consumed up to and including the exit candle
    return_pct: float  # direction-adjusted realized return; positive means profit for either direction
    # True only when outcome is TIMEOUT and granular_candles ran out before
    # max_holding_bars was reached -- a right-censored sample (we don't
    # actually know what would have happened next), not a genuine "held
    # the full window and nothing triggered" case. Downstream calibration
    # should treat these differently (e.g. exclude samples too close to
    # the end of available history), not mix them in as equally valid.
    censored: bool


def _barrier_touch(candle: Candle, direction: TradeDirection, take_profit: float, stop_loss: float) -> tuple[bool, bool]:
    if direction is TradeDirection.LONG:
        return candle.high >= take_profit, candle.low <= stop_loss
    return candle.low <= take_profit, candle.high >= stop_loss


def _build_triple_barrier_label(
    outcome: BarrierOutcome,
    exit_price: float,
    exit_candle: Candle,
    bars_held: int,
    exit_plan: ExitPlan,
    censored: bool,
) -> TripleBarrierLabel:
    if exit_plan.direction is TradeDirection.LONG:
        return_pct = (exit_price - exit_plan.entry_price) / exit_plan.entry_price
    else:
        return_pct = (exit_plan.entry_price - exit_price) / exit_plan.entry_price
    return TripleBarrierLabel(
        outcome=outcome,
        exit_price=exit_price,
        exit_ts=exit_candle.ts,
        bars_held=bars_held,
        return_pct=return_pct,
        censored=censored,
    )


def label_triple_barrier(
    exit_plan: ExitPlan,
    granular_candles: list[Candle],
    max_holding_bars: int,
) -> TripleBarrierLabel:
    """Design brief Section 5d: labels a signal's realized outcome by
    walking forward through candles after entry, checking which of three
    barriers is touched first -- upper barrier = TP1 (exit_plan.
    take_profits[0], per 5b), lower barrier = exit_plan.stop_loss (per
    5a), vertical barrier = max_holding_bars candles elapsed with neither
    touched. This is what the confluence-weight and trader_profile
    (PRD B.6b) fitting pipeline consumes -- NOT naive "price went up =
    win" labeling.

    granular_candles should be MORE GRANULAR than the signal's own
    timeframe where possible (brief: a 4h signal should be labeled
    walking 1h/15m candles, not 4h candles) so the TP-vs-SL-touched-first
    order is accurate rather than assumed from one coarse candle's OHLC.
    Caller's responsibility to slice/align this to start at (or
    immediately after) the entry decision -- ExitPlan carries no
    timestamp to anchor against, so this always starts from
    granular_candles[0].

    Same-candle double-touch (both TP and SL within one candle's
    high-low range) is scored STOP_LOSS unconditionally -- the brief's
    explicit worst-case rule for when intrabar touch order can't be
    determined. This applies at whatever granularity is fed in, not only
    when granular data is literally unavailable: even a genuinely
    granular candle can still span both barriers, and the same
    conservative assumption is the safe one either way.
    """
    if not granular_candles:
        raise ValueError("granular_candles must not be empty")
    if max_holding_bars <= 0:
        raise ValueError("max_holding_bars must be positive")
    if not exit_plan.take_profits:
        raise ValueError("exit_plan has no take_profits -- can't label without an upper barrier (TP1)")

    take_profit = exit_plan.take_profits[0]
    stop_loss = exit_plan.stop_loss
    window = granular_candles[:max_holding_bars]

    for i, candle in enumerate(window):
        hit_tp, hit_sl = _barrier_touch(candle, exit_plan.direction, take_profit, stop_loss)
        if hit_sl:  # covers both "SL only" and "both touched this candle" -- brief's worst-case rule
            return _build_triple_barrier_label(BarrierOutcome.STOP_LOSS, stop_loss, candle, i + 1, exit_plan, censored=False)
        if hit_tp:
            return _build_triple_barrier_label(BarrierOutcome.TAKE_PROFIT, take_profit, candle, i + 1, exit_plan, censored=False)

    timeout_candle = window[-1]
    censored = len(granular_candles) < max_holding_bars
    return _build_triple_barrier_label(
        BarrierOutcome.TIMEOUT, timeout_candle.close, timeout_candle, len(window), exit_plan, censored=censored
    )
