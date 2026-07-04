"""Design brief Section 6: metrics.py -- PF/Sharpe/max-drawdown computed
from trade_simulator.SimulatedTrade records, funding-aware per the brief's
explicit "Metrics -- funding-aware (WAJIB, bukan opsional)" requirement:

- Every metric is computed BOTH gross (fib_gann_timing.TripleBarrierLabel.
  return_pct, raw price PnL) and net (SimulatedTrade.net_return_pct, after
  funding cost) and reported side by side -- a big gross-vs-net gap is
  itself the diagnostic the brief asks for ("strategi terlalu bergantung
  raw momentum yang dimakan biaya holding").
- Sharpe is annualized from each trade's ACTUAL holding duration
  (signal_ts -> label.exit_ts, real calendar time), not an assumed 252
  trading days -- crypto perps trade 24/7 with non-uniform holding
  periods, so a fixed trading-calendar assumption would be wrong on its
  own terms, not just imprecise.
- Regime-segmented breakdown (RISK_ON/OFF/NEUTRAL/FREEZE) is
  architecturally supported via compute_metrics_by_regime()'s pluggable
  `regime_of` callable, but NOT exercised or verified against real regime
  data -- market_regime.py (PRD B.6) doesn't exist yet, so there is no
  real regime label to group by. Same "mechanism built, not yet validated
  against the thing it's meant for" caveat as level_strength.py's
  Gann-angle touch-tracking.

Censored trades (label.censored -- ran out of candle data before
max_holding_bars) are excluded from every calculation here, same
right-censoring discipline as every other module this session: their
return_pct reflects an arbitrary early cutoff, not a genuine resolution,
and mixing them in would bias PF/Sharpe/drawdown with incomplete samples.
censored_count on the result records how many were dropped, for
transparency rather than silently vanishing.

Pure function over an explicit SimulatedTrade list -- no DB coupling,
same discipline as every other module in this validation harness.
"""

import dataclasses
import datetime
import math
import os
import random
import statistics
import sys
from collections.abc import Callable

sys.path.insert(0, os.path.dirname(__file__))

import trade_simulator as ts  # noqa: E402

# Used to derive an annualization factor from actual average holding
# duration, replacing the naive "252 trading days" assumption the brief
# explicitly rejects for 24/7 crypto perps.
YEAR_DURATION = datetime.timedelta(days=365.25)

# F6b I5: bootstrap CI default resample count -- cheap enough (a few
# hundred ms per series at typical trade counts) to run on every campaign
# report, not just on request.
DEFAULT_BOOTSTRAP_RESAMPLES = 2000
DEFAULT_BOOTSTRAP_CI = 0.90
# Fixed, not time-derived -- bootstrap_pf_net_ci() must be reproducible run
# to run for the same trades (same "no hidden randomness" discipline as
# every other constant in this harness; sklearn's own saga solver is the
# sole exception, already noted as unseeded elsewhere in this codebase).
DEFAULT_BOOTSTRAP_SEED = 20260704


@dataclasses.dataclass(frozen=True)
class MetricsResult:
    trade_count: int  # non-censored trades used in every calculation below
    censored_count: int  # excluded trades, reported for transparency
    win_count: int  # by net_return_pct > 0 -- the funding-adjusted, "real" outcome
    loss_count: int
    profit_factor_gross: float | None  # None when there are no losing trades to divide by (undefined, not infinite)
    profit_factor_net: float | None
    sharpe_gross: float | None  # None when fewer than 2 trades or zero variance (undefined)
    sharpe_net: float | None
    max_drawdown_pct_gross: float
    max_drawdown_pct_net: float
    avg_holding_duration_hours: float
    trades_per_year: float | None  # the annualization factor actually used for Sharpe; None if avg holding duration is zero


def _profit_factor(returns: list[float]) -> float | None:
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = -sum(r for r in returns if r < 0)  # positive magnitude
    if gross_loss <= 0.0:
        return None
    return gross_profit / gross_loss


def weighted_profit_factor(weighted_returns: list[tuple[float, float]]) -> float | None:
    """F6b I1(a) sizing-multiplier experiment: `weighted_returns` is a list
    of (weight, net_return_pct) pairs, one per trade, where weight is that
    trade's own position-size multiplier (see gated_campaign.py's
    size_multiplier()). Scaling a trade's position size scales its dollar
    PnL by the same factor, so weighting BOTH gross profit and gross loss
    by each trade's own weight is the size-aware generalization of
    _profit_factor() above (weight=1.0 for every trade reduces to exactly
    the same number). None when there's no weighted loss to divide by, same
    "undefined, not infinite" convention as _profit_factor()."""
    gross_profit = sum(w * r for w, r in weighted_returns if r > 0)
    gross_loss = -sum(w * r for w, r in weighted_returns if r < 0)
    if gross_loss <= 0.0:
        return None
    return gross_profit / gross_loss


