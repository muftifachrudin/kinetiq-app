"""SQLAlchemy models — source of truth schema for Kinetiq.

Kinetiq is a single-operator agentic trading system (no multi-tenant
platform-core layer — see migration 0009, which dropped `tenant`/
`platform_user`/`llm_config`/`token_package`/`tenant_token_ledger` and
stripped `tenant_id` from every trading table). Mirrors docs/prd.md's
data-model section. Time-series tables (funding_rate, open_interest,
price_basis, orderbook_snapshot, liquidation_event, market_sentiment,
ohlcv) are range-partitioned by `ts` — see
migrations/versions/0001_initial_schema.py for the partition DDL and
infra/neon/partitioning/ for the ongoing partition-rollover job.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# --- Trading vertical: dimensions ------------------------------------------


class Venue(Base):
    __tablename__ = "venue"

    id = Column(SmallInteger, primary_key=True, autoincrement=True)
    name = Column(Text, unique=True, nullable=False)
    venue_type = Column(Text, nullable=False)
    is_active = Column(Boolean, server_default="true")

    __table_args__ = (CheckConstraint("venue_type in ('cex','dex')", name="ck_venue_type"),)


class Instrument(Base):
    __tablename__ = "instrument"

    id = Column(Integer, primary_key=True, autoincrement=True)
    venue_id = Column(SmallInteger, ForeignKey("venue.id"), nullable=False)
    symbol = Column(Text, nullable=False)
    venue_symbol = Column(Text, nullable=False)
    base_asset = Column(Text, nullable=False)
    quote_asset = Column(Text, nullable=False)
    contract_type = Column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("venue_id", "venue_symbol", name="uq_instrument_venue_symbol"),)


class DataSourceHealth(Base):
    __tablename__ = "data_source_health"

    venue_id = Column(SmallInteger, ForeignKey("venue.id"), primary_key=True)
    data_type = Column(Text, primary_key=True)
    last_success_at = Column(DateTime(timezone=True))
    last_failure_at = Column(DateTime(timezone=True))
    consecutive_failures = Column(Integer, server_default="0")


# --- Trading vertical: time-series (range-partitioned by ts) --------------
# NOTE: partition DDL (PARTITION BY RANGE) and the default catch-all
# partition are created in the migration via raw SQL, matching docs/prd.md
# Section B.3. These ORM classes describe the parent table shape only.


class FundingRate(Base):
    __tablename__ = "funding_rate"

    instrument_id = Column(Integer, ForeignKey("instrument.id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    funding_rate = Column(Numeric(12, 10), nullable=False)
    predicted_next_rate = Column(Numeric(12, 10))
    funding_interval_hours = Column(SmallInteger, nullable=False)
    mark_price = Column(Numeric(24, 10))

    __table_args__ = {"postgresql_partition_by": "RANGE (ts)"}


class OpenInterest(Base):
    __tablename__ = "open_interest"

    instrument_id = Column(Integer, ForeignKey("instrument.id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    oi_contracts = Column(Numeric(24, 8), nullable=False)
    oi_usd = Column(Numeric(24, 4))

    __table_args__ = {"postgresql_partition_by": "RANGE (ts)"}


class PriceBasis(Base):
    __tablename__ = "price_basis"

    instrument_id = Column(Integer, ForeignKey("instrument.id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    mark_price = Column(Numeric(24, 10), nullable=False)
    index_price = Column(Numeric(24, 10), nullable=False)

    __table_args__ = {"postgresql_partition_by": "RANGE (ts)"}
    # basis / basis_pct are GENERATED ALWAYS columns, added via raw SQL in
    # the migration (SQLAlchemy Column doesn't model generated columns
    # portably across dialects).


class OrderbookSnapshot(Base):
    __tablename__ = "orderbook_snapshot"

    instrument_id = Column(Integer, ForeignKey("instrument.id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    bids = Column(JSONB, nullable=False)
    asks = Column(JSONB, nullable=False)
    bid_depth_usd_1pct = Column(Numeric(24, 4))
    ask_depth_usd_1pct = Column(Numeric(24, 4))

    __table_args__ = {"postgresql_partition_by": "RANGE (ts)"}


class LiquidationEvent(Base):
    __tablename__ = "liquidation_event"

    id = Column(BigInteger, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False)
    ts = Column(DateTime(timezone=True), primary_key=True)
    side = Column(Text, nullable=False)
    qty = Column(Numeric(24, 8), nullable=False)
    price = Column(Numeric(24, 10), nullable=False)
    notional_usd = Column(Numeric(24, 4))

    __table_args__ = (
        CheckConstraint("side in ('long','short')", name="ck_liquidation_event_side"),
        {"postgresql_partition_by": "RANGE (ts)"},
    )


class MarketSentiment(Base):
    __tablename__ = "market_sentiment"

    instrument_id = Column(Integer, ForeignKey("instrument.id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    long_short_ratio = Column(Numeric(10, 4))
    top_trader_long_short_ratio = Column(Numeric(10, 4))
    taker_buy_vol = Column(Numeric(24, 8))
    taker_sell_vol = Column(Numeric(24, 8))

    __table_args__ = {"postgresql_partition_by": "RANGE (ts)"}


class Ohlcv(Base):
    __tablename__ = "ohlcv"

    instrument_id = Column(Integer, ForeignKey("instrument.id"), primary_key=True)
    timeframe = Column(Text, primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    open = Column(Numeric(24, 10))
    high = Column(Numeric(24, 10))
    low = Column(Numeric(24, 10))
    close = Column(Numeric(24, 10))
    volume = Column(Numeric(24, 8))

    __table_args__ = {"postgresql_partition_by": "RANGE (ts)"}


# --- Trading vertical: domain / trading state ------------------------------


class Strategy(Base):
    __tablename__ = "strategy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    type = Column(Text, nullable=False)
    params = Column(JSONB, nullable=False)
    is_paper = Column(Boolean, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PortfolioTarget(Base):
    __tablename__ = "portfolio_target"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("strategy.id"), nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False)
    target_weight = Column(Numeric(8, 6))
    target_leverage = Column(Numeric(6, 3))
    expected_return_components = Column(JSONB)


class Position(Base):
    __tablename__ = "position"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False)
    venue_id = Column(SmallInteger, ForeignKey("venue.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False)
    is_paper = Column(Boolean, server_default="true")
    side = Column(Text)
    qty = Column(Numeric(24, 8))
    entry_price = Column(Numeric(24, 10))
    leverage = Column(Numeric(6, 3))
    liquidation_price = Column(Numeric(24, 10))
    opened_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    # docs/daily-loss-limit-exposure-cap-brief.md Section 2 -- explicit
    # status replacing the fragile "closed_at IS NULL means open"
    # convention; exit_price/realized_pnl_usd populated when a position
    # closes (neither existed before this migration, so realized PnL was
    # literally uncomputable even after the fact).
    status = Column(Text, nullable=False)
    exit_price = Column(Numeric(24, 10))
    realized_pnl_usd = Column(Numeric(24, 4))

    __table_args__ = (
        CheckConstraint("side in ('long','short')", name="ck_position_side"),
        CheckConstraint("status in ('open', 'closed')", name="ck_position_status"),
    )


class OrderAuditLog(Base):
    """Append-only. INSERT-only DB grant enforced in the migration, not the ORM."""

    __tablename__ = "order_audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ts = Column(DateTime(timezone=True), server_default=func.now())
    account_id = Column(Integer, nullable=False)
    actor = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    is_paper = Column(Boolean, nullable=False)
    result = Column(Text)


class RiskMandate(Base):
    __tablename__ = "risk_mandate"

    account_id = Column(Integer, primary_key=True)
    max_leverage = Column(Numeric(6, 3), server_default="3")
    max_position_notional_usd = Column(Numeric(24, 4))
    max_daily_loss_usd = Column(Numeric(24, 4))
    max_drawdown_pct = Column(Numeric(6, 4), server_default="0.15")
    symbol_universe = Column(ARRAY(Text))
    kill_switch_active = Column(Boolean, server_default="false")
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    # F7a (docs/margin-mode-brief.md Section 5): margin mode is decided once
    # at the mandate level, not per-trade -- see position_sizing.py. MVP
    # only implements ISOLATED sizing; 'cross' is a valid mandate value
    # (surfaced in onboarding as "coming soon") but position_sizing.py
    # raises NotImplementedError for it until F7b.
    default_margin_mode = Column(Text, server_default="isolated")
    risk_pct_per_trade = Column(Numeric(5, 4), server_default="0.01")

    __table_args__ = (CheckConstraint("default_margin_mode in ('cross', 'isolated')", name="ck_risk_mandate_default_margin_mode"),)


class EquitySnapshot(Base):
    """docs/daily-loss-limit-exposure-cap-brief.md Section 2 -- periodic
    equity ledger (composite PK, no surrogate id, same time-series
    convention as funding_rate/ohlcv/onchain_exchange_flow). Source of
    truth for "equity at start of today"/"peak equity ever" that the
    daily-loss-limit/drawdown-kill-switch formulas need -- recomputing
    those from raw position history on every gate check would be
    expensive and fragile. Nothing writes to this table yet; that's a
    future implementation step once a live orchestration layer exists."""

    __tablename__ = "equity_snapshot"

    account_id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    equity_usd = Column(Numeric(24, 4), nullable=False)
    realized_pnl_usd = Column(Numeric(24, 4))
    unrealized_pnl_usd = Column(Numeric(24, 4))


class Credential(Base):
    """Envelope-encrypted operator API key / agent-wallet. Never store a
    raw secret here — encrypted_payload + data_key_encrypted only."""

    __tablename__ = "credential"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    venue_id = Column(SmallInteger, ForeignKey("venue.id"), nullable=False)
    credential_type = Column(Text, nullable=False)
    encrypted_payload = Column(LargeBinary, nullable=False)
    data_key_encrypted = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "credential_type in ('api_key_trade_only','agent_wallet')",
            name="ck_credential_type",
        ),
    )


# --- On-chain intel (collect-only, not wired into signal/confidence) ------


class OnchainExchangeFlow(Base):
    """USD in/outflow of an asset between a tracked entity (e.g. a CEX) and
    the rest of the chain, per data point from an on-chain intel vendor
    (Arkham). Collect-only -- no FK into instrument/venue, not read by
    anything in the signal pipeline yet (see migration 0010's docstring).

    Composite PK (no surrogate id), matching funding_rate/ohlcv/
    open_interest's convention -- required for db.merge() to upsert
    idempotently in ingest_onchain.py."""

    __tablename__ = "onchain_exchange_flow"

    source = Column(Text, primary_key=True, server_default="arkham")
    entity = Column(Text, primary_key=True)
    chain = Column(Text, primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    inflow_usd = Column(Numeric(24, 4))
    outflow_usd = Column(Numeric(24, 4))
    cumulative_inflow_usd = Column(Numeric(24, 4))
    cumulative_outflow_usd = Column(Numeric(24, 4))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- Meme-sniper (V2) -------------------------------------------------------


class TokenLaunchEvent(Base):
    __tablename__ = "token_launch_event"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    chain = Column(Text, nullable=False)
    token_address = Column(Text, nullable=False)
    pair_address = Column(Text)
    detected_at = Column(DateTime(timezone=True), nullable=False)
    initial_liquidity_usd = Column(Numeric(24, 4))
    safety_score = Column(Numeric(5, 2))
    safety_flags = Column(JSONB)


# --- DLMM (V3) ---------------------------------------------------------------


class DlmmPosition(Base):
    __tablename__ = "dlmm_position"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pool_address = Column(Text, nullable=False)
    lower_bin = Column(Integer)
    upper_bin = Column(Integer)
    liquidity_usd = Column(Numeric(24, 4))
    fees_earned_usd = Column(Numeric(24, 4), server_default="0")
    impermanent_loss_usd = Column(Numeric(24, 4), server_default="0")
    opened_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))


# --- Trader profile / Shadow Account (Section B.6b) -------------------------


class Signal(Base):
    """F0b (docs/sonnet5-implementation-roadmap.md): persisted mirror of
    apps/products/trading/agent-orchestrator/validation/fib_gann_backtest/
    signal_runner.Signal, the in-memory dataclass every Fase 1-5 backtest
    module already produces. Deliberately NOT built until now -- migration
    0005's own docstring and shadow_pair.py's module docstring both said so
    explicitly ("building a signal table now, with no live writer, would be
    exactly the kind of design for a hypothetical future requirement this
    codebase's own conventions warn against"). That blocker is resolved:
    fit_weights.py (Fase 3) and the F7 shadow loop are real, existing
    consumers/writers this table serves.

    No tenant_id / RLS -- same convention as ohlcv/funding_rate/
    open_interest: this is shared strategy-engine output describing market
    timing for one instrument, not tenant-owned data. Not partitioned by ts
    (unlike those tables) -- signal volume is orders of magnitude lower
    (one row per gated touch-bar, not per candle across every instrument),
    matching trade_annotation's own unpartitioned scale rather than ohlcv's.

    factor_scores mirrors signal_runner.Signal's per-factor dump fields
    (swing_quality, fib_gann_confluence, ..., liq_cascade_flag) as a flat
    JSONB object -- exactly the payload Fase 3/4 already compute, just not
    yet written anywhere durable. A future live writer (F7) is expected to
    serialize dataclasses.asdict()-shaped data here; this migration only
    adds the column, it does not write to it.
    """

    __tablename__ = "signal"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False)
    timeframe = Column(Text, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)
    direction = Column(Text, nullable=False)
    entry_price = Column(Numeric(24, 10), nullable=False)
    stop_loss = Column(Numeric(24, 10), nullable=False)
    take_profit_1 = Column(Numeric(24, 10))  # nullable: ExitPlan.take_profits can be empty
    confidence = Column(Numeric(5, 4), nullable=False)
    factor_scores = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("direction in ('long', 'short')", name="ck_signal_direction"),
        UniqueConstraint("instrument_id", "timeframe", "ts", name="uq_signal_instrument_timeframe_ts"),
    )


class TradeAnnotation(Base):
    """Founder (MVP) trade annotations used to calibrate fib_gann_timing.

    Execution columns (leverage through exit_reason_real) were added in
    migration 0005 (docs/shadow-simulator-brief.md Option 2) so a real,
    manually-logged trade can eventually be paired against its
    trade_simulator.py counterpart -- all nullable, since a signal without
    a real trade behind it is still annotated with the real-side columns
    empty (brief: "Sinyal tanpa trade real tetap disimulasikan dan
    dicatat"). signal_id (F0b, this migration) links a row to the `signal`
    table's persisted record when one exists -- nullable, since every
    manually-logged annotation up to and including this migration predates
    the `signal` table's existence and has nothing to link to; shadow_pair.
    py's heuristic (time+direction) matcher remains how pairing actually
    happens until F7's live loop starts populating this column going
    forward.
    """

    __tablename__ = "trade_annotation"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id = Column(Integer, ForeignKey("instrument.id"), nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)
    swing_ref = Column(JSONB)
    fib_level = Column(Numeric(8, 6))
    gann_angle = Column(Text)
    action = Column(Text, nullable=False)
    rationale_text = Column(Text)
    signal_id = Column(BigInteger, ForeignKey("signal.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Real execution data (all nullable -- see class docstring)
    leverage = Column(Numeric(6, 3))
    margin_mode = Column(Text)
    entry_fill_price = Column(Numeric(24, 10))
    exit_fill_price = Column(Numeric(24, 10))
    # Deviates from the brief's literal "fees_paid"/"funding_paid" names --
    # explicit _usd suffix to match this schema's own existing convention
    # for dollar amounts (RiskMandate.max_position_notional_usd,
    # max_daily_loss_usd), and to remove any ambiguity with
    # trade_simulator.py's percent-of-notional fee/funding fractions,
    # which this table does NOT use (a human fills this in from their
    # exchange's real trade history, in dollars, not a computed fraction).
    fees_paid_usd = Column(Numeric(24, 4))
    funding_paid_usd = Column(Numeric(24, 4))
    exit_reason_real = Column(Text)

    __table_args__ = (
        CheckConstraint("margin_mode in ('cross','isolated')", name="ck_trade_annotation_margin_mode"),
        CheckConstraint(
            "exit_reason_real in ('stop_loss','take_profit','liquidated','timeout','manual_override')",
            name="ck_trade_annotation_exit_reason_real",
        ),
    )
