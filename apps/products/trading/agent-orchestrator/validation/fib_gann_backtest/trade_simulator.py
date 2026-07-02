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
"""

import dataclasses
import datetime
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
    net_return_pct: float  # label.return_pct - funding_cost_pct


def _funding_cost_pct(direction: fgt.TradeDirection, events_in_window: list[FundingEvent]) -> float:
    total_rate = sum(event.rate for event in events_in_window)
    return total_rate if direction is fgt.TradeDirection.LONG else -total_rate


def simulate_trade(
    signal: sr.Signal,
    granular_candles: list[fgt.Candle],
    funding_events: list[FundingEvent],
    max_holding_bars: int,
) -> SimulatedTrade:
    """Labels one signal's realized outcome (label_triple_barrier) and
    deducts direction-adjusted funding cost accrued over the holding
    window. granular_candles should already be sliced to start immediately
    after the signal's own bar -- same caller responsibility
    label_triple_barrier() itself documents."""
    label = fgt.label_triple_barrier(signal.exit_plan, granular_candles, max_holding_bars)
    window_events = [event for event in funding_events if signal.ts <= event.ts <= label.exit_ts]
    funding_cost_pct = _funding_cost_pct(signal.direction, window_events)
    return SimulatedTrade(
        signal_ts=signal.ts,
        signal_index=signal.index,
        direction=signal.direction,
        confidence=signal.confidence,
        entry_price=signal.entry_price,
        label=label,
        funding_cost_pct=funding_cost_pct,
        funding_events_count=len(window_events),
        net_return_pct=label.return_pct - funding_cost_pct,
    )


def simulate_trades(
    signals: list[sr.Signal],
    candles: list[fgt.Candle],
    funding_events: list[FundingEvent],
    max_holding_bars: int,
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
        trades.append(simulate_trade(signal, granular, funding_events, max_holding_bars))
    return trades
