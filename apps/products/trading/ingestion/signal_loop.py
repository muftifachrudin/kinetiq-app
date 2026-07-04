"""F0e P3 (docs/sonnet5-implementation-roadmap.md): Shadow Tahap 1's signal
collection loop, wired into the SAME ingestion-worker process as worker.py's
OHLCV/funding poll loop -- deliberately not a new Railway service (the
roadmap's own instruction: "DI ingestion-worker yang sudah ada"). The worker
already wakes up right at each 1h candle close with fresh data; this module
adds one more step to that same cycle: turn the freshly-closed candle history
into signals and persist them, so every hour the loop doesn't run is a whole
hour of genuine out-of-sample signal data lost for good (unlike OHLCV, which
can always be backfilled after the fact).

Purely additive plumbing -- no order execution, no trading decision, no
tenant/account context at all (Shadow Tahap 1 has none yet, per the roadmap's
own "belum ada eksekusi order, belum ada keputusan trading -- murni data").

generate_signals() (signal_runner.py) is a pure function over an explicit
candle list -- reused UNCHANGED here, no live-specific reimplementation. It's
O(n^2) over the full candle history every call (documented in signal_runner.py
itself); at today's ~1 year/series (~8770 candles) that's a couple of minutes
per series, comfortably inside a 1h cycle for 4 series -- P6 (roadmap) tracks
optimizing this before a 3-year history makes it too slow, not before this
module ships. Idempotency comes from re-checking which (instrument, timeframe,
ts) triples already exist in `signal` before writing (backed by the table's
own unique constraint as a second line of defense), not from trying to avoid
recomputing signals for already-covered history -- avoiding the recompute
itself is exactly what P6 is for.

Derivatives factors (funding/OI/L-S/liq-cascade) are NOT wired in yet: P2
(funding/OI backfill) hasn't landed in production at the time this module was
written (funding_rate has only live-poll rows, open_interest has zero) --
wiring a real DailyDerivativesRecord source now would mostly read neutral
defaults anyway. generate_signals() is called without derivatives_records
here on purpose; once P2 lands, a follow-up can build DailyDerivativesRecord
straight from the funding_rate/open_interest tables (a natural bump to
config-v2, tracked alongside that work, not invented speculatively now).

PreTradeCard (F7a, position_sizing.py) is built here against REPRESENTATIVE,
illustrative account parameters, NOT a real tenant/mandate -- there is no
tenant in Shadow Tahap 1 at all (signal has no tenant_id, same as ohlcv/
funding_rate, per the Signal model's own docstring). This mirrors what a
typical default RiskMandate row would compute, for descriptive/context
purposes in factor_scores only -- never a real trading decision, and never
read back into anything that gates or sizes a real order.
"""

import dataclasses
import datetime
import os
import sys

_AGENT_ORCHESTRATOR = os.path.join(os.path.dirname(__file__), "..", "agent-orchestrator")
sys.path.insert(0, os.path.join(_AGENT_ORCHESTRATOR, "skills", "strategy"))
sys.path.insert(0, os.path.join(_AGENT_ORCHESTRATOR, "validation", "fib_gann_backtest"))

import fib_gann_timing as fgt  # noqa: E402
import ingest  # noqa: E402
import position_sizing as ps  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402
from kinetiq_db.models import Instrument, Ohlcv, Signal  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

# Labeled per the roadmap's Shadow Tahap 1 framing ("freeze konfigurasi
# sebagai config-v1... catatan config kandidat F5 dievaluasi paralel di
# harness"): every signal this loop persists is generated with PRODUCTION
# generate_signals() defaults (fib_gann_timing.DEFAULT_*), recorded on each
# row so a later config change is visible in the data rather than silently
# assumed. Bump this string (config-v2, ...) if/when the live generation
# parameters themselves ever change -- never silently reuse "config-v1" for
# different parameters.
CONFIG_LABEL = "config-v1"

