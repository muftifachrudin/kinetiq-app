"""F4 (docs/sonnet5-implementation-roadmap.md) -- funding/OI/long-short
context, the graduation of validation/deep_dive_2026_07/coinglass_pull.py +
cg_analysis.py's one-off analysis into a tested, pure-function skill (same
"anything worth keeping graduates into fib_gann_backtest/ with tests"
convention Fase 1-3 followed -- see that folder's README.md).

Pure function, no DB/HTTP coupling -- same discipline as every other module
here. Caller supplies an already-fetched daily record history (CoinGlass
Hobbyist daily data + native funding_rate/open_interest, F0c); this module
never calls the CoinGlass API or touches a DB itself. Fetch/cache-to-DB is a
separate, later ingestion concern, not this module's job.

Two categories, deliberately kept separate -- this split is the roadmap's
explicit instruction AND an empirical finding from the July deep-dive
(CLAUDE.md's own memory entry): "OI-fuel is a coincident/volatility-regime
indicator, not a directional predictor (strong same-day replication,
weak H+1, zero effect on trade outcomes). Don't wire it as a direction
weight."
 - DIRECTION candidates (funding_contrarian_alignment, global_ls_contrarian_
   alignment, top_vs_global_alignment, liq_cascade_flag): meant to be dumped
   onto signal_runner.Signal as per-factor fields, for fit_weights.py's L1
   fit to assign a real coefficient to (may land at ~0 -- a valid,
   reportable finding, not a bug, same "boleh nol" philosophy Fase 3 uses).
 - fuel_quadrant: NEVER a direction feature. Exposed only for
   position_sizing.py's high_vol_flag (sizing/buffer context) and any
   future volatility-regime consumer -- never fit against trade direction.

No-lookahead: every value here is computed for a signal firing on
`target_date` using ONLY records with date < target_date (the roadmap's
"semua dari HARI SEBELUM entry" requirement) -- compute_derivatives_context
enforces this structurally (it never reads a record whose date >=
target_date, even if the caller's list includes one), rather than trusting
every caller to have pre-filtered. Percentiles are a TRAILING window (up to
365 daily records ending the day before target_date), not the full
available history -- a percentile computed against the whole future dataset
would leak exactly like an unbounded lookback would elsewhere in this
codebase (fib_gann_timing's ZigZag/ATR conventions make the same choice).

liq_cascade_flag is deliberately an UNSIGNED magnitude feature (0.0/1.0),
not a direction-aligned score like the other three -- there is no
established directional theory in this codebase for which way a long-
liquidation cascade predicts price will move next (the deep-dive found
"weak H+1, zero effect on trade outcomes" for this whole family), so
fabricating a directional sign for it here would be inventing a claim the
data doesn't support. It's exactly the same treatment swing_quality/
volume_confirmation get in fit_weights.FEATURE_NAMES: a magnitude/context
signal, direction-agnostic, and the regression's own coefficient sign (not
a hardcoded assumption here) is what determines whatever relationship
actually exists.

funding_contrarian_alignment / global_ls_contrarian_alignment DO get a
direction-signed transform, because the roadmap cites an established
contrarian theory for both ("sinyal contrarian... >=p90 BTC -> -0.45% H+1"):
extreme crowded positioning (high percentile) is a bearish tailwind (fade
the crowd), extreme opposite crowding (low percentile) a bullish one. The
same theory underlies top_vs_global_divergence (fade-the-crowd via smart-
money vs retail disagreement), so it gets a signed transform too.
"""

import dataclasses
import datetime
import enum

import fib_gann_timing as fgt

DEFAULT_PERCENTILE_WINDOW_DAYS = 365
# Roadmap: "long-liq kemarin > p90 tahunan" -- an initial, undisputed
# starting point (same "initial numbers are free" convention as every other
# new constant in this validation harness), not a fitted value.
LIQ_CASCADE_PERCENTILE_THRESHOLD = 0.90
# Divergence (top_ls_ratio - global_ls_ratio) is an unbounded raw
# difference of two ratios (each typically ~0.5-3 in CoinGlass's data) --
# this scales it into the same 0-1 alignment convention every other factor
# uses. A starting point, not fitted.
DEFAULT_DIVERGENCE_SCALE = 0.5


class FuelQuadrant(enum.Enum):
    """price/OI direction the day before entry -- context/sizing ONLY, see
    module docstring for why this is never a direction-fitting feature."""

    UP_OI_UP = "up_oi_up"
    UP_OI_DOWN = "up_oi_down"
    DOWN_OI_UP = "down_oi_up"
    DOWN_OI_DOWN = "down_oi_down"


@dataclasses.dataclass(frozen=True)
class DailyDerivativesRecord:
    """One coin's one calendar day of CoinGlass Hobbyist + native
    funding_rate/open_interest data (see validation/deep_dive_2026_07/
    coinglass_pull.py for the exact endpoints/params this is sourced from).
    long_liq_usd/short_liq_usd stay Optional -- a day CoinGlass returns no
    liquidation row for is real missing data, not a legitimate zero (same
    right-censoring discipline shadow_pair.py/metrics.py use elsewhere)."""

    date: datetime.date
    price_close: float
    oi_close: float
    funding_rate: float  # this day's funding rate, raw fraction (not %)
    global_ls_ratio: float  # global account long/short ratio
    top_ls_ratio: float  # top-trader position long/short ratio
    long_liq_usd: float | None = None
    short_liq_usd: float | None = None


