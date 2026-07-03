"""Design brief Section 6: trade_simulator.py -- turns each signal_runner.
Signal into a realized trade outcome by wrapping fib_gann_timing.
label_triple_barrier() (already implemented, does the TP/SL/timeout walk)
plus funding-cost deduction. Section 6's "Metrics -- funding-aware (WAJIB,
bukan opsional)" is mandatory here, not a later add-on: net PnL after
funding is what metrics.py (not yet built) will consume, so it has to
exist at this layer rather than being bolted on after the fact.

Funding accrual is snapshot-based per the brief, not a continuous prorated
estimate: a position only pays/receives funding at the actual funding
timestamps (FundingEvent.ts, typically every funding_interval_hours from
the funding_rate table) that fall within its holding window
[signal.ts, label.exit_ts] -- boundary is inclusive on both ends, a
deliberate simplification for the rare case a signal fires or resolves
exactly on a funding timestamp, not something worth more precision than
that until it's shown to matter.

Direction-adjusted sign: a positive funding_rate means longs pay shorts
(the universal perp convention), so LONG accrues +rate as a cost and
SHORT accrues -rate (a cost that's negative, i.e. a benefit) per event.
net_return_pct = label.return_pct - funding_cost_pct, so a long-held
winning trade that accumulated real funding cost can look worse net than
gross -- exactly the "PF gross vs PF net side by side" comparison the
brief asks metrics.py to report later.

Pure function over explicit signals/candles/funding events -- no DB
coupling, same discipline as fib_gann_timing.py and signal_runner.py.
data_loader.py is what turns real funding_rate table rows into
FundingEvent objects; that wiring isn't done here (data_loader.py is a
separate DB-touching module, deliberately kept out of anything this file
imports).

--- Leverage/liquidation-aware simulation (docs/shadow-simulator-brief.md,
points 1-2 of its implementation order) ---

Everything above this point (SimulatedTrade/simulate_trade/simulate_trades)
is UNLEVERAGED: it assumes a position survives to its structural SL no
matter what. That's a real, material gap the founder flagged (3 Juli
2026): a real leveraged position can be LIQUIDATED before ever reaching
that structural SL, if initial margin is too thin for the leverage used --
arguably the single biggest source of "paper vs real money" divergence,
and one that's fully computable today without needing any real trade
execution data at all (unlike funding-cost verification above, which is
blocked on real funding_rate volume).

MarginContext/build_margin_context/simulate_leveraged_trade are ADDITIVE,
not a replacement -- SimulatedTrade's existing 135-test-covered behavior
is untouched. No dollar/equity amounts are tracked anywhere else in this
per-signal simulator (everything is *_pct/*_fraction, notional-relative),
so initial_margin here is deliberately a FRACTION of notional (1/leverage),
not a dollar figure -- this makes every formula position-size-agnostic by
construction, which is a feature, not a shortcut.

Liquidation price (isolated, MVP simplification -- flat maintenance_margin_
rate per the brief's explicit allowance, not Binance's real tiered-by-
notional schedule): a position's cushion against liquidation is
initial_margin_fraction - maintenance_margin_rate (LONG loses if price
drops through entry*(1-cushion), SHORT if it rises through
entry*(1+cushion)). CROSS margin mode gets an extra cross_buffer_pct added
to that cushion, representing account equity allocated to backstop this
position beyond its own isolated margin -- a genuine simplification, since
this single-trade simulator has no portfolio-wide equity state to derive
that number from automatically; the caller supplies it.

Funding erosion (brief: "posisi leverage tinggi yang di-hold lama bisa
ke-liquidasi karena erosi funding, simulator harus bisa menangkap ini"):
simulate_leveraged_trade() recomputes the liquidation threshold every bar
by subtracting cumulative direction-adjusted funding cost from the cushion
-- a long-held position can get liquidated from funding bleed ALONE with
zero adverse price movement, and the same inequality check naturally
captures that (once cumulative funding consumes the whole cushion, the
effective liquidation price crosses to sit at or past the CURRENT price,
so the very next bar's touch check fires immediately).

max_safe_leverage()/assert_liquidation_safe() implement the brief's hard
invariant: liquidation must sit >= buffer_k*ATR beyond the structural SL,
or the setup is rejected outright (UnsafeLeverageError), not silently
simulated. This is algebraically the exact boundary, not an approximation
-- max_safe_leverage() returns precisely the leverage at which liquidation
distance equals the required minimum (see
test_max_safe_leverage_is_exactly_the_assert_boundary), so leverage at
that value passes and anything above it fails.

Per the brief's explicit sequencing (its Section 5/7): this round is ONLY
points 1-2 (the leverage-aware simulator itself). trade_annotation schema
extension, shadow_pair divergence attribution, fidelity scoring, and any
ML risk-envelope fitting are separate, later rounds -- nothing here reads
or writes trade_annotation, and no learning/fitting happens in this file.
"""