# Illustrative-only account parameters for the PreTradeCard recorded in
# factor_scores (module docstring) -- Shadow Tahap 1 has no real tenant or
# RiskMandate to read from. risk_pct_per_trade/max_leverage_cap match
# RiskMandate's own column server_defaults exactly (packages/db/src/
# kinetiq_db/models.py) so this reads as "what a brand-new default mandate
# would compute", not an arbitrary made-up number.
REPRESENTATIVE_EQUITY_USD = 10_000.0
REPRESENTATIVE_RISK_PCT_PER_TRADE = 0.01  # RiskMandate.risk_pct_per_trade server_default
REPRESENTATIVE_MAX_LEVERAGE_CAP = 3.0  # RiskMandate.max_leverage server_default
REPRESENTATIVE_MARGIN_MODE = ts.MarginMode.ISOLATED  # the only mode position_sizing.py implements (F7b: cross)

# The exact per-factor dump fields signal_runner.Signal carries, matching
# the Signal DB model's own docstring ("factor_scores mirrors signal_runner.
# Signal's per-factor dump fields ... as a flat JSONB object") -- listed
# explicitly rather than dataclasses.asdict(signal) so nested non-JSON
# objects (pivot, exit_plan, structure_event, the direction enum) are never
# accidentally dumped wholesale into this column.
FACTOR_SCORE_FIELDS = (
    "swing_quality",
    "fib_gann_confluence",
    "volume_confirmation",
    "wick_rejection",
    "structure_alignment",
    "htf_alignment",
    "regime_alignment",
    "sma_trend_bias_alignment",
    "daily_bias_alignment",
    "funding_contrarian_alignment",
    "global_ls_contrarian_alignment",
    "top_vs_global_alignment",
    "liq_cascade_flag",
)


def load_candles(db: Session, instrument_id: int, timeframe: str) -> list[fgt.Candle]:
    """Every ohlcv row on file for this (instrument, timeframe), ascending by
    ts -- Numeric columns come back as Decimal via SQLAlchemy, cast to float
    since every fib_gann_timing/signal_runner function expects plain floats."""
    rows = (
        db.query(Ohlcv)
        .filter_by(instrument_id=instrument_id, timeframe=timeframe)
        .order_by(Ohlcv.ts.asc())
        .all()
    )
    return [
        fgt.Candle(ts=row.ts, open=float(row.open), high=float(row.high), low=float(row.low), close=float(row.close), volume=float(row.volume))
        for row in rows
    ]


def existing_signal_timestamps(db: Session, instrument_id: int, timeframe: str) -> set[datetime.datetime]:
    rows = db.query(Signal.ts).filter_by(instrument_id=instrument_id, timeframe=timeframe).all()
    return {row.ts for row in rows}


def _representative_pre_trade_card(signal: sr.Signal, atr_value: float | None) -> dict | None:
    """None (not a crash) when a card can't be built for this particular
    signal -- atr_value unavailable this early in the series, or a
    malformed exit_plan (entry_price == stop_loss, position_sizing.py
    raises ValueError) that signal_runner's own entry-validity gate
    should already prevent but this defends against anyway. Note
    leverage_used = min(cap, max_safe_leverage(...)) is ALWAYS <= the
    exact safe boundary by construction (trade_simulator.max_safe_
    leverage()'s own docstring/proof), so ts.UnsafeLeverageError can never
    actually fire via this call -- caught anyway (it's a ValueError
    subclass) since relying on that being true forever, silently, would be
    exactly the kind of hidden assumption this codebase's conventions
    avoid. One bad signal must never take down the whole cycle's
    persistence for every other signal/instrument."""
    if atr_value is None or atr_value <= 0:
        return None
    try:
        card = ps.build_pre_trade_card(
            exit_plan=signal.exit_plan,
            atr_value=atr_value,
            equity_usd=REPRESENTATIVE_EQUITY_USD,
            risk_pct_per_trade=REPRESENTATIVE_RISK_PCT_PER_TRADE,
            margin_mode=REPRESENTATIVE_MARGIN_MODE,
            max_leverage_cap=REPRESENTATIVE_MAX_LEVERAGE_CAP,
        )
    except ValueError:
        return None
    return dataclasses.asdict(card)


