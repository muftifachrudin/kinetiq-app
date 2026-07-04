"""docs/shadow-simulator-brief.md Section 3-4, 6: pairs a signal's
simulated (paper) outcome against its real-money counterpart and
decomposes the gap between them into named components -- so the founder
learns WHICH part of "real execution differs from paper" is costing
them (discipline? sizing? fees?), not just that it does.

Scope decision (3 Juli 2026): this is the pure-function attribution/
fidelity layer ONLY, deliberately without any new DB table or migration.
Investigated first: docs/shadow-simulator-brief.md Section 6 sketches a
persisted `shadow_pair` table keyed by `signal_id`, but at the time this
module was written no such `signal_id` existed anywhere in this codebase,
because there was no live signal-emission pipeline yet -- `signal_runner.
Signal` was a pure in-memory dataclass only ever consumed by validation/
backtest scripts (apps/products/trading/agent-orchestrator/graphs/,
skills/execution/, telegram-bot/ were all still empty `.gitkeep`
scaffolding). Building a `signal` table then, with no live writer, would
have been exactly the kind of "design for a hypothetical future
requirement" this codebase's own conventions warn against. So:
match_signal_to_trade() below is a heuristic (instrument+direction+time-
window) matcher over whatever in-memory Signal list a caller already has
(e.g. from a backtest/validation run), not a DB join -- and everything in
this module stays a plain function over dataclasses, same discipline as
trade_simulator.py and metrics.py.

Update (F0b, docs/sonnet5-implementation-roadmap.md): the `signal` table
and `trade_annotation.signal_id` linkage column now exist (migration
0008) -- Fase 3 (fit_weights.py) and the F7 shadow loop are real
consumers/writers that resolve the blocker above. This module's own
heuristic matching is UNCHANGED by that migration: there is still no live
writer populating `signal`/`signal_id` for real trades (F7's own loop is
what would do that), so match_signal_to_trade() remains how pairing
actually happens today. Once a live writer exists, a signal_id-based exact
join becomes possible and would likely replace or supplement this
heuristic -- not done here, since building that consumer is F7's job, not
a schema-only migration's.

Real-data honesty note: the founder's 276 bulk-imported trade_annotation
rows (docs/fib-gann-validation-brief.md Section 20) have leverage AND
exit_reason_real NULL for essentially all of them (Binance's export
doesn't carry either). That means size_leverage_effect_pct/
exit_slippage_pct/manual_override_pct/gap_margin_pct will legitimately
come back None for most of that historical batch -- this module never
guesses a value for a field the data doesn't support (same right-
censoring discipline as metrics.py's `censored` handling). Only
entry_slippage_pct is always computable, since it only needs prices
that are required inputs. Full attribution becomes possible going
forward as new trades get logged with leverage/exit_reason_real filled
in via log_trade_annotation.py.

--- Attribution design ---

Everything is expressed as a MARGIN-scaled (leveraged) percentage,
matching trade_simulator.LeveragedTradeResult.margin_return_pct's
convention -- notional-only percentages can't show a liquidation's
-100% margin loss, which is the whole point of comparing real leverage/
liquidation behavior against the sim's assumption (the brief's headline
example). gap_margin_pct = real_margin_pnl_pct - sim.margin_return_pct
is the total being decomposed.

entry_slippage_pct: direction-adjusted (signal.entry_price vs
real.entry_fill_price) price gap, scaled to sim's leverage. Always
computable -- doesn't depend on real.leverage at all (it's asking "what
would the margin-pct impact of this fill-price gap have been AT THE
SIM'S leverage", isolating the price-difference effect independent of
any leverage difference).

exit_slippage_pct / manual_override_pct: mutually exclusive halves of
the same underlying "exit price differs from sim" comparison, split by
whether real.exit_reason_real matches sim's exit_reason. Same exit
reason -> it's slippage (execution quality on the same kind of exit).
Different exit reason -> the exit-price gap is attributed to
manual_override instead UNLESS the mismatch is real being liquidated
(that's a leverage/margin effect captured by size_leverage_effect_pct
below, not a discretionary choice -- mislabeling a liquidation as
"manual override" would actively point the founder at the wrong fix).

size_leverage_effect_pct: holds prices at exactly what the sim assumed
(so it's orthogonal to slippage/manual_override above) and asks "if
only leverage/margin_mode/liquidation-status had been real's instead of
sim's, what's the margin-pct gap." Liquidation makes this computable
even without knowing real.leverage (a liquidation is always exactly
-100% margin, independent of the leverage number), which is
deliberate -- it's the one case the brief calls out by name.

fees_funding_delta_pct: real fees+funding normalized to a margin-pct
using real.notional_usd (a caller-supplied value, NOT a trade_annotation
column -- that table has no quantity/notional field at all, so this
stays None rather than guessing a notional from nothing).

residual_pct: gap_margin_pct minus every other component, computed only
when every other component is non-None (otherwise a "residual" would
silently absorb an unrelated missing-data gap rather than genuine
unexplained interaction effects, which is the only thing residual is
supposed to represent per the brief -- "kalau besar = ada bug
attribution").

timing_deviation is reported as a plain duration (real entry ts minus
signal ts), informational only -- it is NOT folded into the pct
decomposition, because isolating its OWN price contribution would
require re-running the simulator at the real trade's actual entry
timestamp (needs the original candle series, which this module doesn't
have access to by design -- it operates on already-computed
Signal/LeveragedTradeResult objects, not raw candles). Whatever price
effect the timing difference actually had shows up already, folded into
entry_slippage_pct (the only price gap this module can observe).
"""