import dataclasses
import datetime
import enum
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))

import fib_gann_timing as fgt  # noqa: E402
import signal_runner as sr  # noqa: E402


@dataclasses.dataclass(frozen=True)
class FundingEvent:
    ts: datetime.datetime
    rate: float  # raw funding rate for one interval, exchange sign convention (positive = longs pay shorts)


@dataclasses.dataclass(frozen=True)
class SimulatedTrade:
    signal_ts: datetime.datetime
    signal_index: int
    direction: fgt.TradeDirection
    confidence: float
    entry_price: float
    label: fgt.TripleBarrierLabel
    funding_cost_pct: float  # direction-adjusted; positive = net cost, negative = net benefit
    funding_events_count: int
    fee_cost_pct: float  # fee_entry_fraction + fee_exit_fraction, always a cost (fees don't care about direction, unlike funding)
    net_return_pct: float  # label.return_pct - funding_cost_pct - fee_cost_pct


def _funding_cost_pct(direction: fgt.TradeDirection, events_in_window: list[FundingEvent]) -> float:
    total_rate = sum(event.rate for event in events_in_window)
    return total_rate if direction is fgt.TradeDirection.LONG else -total_rate


def simulate_trade(
    signal: sr.Signal,
    granular_candles: list[fgt.Candle],
    funding_events: list[FundingEvent],
    max_holding_bars: int,
    fee_entry_fraction: float = 0.0,
    fee_exit_fraction: float = 0.0,
) -> SimulatedTrade:
    """Labels one signal's realized outcome (label_triple_barrier) and
    deducts direction-adjusted funding cost plus round-trip trading fees
    accrued over the holding window. granular_candles should already be
    sliced to start immediately after the signal's own bar -- same caller
    responsibility label_triple_barrier() itself documents.

    fee_entry_fraction/fee_exit_fraction default to 0.0 -- ADDITIVE, not a
    behavior change for any existing caller that doesn't pass them (deep-dive
    finding F5, docs/validation-deep-dive-2026-07.md: fees were entirely
    unmodeled before this, and turned out to be the dominant real-money cost
    for this ~11h-average-holding intraday system, not funding -- a 0.10%
    Binance VIP0 taker-taker round-trip flips baseline mean trade return
    negative, while funding for the same holding period is roughly 20x
    smaller). Unlike funding_cost_pct, fees are NOT direction-adjusted --
    both a taker entry and a taker exit cost the same regardless of
    long/short, so fee_cost_pct is just the sum of the two fractions."""
    label = fgt.label_triple_barrier(signal.exit_plan, granular_candles, max_holding_bars)
    window_events = [event for event in funding_events if signal.ts <= event.ts <= label.exit_ts]
    funding_cost_pct = _funding_cost_pct(signal.direction, window_events)
    fee_cost_pct = fee_entry_fraction + fee_exit_fraction
    return SimulatedTrade(
        signal_ts=signal.ts,
        signal_index=signal.index,
        direction=signal.direction,
        confidence=signal.confidence,
        entry_price=signal.entry_price,
        label=label,
        funding_cost_pct=funding_cost_pct,
        funding_events_count=len(window_events),
        fee_cost_pct=fee_cost_pct,
        net_return_pct=label.return_pct - funding_cost_pct - fee_cost_pct,
    )


def simulate_trades(
    signals: list[sr.Signal],
    candles: list[fgt.Candle],
    funding_events: list[FundingEvent],
    max_holding_bars: int,
    fee_entry_fraction: float = 0.0,
    fee_exit_fraction: float = 0.0,
) -> list[SimulatedTrade]:
    """Batch version: slices candles[signal.index + 1:] as the granular
    window for each signal (single-timeframe for now, matching
    signal_runner.py's own scope note) and skips any signal that's the
    very last candle in the series (no forward data to label at all)."""
    trades = []
    for signal in signals:
        granular = candles[signal.index + 1 :]
        if not granular:
            continue
        trades.append(simulate_trade(signal, granular, funding_events, max_holding_bars, fee_entry_fraction, fee_exit_fraction))
    return trades


# --- Leverage/liquidation-aware simulation ---

# Flat MVP simplification (brief explicitly allows this): real exchanges
# tier maintenance margin by notional size, this uses one flat rate
# instead. ~0.4% is representative of Binance USDT-M's lowest BTC tier.
DEFAULT_MAINTENANCE_MARGIN_RATE = 0.004
# Invariant: liquidation must sit at least this many ATRs beyond the
# structural SL. 1.0x is a starting point, not a fitted value.
DEFAULT_LIQUIDATION_BUFFER_K = 1.0