def _factor_scores(signal: sr.Signal, atr_value: float | None) -> dict:
    scores = {field: getattr(signal, field) for field in FACTOR_SCORE_FIELDS}
    scores["config_label"] = CONFIG_LABEL
    scores["pre_trade_card"] = _representative_pre_trade_card(signal, atr_value)
    return scores


def persist_new_signals(db: Session, instrument: Instrument, timeframe: str, candles: list[fgt.Candle]) -> int:
    """Runs generate_signals() over the FULL candle history supplied (module
    docstring on why: correctness over the O(n^2) recompute cost at today's
    data scale), then writes only signals whose ts isn't already in `signal`
    for this (instrument, timeframe) -- the unique constraint is the final
    backstop, this existence check is what keeps every cycle's DB writes
    down to ~0-1 new rows instead of re-writing the whole history every
    hour. Returns the count of newly written rows."""
    if len(candles) < 2:
        return 0

    signals = sr.generate_signals(candles)
    if not signals:
        return 0

    already_seen = existing_signal_timestamps(db, instrument.id, timeframe)
    new_signals = [s for s in signals if s.ts not in already_seen]
    if not new_signals:
        return 0

    atr_series = fgt.compute_atr(candles)
    written = 0
    for signal in new_signals:
        db.add(
            Signal(
                instrument_id=instrument.id,
                timeframe=timeframe,
                ts=signal.ts,
                direction=signal.direction.value,
                entry_price=signal.entry_price,
                stop_loss=signal.exit_plan.stop_loss,
                take_profit_1=signal.exit_plan.take_profits[0] if signal.exit_plan.take_profits else None,
                confidence=signal.confidence,
                factor_scores=_factor_scores(signal, atr_series[signal.index]),
            )
        )
        written += 1
    db.commit()
    return written


def run_signal_loop_once(db: Session, contexts: list, timeframe: str) -> None:
    """Same per-instrument try/except-continue resilience as ingest.
    poll_once(): one instrument's failure (bad data, a transient bug) must
    never block signal generation for every other instrument this cycle.
    Only ever called for timeframe == "1h" by worker.py -- signal_runner.py
    /fib_gann_timing.py's whole design (htf_bias 4h/1d resampling, ATR
    period, etc.) assumes a 1h entry timeframe, matching every backtest
    module in this codebase.

    F0e P5 (docs/sonnet5-implementation-roadmap.md): records a "signal"
    data_type heartbeat via ingest.record_health(), the same data_source_
    health table poll_once() already writes "funding_rate"/"ohlcv"/
    "open_interest" heartbeats to -- signal generation never had one before
    this, so a stuck/crashing signal loop (unlike the OHLCV/funding/OI
    polls) could go unnoticed indefinitely. Recorded per-venue (matching
    that table's own (venue_id, data_type) primary key and poll_once()'s
    existing per-instrument-overwrites-the-same-venue-row convention), not
    per-instrument."""
    for ctx in contexts:
        for venue_symbol, instrument in ctx.instruments:
            try:
                candles = load_candles(db, instrument.id, timeframe)
                written = persist_new_signals(db, instrument, timeframe, candles)
                ingest.record_health(db, ctx.venue, "signal", success=True)
                print(f"[{ctx.venue_name}:{venue_symbol}] signals OK ({written} new, {len(candles)} candles considered)")
            except Exception as exc:
                db.rollback()
                ingest.record_health(db, ctx.venue, "signal", success=False)
                print(f"[{ctx.venue_name}:{venue_symbol}] signals FAILED: {exc}")