import dataclasses
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "validation", "fib_gann_backtest"))

import fib_gann_timing as fgt  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

_DIRECTION_SIGN = {fgt.TradeDirection.LONG: 1.0, fgt.TradeDirection.SHORT: -1.0}
_ACTION_TO_DIRECTION = {"long": fgt.TradeDirection.LONG, "short": fgt.TradeDirection.SHORT}


@dataclasses.dataclass(frozen=True)
class RealTrade:
    """The real side of a shadow pair. Deliberately requires entry/exit
    fill prices (unlike trade_annotation's nullable columns) -- a trade
    with no exit fill yet isn't a completed round-trip and isn't
    meaningful to pair against a sim outcome. leverage/margin_mode/
    exit_reason_real/fees/funding stay Optional because that's the real
    shape of trade_annotation data today (see module docstring)."""

    ts: datetime.datetime  # entry timestamp -- trade_annotation has no separate exit_ts column at all
    direction: fgt.TradeDirection
    entry_fill_price: float
    exit_fill_price: float
    leverage: float | None = None
    margin_mode: str | None = None
    exit_reason_real: str | None = None
    fees_paid_usd: float | None = None
    funding_paid_usd: float | None = None
    notional_usd: float | None = None  # caller-supplied context, NOT a trade_annotation column -- needed only to normalize fees_funding_delta_pct


def real_trade_from_annotation_row(row: dict, notional_usd: float | None = None) -> RealTrade:
    """Maps a trade_annotation-shaped dict (as built by log_trade_annotation.py/
    import_binance_position_history.py's build_row(), or a real DB row) into a
    RealTrade. Raises if entry_fill_price/exit_fill_price are missing --
    see RealTrade's docstring for why that's a hard requirement here."""
    if row.get("entry_fill_price") is None or row.get("exit_fill_price") is None:
        raise ValueError("row has no entry_fill_price/exit_fill_price -- not a completed round-trip, can't pair")
    return RealTrade(
        ts=row["ts"],
        direction=_ACTION_TO_DIRECTION[row["action"]],
        entry_fill_price=row["entry_fill_price"],
        exit_fill_price=row["exit_fill_price"],
        leverage=row.get("leverage"),
        margin_mode=row.get("margin_mode"),
        exit_reason_real=row.get("exit_reason_real"),
        fees_paid_usd=row.get("fees_paid_usd"),
        funding_paid_usd=row.get("funding_paid_usd"),
        notional_usd=notional_usd,
    )