class MarginMode(enum.Enum):
    CROSS = "cross"
    ISOLATED = "isolated"


class ExitReason(enum.Enum):
    LIQUIDATED = "liquidated"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TIMEOUT = "timeout"


class UnsafeLeverageError(ValueError):
    """Raised when the requested leverage's liquidation price sits inside
    (or too close to) the structural stop-loss distance -- fail fast per
    the brief's explicit invariant, never a silent warning."""


@dataclasses.dataclass(frozen=True)
class MarginContext:
    leverage: float
    margin_mode: MarginMode
    initial_margin_fraction: float  # 1/leverage -- fraction of notional, not a dollar amount (see module docstring)
    maintenance_margin_rate: float
    cross_buffer_pct: float  # extra cushion fraction for CROSS mode; 0.0 for ISOLATED
    liquidation_price: float  # static, ignoring not-yet-accrued funding -- computed, never passed in directly


def _cushion_fraction(margin_context: MarginContext) -> float:
    return margin_context.initial_margin_fraction + margin_context.cross_buffer_pct - margin_context.maintenance_margin_rate


def build_margin_context(
    entry_price: float,
    direction: fgt.TradeDirection,
    leverage: float,
    margin_mode: MarginMode,
    maintenance_margin_rate: float = DEFAULT_MAINTENANCE_MARGIN_RATE,
    cross_buffer_pct: float = 0.0,
) -> MarginContext:
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    if margin_mode is MarginMode.ISOLATED and cross_buffer_pct != 0.0:
        raise ValueError("cross_buffer_pct only applies to CROSS margin mode")
    if cross_buffer_pct < 0.0:
        raise ValueError("cross_buffer_pct must not be negative")

    initial_margin_fraction = 1.0 / leverage
    cushion = initial_margin_fraction + cross_buffer_pct - maintenance_margin_rate
    if cushion <= 0.0:
        raise ValueError(f"leverage {leverage}x leaves no cushion at all against maintenance_margin_rate {maintenance_margin_rate}")

    if direction is fgt.TradeDirection.LONG:
        liquidation_price = entry_price * (1.0 - cushion)
    else:
        liquidation_price = entry_price * (1.0 + cushion)

    return MarginContext(
        leverage=leverage,
        margin_mode=margin_mode,
        initial_margin_fraction=initial_margin_fraction,
        maintenance_margin_rate=maintenance_margin_rate,
        cross_buffer_pct=cross_buffer_pct,
        liquidation_price=liquidation_price,
    )


def max_safe_leverage(
    entry_price: float,
    stop_loss: float,
    atr_value: float,
    maintenance_margin_rate: float = DEFAULT_MAINTENANCE_MARGIN_RATE,
    buffer_k: float = DEFAULT_LIQUIDATION_BUFFER_K,
) -> float:
    """Highest leverage (ISOLATED, cross_buffer_pct=0) at which the
    resulting liquidation price still sits >= buffer_k*ATR beyond the
    structural SL. Algebraically exact, not an approximation -- see the
    module docstring and test_max_safe_leverage_is_exactly_the_assert_
    boundary for the derivation/proof."""
    sl_distance = abs(entry_price - stop_loss)
    denom = sl_distance + buffer_k * atr_value + entry_price * maintenance_margin_rate
    if denom <= 0.0:
        raise ValueError("sl_distance + buffer_k*atr_value + entry_price*maintenance_margin_rate must be positive")
    return entry_price / denom


def assert_liquidation_safe(
    entry_price: float,
    stop_loss: float,
    atr_value: float,
    margin_context: MarginContext,
    buffer_k: float = DEFAULT_LIQUIDATION_BUFFER_K,
) -> None:
    """Fail-fast invariant (brief: "jangan dilanggar walau diminta" in
    spirit -- this is the enforcement, not a suggestion): raises
    UnsafeLeverageError if margin_context's liquidation price would sit
    closer to entry than the structural SL plus a safety buffer. Passing
    (not raising) at exactly buffer_k*ATR beyond SL is intentional --
    max_safe_leverage() returns that exact boundary value."""
    sl_distance = abs(entry_price - stop_loss)
    liq_distance = abs(entry_price - margin_context.liquidation_price)
    required = sl_distance + buffer_k * atr_value
    if liq_distance < required:
        raise UnsafeLeverageError(
            f"leverage {margin_context.leverage}x liquidation distance {liq_distance:.6f} is inside the required "
            f"buffer {required:.6f} (SL distance {sl_distance:.6f} + {buffer_k}x ATR {atr_value:.6f}) -- reduce "
            f"leverage or widen the stop-loss"
        )