@dataclasses.dataclass(frozen=True)
class DerivativesContext:
    funding_percentile_365d: float  # 0-1
    global_ls_percentile_365d: float  # 0-1
    top_vs_global_divergence: float  # top_ls_ratio - global_ls_ratio, signed, unbounded
    liq_cascade_flag: bool
    fuel_quadrant: FuelQuadrant
    window_size: int  # trailing records actually used (< window_days early in a series)


def _percentile_rank(value: float, population: list[float]) -> float:
    """Fraction of `population` strictly less than `value`, plus half the
    ties -- the standard midpoint percentile-rank convention. Avoids a
    value that equals every historical entry (e.g. a flat funding stretch)
    silently reading as either the 0th or 100th percentile depending on
    which comparison direction happened to be used."""
    if not population:
        raise ValueError("population must not be empty")
    less = sum(1 for p in population if p < value)
    equal = sum(1 for p in population if p == value)
    return (less + 0.5 * equal) / len(population)


def compute_derivatives_context(
    records: list[DailyDerivativesRecord],
    target_date: datetime.date,
    window_days: int = DEFAULT_PERCENTILE_WINDOW_DAYS,
) -> DerivativesContext:
    """Computes context for a signal firing on `target_date`, using ONLY
    records strictly before it (enforced here, not just documented --
    target_date's own record, if present in `records`, is never read).
    Needs at least 2 qualifying records (today-relative-to-target's own
    snapshot plus at least one prior day to diff price/OI against)."""
    prior = sorted((r for r in records if r.date < target_date), key=lambda r: r.date)
    if len(prior) < 2:
        raise ValueError(f"need at least 2 records strictly before {target_date}, got {len(prior)}")
    window = prior[-window_days:]

    latest, previous = window[-1], window[-2]
    price_ret = (latest.price_close - previous.price_close) / previous.price_close
    oi_ret = (latest.oi_close - previous.oi_close) / previous.oi_close

    if price_ret > 0:
        fuel_quadrant = FuelQuadrant.UP_OI_UP if oi_ret > 0 else FuelQuadrant.UP_OI_DOWN
    else:
        fuel_quadrant = FuelQuadrant.DOWN_OI_UP if oi_ret > 0 else FuelQuadrant.DOWN_OI_DOWN

    funding_percentile = _percentile_rank(latest.funding_rate, [r.funding_rate for r in window])
    gls_percentile = _percentile_rank(latest.global_ls_ratio, [r.global_ls_ratio for r in window])
    divergence = latest.top_ls_ratio - latest.global_ls_ratio

    liq_cascade = False
    if latest.long_liq_usd is not None:
        long_liq_population = [r.long_liq_usd for r in window if r.long_liq_usd is not None]
        if len(long_liq_population) >= 2:
            liq_cascade = _percentile_rank(latest.long_liq_usd, long_liq_population) >= LIQ_CASCADE_PERCENTILE_THRESHOLD

    return DerivativesContext(
        funding_percentile_365d=funding_percentile,
        global_ls_percentile_365d=gls_percentile,
        top_vs_global_divergence=divergence,
        liq_cascade_flag=liq_cascade,
        fuel_quadrant=fuel_quadrant,
        window_size=len(window),
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def funding_contrarian_alignment(direction: fgt.TradeDirection, funding_percentile: float) -> float:
    """High funding percentile = crowded/expensive longs = bearish
    contrarian tailwind (roadmap: ">=p90 BTC -> -0.45% H+1") -- supportive
    of SHORT. Low percentile = crowded shorts = supportive of LONG. Linear
    in percentile, 0.5 at the midpoint (neutral), symmetric by direction."""
    return funding_percentile if direction is fgt.TradeDirection.SHORT else 1.0 - funding_percentile


def global_ls_contrarian_alignment(direction: fgt.TradeDirection, gls_percentile: float) -> float:
    """Same fade-the-crowd logic as funding_contrarian_alignment, applied
    to the global account long/short ratio's own percentile: crowded
    retail long positioning (high percentile) is a bearish contrarian
    signal, supportive of SHORT."""
    return gls_percentile if direction is fgt.TradeDirection.SHORT else 1.0 - gls_percentile


def top_vs_global_alignment(direction: fgt.TradeDirection, divergence: float, scale: float = DEFAULT_DIVERGENCE_SCALE) -> float:
    """Positive divergence (top traders relatively MORE long than the
    global/retail crowd) is a bullish smart-money-vs-retail signal --
    supportive of LONG. Negative divergence supports SHORT. `scale`
    normalizes the raw ratio-difference into the 0-1 convention; values
    beyond +-scale clamp rather than extrapolate past full alignment."""
    signed = divergence if direction is fgt.TradeDirection.LONG else -divergence
    return _clamp01(0.5 + 0.5 * (signed / scale))