def match_signal_to_trade(
    candidate_signals: list[sr.Signal],
    real: RealTrade,
    tolerance: datetime.timedelta,
) -> sr.Signal | None:
    """Heuristic pairing: nearest same-direction signal within `tolerance`
    of the real trade's entry timestamp, or None if no candidate qualifies.
    Caller must pre-filter candidate_signals to the real trade's own
    instrument first -- Signal itself carries no instrument identifier
    (signal_runner.py operates on one instrument's candle series at a
    time)."""
    same_direction = [s for s in candidate_signals if s.direction is real.direction]
    within_tolerance = [s for s in same_direction if abs((s.ts - real.ts).total_seconds()) <= tolerance.total_seconds()]
    if not within_tolerance:
        return None
    return min(within_tolerance, key=lambda s: abs((s.ts - real.ts).total_seconds()))


def _notional_pnl_pct(direction: fgt.TradeDirection, entry_price: float, exit_price: float) -> float:
    if direction is fgt.TradeDirection.LONG:
        return (exit_price - entry_price) / entry_price
    return (entry_price - exit_price) / entry_price


def _price_gap_pct(signal_price: float, price_a: float, price_b: float, direction: fgt.TradeDirection) -> float:
    """Direction-adjusted (price_a - price_b)/signal_price -- positive
    means price_a was more favorable to the trader than price_b. Shared
    formula behind entry_slippage/exit_slippage/manual_override, which
    are all "compare two prices, direction-adjusted" at heart."""
    return _DIRECTION_SIGN[direction] * (price_a - price_b) / signal_price


@dataclasses.dataclass(frozen=True)
class DivergenceAttribution:
    gap_margin_pct: float | None  # real_margin_pnl_pct - sim.margin_return_pct; None when real_margin_pnl_pct isn't computable (see module docstring)
    entry_slippage_pct: float  # always computable
    exit_slippage_pct: float | None
    manual_override_pct: float | None
    size_leverage_effect_pct: float | None
    fees_funding_delta_pct: float | None
    residual_pct: float | None
    exit_reason_match: bool | None  # None when real.exit_reason_real is unknown
    timing_deviation: datetime.timedelta  # informational only -- see module docstring


def compute_divergence_attribution(
    signal: sr.Signal,
    sim: ts.LeveragedTradeResult,
    real: RealTrade,
) -> DivergenceAttribution:
    sim_leverage = sim.margin_context.leverage
    direction = signal.direction

    entry_slippage_pct = _price_gap_pct(signal.entry_price, signal.entry_price, real.entry_fill_price, direction) * sim_leverage

    sim_exit_reason_value = sim.exit_reason.value
    if real.exit_reason_real is None:
        exit_reason_match = None
        exit_slippage_pct = None
        manual_override_pct = None
    else:
        exit_reason_match = real.exit_reason_real == sim_exit_reason_value
        exit_price_gap_pct = _price_gap_pct(signal.entry_price, real.exit_fill_price, sim.exit_price, direction) * sim_leverage
        if exit_reason_match:
            exit_slippage_pct = exit_price_gap_pct
            manual_override_pct = 0.0
        elif real.exit_reason_real == "liquidated":
            # a liquidation mismatch is a leverage/margin effect (captured
            # by size_leverage_effect_pct below), not a discretionary
            # choice -- don't mislabel it as manual_override.
            exit_slippage_pct = None
            manual_override_pct = 0.0
        else:
            exit_slippage_pct = None
            manual_override_pct = exit_price_gap_pct

    if real.exit_reason_real == "liquidated":
        real_margin_pnl_pct = -1.0
        counterfactual_real_margin_pnl_pct = -1.0
        size_leverage_effect_pct = counterfactual_real_margin_pnl_pct - sim.margin_return_pct
    elif real.leverage is not None:
        real_notional_pnl_pct = _notional_pnl_pct(direction, real.entry_fill_price, real.exit_fill_price)
        real_margin_pnl_pct = real_notional_pnl_pct * real.leverage
        counterfactual_real_margin_pnl_pct = sim.notional_return_pct * real.leverage
        size_leverage_effect_pct = counterfactual_real_margin_pnl_pct - sim.margin_return_pct
    else:
        real_margin_pnl_pct = None
        size_leverage_effect_pct = None

    gap_margin_pct = (real_margin_pnl_pct - sim.margin_return_pct) if real_margin_pnl_pct is not None else None

    if real.notional_usd is not None:
        real_fees_and_funding_usd = (real.fees_paid_usd or 0.0) + (real.funding_paid_usd or 0.0)
        fees_funding_delta_pct = -(real_fees_and_funding_usd / real.notional_usd) * sim_leverage
    else:
        fees_funding_delta_pct = None

    residual_pct = None
    if (
        gap_margin_pct is not None
        and size_leverage_effect_pct is not None
        and fees_funding_delta_pct is not None
        and exit_reason_match is not None
    ):
        residual_pct = gap_margin_pct - (
            entry_slippage_pct + (exit_slippage_pct or 0.0) + (manual_override_pct or 0.0) + size_leverage_effect_pct + fees_funding_delta_pct
        )

    return DivergenceAttribution(
        gap_margin_pct=gap_margin_pct,
        entry_slippage_pct=entry_slippage_pct,
        exit_slippage_pct=exit_slippage_pct,
        manual_override_pct=manual_override_pct,
        size_leverage_effect_pct=size_leverage_effect_pct,
        fees_funding_delta_pct=fees_funding_delta_pct,
        residual_pct=residual_pct,
        exit_reason_match=exit_reason_match,
        timing_deviation=real.ts - signal.ts,
    )


