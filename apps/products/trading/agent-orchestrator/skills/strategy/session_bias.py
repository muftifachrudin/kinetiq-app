"""Founder theory (3 Juli 2026): price behaves differently depending on
which trading session (Asia/London/New York) is active -- e.g. "jam Asia
sering long/naik" -- capability #3 of the "trade journey prediction"
roadmap (docs/fib-gann-validation-brief.md Section 9).

Correction to this session's earlier documentation: Section 9/bag. 9 of
the validation brief said this capability was "terblokir data" because
CoinGlass Hobbyist only gives daily-granularity funding/OI/liquidation
data. That's true for THOSE data types, but irrelevant here -- session
tagging only needs a candle's own timestamp (session_of() below is a pure
function of an hour-of-day), and this codebase's OHLCV ingestion
(apps/products/trading/ingestion/) already pulls HOURLY candles from
Binance/Bybit/Hyperliquid directly, not from CoinGlass at all. The real
constraint is DATA VOLUME, not granularity: production currently has
only ~100 hourly candles (~4 days), the same constraint that made
run_validation.py's real walk-forward config produce zero windows
(fib-gann-validation-brief.md Section 17) -- nowhere near enough days to
say anything statistically meaningful about "does Asia session usually
go up," even though the mechanism to check it is fully buildable today.

Two pieces:
- session_of(): classifies a UTC timestamp's hour into Asia/London/New
  York/the London-NY overlap (historically the highest-liquidity window,
  called out separately rather than arbitrarily picked as one or the
  other)/off-hours. Boundaries are a documented, adjustable STARTING
  CONVENTION (same "reasonable default, not a calibrated result" caveat
  every other DEFAULT_* constant in this codebase carries -- e.g.
  fib_gann_timing.DEFAULT_ZIGZAG_ATR_MULTIPLIER), not a founder-confirmed
  exact definition.
- group_into_session_blocks()/compute_session_bias(): groups consecutive
  same-day, same-session candles into one block (a session is a
  continuous period, not independent candles), then aggregates each
  session's block-level returns into descriptive statistics -- purely
  informational, matching the standing gate-vs-score principle (Section
  10): nothing here rejects a signal or blocks a trade, it's a raw
  market-behavior statistic, not yet wired into any signal-generation
  path.
"""

import dataclasses
import datetime
import enum
import statistics

import fib_gann_timing as fgt

# UTC hour ranges, half-open [start, end). A documented starting
# convention -- crypto trades 24/7 so there's no DST-adjusted "session
# open" the way forex desks observe; these are the commonly cited
# Asia/London/New York windows used in retail crypto/forex trading
# education, not derived from anything in this codebase.
DEFAULT_SESSION_BOUNDARIES_UTC = {
    "asia": (0, 8),
    "london": (8, 16),
    "new_york": (13, 21),
}


class TradingSession(enum.Enum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_NY_OVERLAP = "london_ny_overlap"  # historically the highest-liquidity window -- kept distinct, not folded into either
    OFF_HOURS = "off_hours"  # outside every named session -- still tracked, not dropped


def session_of(ts: datetime.datetime, boundaries: dict[str, tuple[int, int]] = DEFAULT_SESSION_BOUNDARIES_UTC) -> TradingSession:
    """Classifies ts's UTC hour. ts must be timezone-aware (same
    discipline as fib_gann_timing.Candle) -- converted to UTC first so a
    caller passing a non-UTC-but-aware datetime still gets the right
    session, not silently wrong."""
    if ts.tzinfo is None:
        raise ValueError(f"ts must be timezone-aware (UTC): {ts!r}")
    hour = ts.astimezone(datetime.timezone.utc).hour

    def _in(name: str) -> bool:
        start, end = boundaries[name]
        return start <= hour < end

    in_london, in_ny = _in("london"), _in("new_york")
    if in_london and in_ny:
        return TradingSession.LONDON_NY_OVERLAP
    if in_london:
        return TradingSession.LONDON
    if in_ny:
        return TradingSession.NEW_YORK
    if _in("asia"):
        return TradingSession.ASIA
    return TradingSession.OFF_HOURS


@dataclasses.dataclass(frozen=True)
class SessionBlock:
    session: TradingSession
    date: datetime.date  # UTC calendar date the block started on
    open_price: float  # open of the first candle in the block
    close_price: float  # close of the last candle in the block
    candle_count: int
    return_pct: float  # (close_price - open_price) / open_price


def group_into_session_blocks(
    candles: list[fgt.Candle], boundaries: dict[str, tuple[int, int]] = DEFAULT_SESSION_BOUNDARIES_UTC
) -> list[SessionBlock]:
    """A session is a continuous period, not independent candles -- this
    merges consecutive candles sharing the same (UTC date, session) into
    one block before computing a return, so a 5-candle Asia session
    becomes one return figure (open of candle 1 to close of candle 5),
    not five separate ones that would over-weight sessions with more
    candles in any per-block aggregate."""
    if not candles:
        raise ValueError("candles must not be empty")

    blocks: list[SessionBlock] = []
    current_session: TradingSession | None = None
    current_date: datetime.date | None = None
    open_price = close_price = 0.0
    candle_count = 0

    def _flush() -> None:
        blocks.append(
            SessionBlock(
                session=current_session,
                date=current_date,
                open_price=open_price,
                close_price=close_price,
                candle_count=candle_count,
                return_pct=(close_price - open_price) / open_price,
            )
        )

    for candle in candles:
        session = session_of(candle.ts, boundaries)
        date = candle.ts.astimezone(datetime.timezone.utc).date()
        if session == current_session and date == current_date:
            close_price = candle.close
            candle_count += 1
        else:
            if current_session is not None:
                _flush()
            current_session, current_date = session, date
            open_price = candle.open
            close_price = candle.close
            candle_count = 1

    _flush()
    return blocks


@dataclasses.dataclass(frozen=True)
class SessionBiasStats:
    session: TradingSession
    block_count: int
    mean_return_pct: float
    median_return_pct: float
    positive_block_fraction: float  # fraction of blocks with return_pct > 0 -- the direct "does this session usually go up" number


def compute_session_bias(blocks: list[SessionBlock]) -> dict[TradingSession, SessionBiasStats]:
    if not blocks:
        raise ValueError("blocks must not be empty")

    grouped: dict[TradingSession, list[float]] = {}
    for block in blocks:
        grouped.setdefault(block.session, []).append(block.return_pct)

    return {
        session: SessionBiasStats(
            session=session,
            block_count=len(returns),
            mean_return_pct=statistics.mean(returns),
            median_return_pct=statistics.median(returns),
            positive_block_fraction=sum(1 for r in returns if r > 0) / len(returns),
        )
        for session, returns in grouped.items()
    }