@dataclasses.dataclass(frozen=True)
class LeveragedTradeResult:
    exit_reason: ExitReason
    exit_price: float
    exit_ts: datetime.datetime
    bars_held: int
    notional_return_pct: float  # unleveraged, price-move-based -- same convention as TripleBarrierLabel.return_pct
    margin_return_pct: float  # leveraged return relative to margin; exactly -1.0 when LIQUIDATED
    censored: bool
    margin_context: MarginContext


def _notional_return_pct(direction: fgt.TradeDirection, entry_price: float, exit_price: float) -> float:
    if direction is fgt.TradeDirection.LONG:
        return (exit_price - entry_price) / entry_price
    return (entry_price - exit_price) / entry_price


def simulate_leveraged_trade(
    exit_plan: fgt.ExitPlan,
    granular_candles: list[fgt.Candle],
    funding_events: list[FundingEvent],
    entry_ts: datetime.datetime,
    max_holding_bars: int,
    margin_context: MarginContext,
    atr_value: float,
    buffer_k: float = DEFAULT_LIQUIDATION_BUFFER_K,
) -> LeveragedTradeResult:
    """Walks forward like fib_gann_timing.label_triple_barrier(), but
    checks liquidation FIRST on every bar (brief: "Liquidation check
    SEBELUM SL check"), and the liquidation threshold itself shifts every
    bar as funding accrues -- label_triple_barrier() has no hook for
    either of those, hence a separate walk here rather than wrapping it.

    Funding erosion: cumulative direction-adjusted funding cost (same sign
    convention as simulate_trade's _funding_cost_pct) is subtracted from
    the margin cushion every bar BEFORE checking the price barriers, so a
    long-held position can get liquidated purely from funding bleed with
    no adverse price move at all.
    """
    if not granular_candles:
        raise ValueError("granular_candles must not be empty")
    if max_holding_bars <= 0:
        raise ValueError("max_holding_bars must be positive")
    if not exit_plan.take_profits:
        raise ValueError("exit_plan has no take_profits -- can't simulate without an upper barrier (TP1)")

    assert_liquidation_safe(exit_plan.entry_price, exit_plan.stop_loss, atr_value, margin_context, buffer_k)

    direction = exit_plan.direction
    entry_price = exit_plan.entry_price
    take_profit = exit_plan.take_profits[0]
    stop_loss = exit_plan.stop_loss
    cushion = _cushion_fraction(margin_context)

    sorted_events = sorted((event for event in funding_events if event.ts >= entry_ts), key=lambda event: event.ts)
    funding_idx = 0
    cumulative_funding_fraction = 0.0

    window = granular_candles[:max_holding_bars]
    for i, candle in enumerate(window):
        while funding_idx < len(sorted_events) and sorted_events[funding_idx].ts <= candle.ts:
            event = sorted_events[funding_idx]
            cumulative_funding_fraction += event.rate if direction is fgt.TradeDirection.LONG else -event.rate
            funding_idx += 1

        remaining_cushion = cushion - cumulative_funding_fraction
        if direction is fgt.TradeDirection.LONG:
            effective_liquidation_price = entry_price * (1.0 - remaining_cushion)
            liquidated = candle.low <= effective_liquidation_price
        else:
            effective_liquidation_price = entry_price * (1.0 + remaining_cushion)
            liquidated = candle.high >= effective_liquidation_price

        if liquidated:
            return LeveragedTradeResult(
                exit_reason=ExitReason.LIQUIDATED,
                exit_price=effective_liquidation_price,
                exit_ts=candle.ts,
                bars_held=i + 1,
                notional_return_pct=_notional_return_pct(direction, entry_price, effective_liquidation_price),
                margin_return_pct=-1.0,
                censored=False,
                margin_context=margin_context,
            )

        if direction is fgt.TradeDirection.LONG:
            hit_sl, hit_tp = candle.low <= stop_loss, candle.high >= take_profit
        else:
            hit_sl, hit_tp = candle.high >= stop_loss, candle.low <= take_profit

        if hit_sl:  # SL checked before TP on a same-candle double-touch, matching label_triple_barrier()'s rule
            notional = _notional_return_pct(direction, entry_price, stop_loss)
            return LeveragedTradeResult(ExitReason.STOP_LOSS, stop_loss, candle.ts, i + 1, notional, notional * margin_context.leverage, False, margin_context)
        if hit_tp:
            notional = _notional_return_pct(direction, entry_price, take_profit)
            return LeveragedTradeResult(ExitReason.TAKE_PROFIT, take_profit, candle.ts, i + 1, notional, notional * margin_context.leverage, False, margin_context)

    timeout_candle = window[-1]
    censored = len(granular_candles) < max_holding_bars
    notional = _notional_return_pct(direction, entry_price, timeout_candle.close)
    return LeveragedTradeResult(
        ExitReason.TIMEOUT, timeout_candle.close, timeout_candle.ts, len(window), notional, notional * margin_context.leverage, censored, margin_context
    )