# Rule-based starting weights (brief Section 4: "Weight awal rule-based
# (bukan ML)"), NOT a fitted result -- points deducted from a 100-start
# fidelity score per 1x risk_pct_per_trade of |component|. Slippage/fees
# are largely unavoidable execution friction (small weight); manual
# override and leverage/liquidation divergence are within the founder's
# control (large weight), matching the brief's explicit intent.
DEFAULT_FIDELITY_WEIGHTS = {
    "entry_slippage": 5.0,
    "exit_slippage": 5.0,
    "fees_funding_delta": 3.0,
    "manual_override": 25.0,
    "size_leverage_effect": 25.0,
    "residual": 5.0,
}


def compute_fidelity_score(
    attribution: DivergenceAttribution,
    risk_pct_per_trade: float,
    weights: dict[str, float] = DEFAULT_FIDELITY_WEIGHTS,
) -> float:
    """0-100: 100 - Σ(|component| / risk_pct_per_trade * weight) over
    whatever components are non-None, clamped to [0, 100]. Missing
    components are skipped, never penalized -- a bulk-imported historical
    trade with no leverage/exit_reason_real data isn't "bad execution,"
    it's just less-observed execution (same right-censoring stance as
    the rest of this module)."""
    if risk_pct_per_trade <= 0.0:
        raise ValueError("risk_pct_per_trade must be positive")
    components = {
        "entry_slippage": attribution.entry_slippage_pct,
        "exit_slippage": attribution.exit_slippage_pct,
        "fees_funding_delta": attribution.fees_funding_delta_pct,
        "manual_override": attribution.manual_override_pct,
        "size_leverage_effect": attribution.size_leverage_effect_pct,
        "residual": attribution.residual_pct,
    }
    deduction = sum(abs(value) / risk_pct_per_trade * weights[name] for name, value in components.items() if value is not None)
    return max(0.0, min(100.0, 100.0 - deduction))


@dataclasses.dataclass(frozen=True)
class ShadowPair:
    signal: sr.Signal
    sim: ts.LeveragedTradeResult
    real: RealTrade
    attribution: DivergenceAttribution
    fidelity_score: float


def build_shadow_pair(
    signal: sr.Signal,
    sim: ts.LeveragedTradeResult,
    real: RealTrade,
    risk_pct_per_trade: float,
    weights: dict[str, float] = DEFAULT_FIDELITY_WEIGHTS,
) -> ShadowPair:
    attribution = compute_divergence_attribution(signal, sim, real)
    fidelity_score = compute_fidelity_score(attribution, risk_pct_per_trade, weights)
    return ShadowPair(signal=signal, sim=sim, real=real, attribution=attribution, fidelity_score=fidelity_score)