def bootstrap_pf_net_ci(
    trades: list[ts.SimulatedTrade],
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    ci: float = DEFAULT_BOOTSTRAP_CI,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """F6b I5: bootstrap confidence interval on pooled PF net, as a
    secondary metric alongside window-pass-count -- a single-window-count
    threshold is a coarse, under-powered signal at the ~40-60 trades/window
    typical of this harness (F6b module docstring context); a CI on the
    POOLED pf_net communicates how much sampling noise is in that number
    without needing more real data.

    Resamples per-trade (with replacement) from the non-censored trades'
    net_return_pct, recomputes PF net each time, and returns the
    (lower, upper) percentile bound of the `ci` central interval (e.g.
    ci=0.90 -> 5th/95th percentile). None when fewer than 2 non-censored
    trades exist (nothing meaningful to resample), or when every resample
    happens to have no losing trade (PF net undefined in all of them --
    vanishingly rare in practice, but reported as None rather than a
    fabricated bound).

    This resamples trades independently of their original chronological
    order (a standard bootstrap assumption), which does NOT reintroduce any
    lookahead: it is a purely descriptive uncertainty estimate over
    already-realized, already-causally-computed trade outcomes, the same
    "post-hoc, non-causal" freedom compute_metrics_by_regime()'s own
    docstring already claims for its caller-supplied regime_of().
    """
    resolved = [t for t in trades if not t.label.censored]
    if len(resolved) < 2:
        return None
    returns = [t.net_return_pct for t in resolved]
    rng = random.Random(seed)
    pf_samples = []
    for _ in range(n_resamples):
        resample = [rng.choice(returns) for _ in returns]
        pf = _profit_factor(resample)
        if pf is not None:
            pf_samples.append(pf)
    if not pf_samples:
        return None
    tail = (1.0 - ci) / 2.0
    pf_samples.sort()
    lower = _percentile(pf_samples, tail * 100.0)
    upper = _percentile(pf_samples, (1.0 - tail) * 100.0)
    return lower, upper


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile over an already-sorted list -- same
    convention numpy.percentile's default uses, kept dependency-free since
    this module has no numpy import elsewhere."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[int(rank)]
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _sharpe(returns: list[float], trades_per_year: float | None) -> float | None:
    if len(returns) < 2 or trades_per_year is None:
        return None
    stdev_return = statistics.stdev(returns)
    if stdev_return == 0.0:
        return None
    return (statistics.mean(returns) / stdev_return) * math.sqrt(trades_per_year)


def _max_drawdown_pct(returns: list[float]) -> float:
    """returns must already be in chronological order -- drawdown is a
    property of a sequence, not a set. Walks a compounding equity curve
    starting at 1.0, tracking the largest peak-to-trough decline."""
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


def compute_metrics(trades: list[ts.SimulatedTrade]) -> MetricsResult:
    if not trades:
        raise ValueError("trades must not be empty")

    censored = [t for t in trades if t.label.censored]
    resolved = sorted((t for t in trades if not t.label.censored), key=lambda t: t.signal_ts)
    if not resolved:
        raise ValueError("no non-censored trades to compute metrics from")

    gross_returns = [t.label.return_pct for t in resolved]
    net_returns = [t.net_return_pct for t in resolved]

    holding_durations = [t.label.exit_ts - t.signal_ts for t in resolved]
    avg_holding_duration = sum(holding_durations, datetime.timedelta()) / len(holding_durations)
    trades_per_year = YEAR_DURATION / avg_holding_duration if avg_holding_duration.total_seconds() > 0 else None

    return MetricsResult(
        trade_count=len(resolved),
        censored_count=len(censored),
        win_count=sum(1 for r in net_returns if r > 0),
        loss_count=sum(1 for r in net_returns if r < 0),
        profit_factor_gross=_profit_factor(gross_returns),
        profit_factor_net=_profit_factor(net_returns),
        sharpe_gross=_sharpe(gross_returns, trades_per_year),
        sharpe_net=_sharpe(net_returns, trades_per_year),
        max_drawdown_pct_gross=_max_drawdown_pct(gross_returns),
        max_drawdown_pct_net=_max_drawdown_pct(net_returns),
        avg_holding_duration_hours=avg_holding_duration.total_seconds() / 3600.0,
        trades_per_year=trades_per_year,
    )


def compute_metrics_by_regime(
    trades: list[ts.SimulatedTrade], regime_of: Callable[[ts.SimulatedTrade], str]
) -> dict[str, MetricsResult]:
    """Regime-segmented breakdown the brief asks for -- caller supplies
    `regime_of` since no regime classifier exists yet in this codebase
    (see module docstring). Each regime group is computed independently
    via compute_metrics(), so a group with zero non-censored trades
    raises the same ValueError compute_metrics() would on its own."""
    groups: dict[str, list[ts.SimulatedTrade]] = {}
    for trade in trades:
        groups.setdefault(regime_of(trade), []).append(trade)
    return {regime: compute_metrics(group) for regime, group in groups.items()}
