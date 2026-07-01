"""Initial schema: platform-core + trading vertical (docs/prd.md Section B.3/B.13/B.6b)

Revision ID: 0001
Revises:
Create Date: 2026-07-01

Raw SQL is used (rather than op.create_table) so that partitioned parent
tables, generated columns, and CHECK constraints match docs/prd.md exactly.
Each partitioned table gets a DEFAULT partition here so it is usable
immediately; infra/neon/partitioning/ owns rolling forward to proper
time-range partitions.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- Platform Core ---------------------------------------------------
    op.execute(
        """
        CREATE TABLE tenant (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            plan_tier TEXT NOT NULL DEFAULT 'signal_only'
                CHECK (plan_tier IN ('signal_only','auto_execute','meme_addon','dlmm_addon')),
            payment_provider TEXT,
            payment_customer_id TEXT,
            payment_subscription_status TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE platform_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenant(id),
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL DEFAULT 'tenant' CHECK (role IN ('superadmin','admin','tenant')),
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE llm_config (
            id SERIAL PRIMARY KEY,
            scope TEXT NOT NULL CHECK (scope IN ('global','product','tenant')),
            tenant_id UUID REFERENCES tenant(id),
            product_key TEXT,
            agent_skill_key TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'openrouter',
            model TEXT NOT NULL,
            params JSONB,
            updated_by UUID REFERENCES platform_user(id),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE token_package (
            id SERIAL PRIMARY KEY,
            package_key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            monthly_token_allowance BIGINT NOT NULL,
            price_usd NUMERIC(10,2) NOT NULL,
            discount_pct NUMERIC(5,2) DEFAULT 0,
            is_addon_topup BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            updated_by UUID REFERENCES platform_user(id),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute("ALTER TABLE tenant ADD COLUMN token_package_id INT REFERENCES token_package(id)")

    op.execute(
        """
        CREATE TABLE tenant_token_ledger (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            ts TIMESTAMPTZ DEFAULT now(),
            delta_tokens BIGINT NOT NULL,
            reason TEXT NOT NULL CHECK (reason IN ('monthly_reset','consumption','topup_purchase','admin_adjustment')),
            agent_skill_key TEXT,
            balance_after BIGINT NOT NULL
        )
        """
    )

    # --- Trading vertical: dimensions ------------------------------------
    op.execute(
        """
        CREATE TABLE venue (
            id SMALLSERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            venue_type TEXT NOT NULL CHECK (venue_type IN ('cex','dex')),
            is_active BOOLEAN DEFAULT TRUE
        )
        """
    )

    op.execute(
        """
        CREATE TABLE instrument (
            id SERIAL PRIMARY KEY,
            venue_id SMALLINT REFERENCES venue(id),
            symbol TEXT NOT NULL,
            venue_symbol TEXT NOT NULL,
            base_asset TEXT NOT NULL,
            quote_asset TEXT NOT NULL,
            contract_type TEXT NOT NULL,
            UNIQUE (venue_id, venue_symbol)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE data_source_health (
            venue_id SMALLINT REFERENCES venue(id),
            data_type TEXT NOT NULL,
            last_success_at TIMESTAMPTZ,
            last_failure_at TIMESTAMPTZ,
            consecutive_failures INT DEFAULT 0,
            PRIMARY KEY (venue_id, data_type)
        )
        """
    )

    # --- Trading vertical: time-series (range-partitioned by ts) --------
    op.execute(
        """
        CREATE TABLE funding_rate (
            instrument_id INT REFERENCES instrument(id),
            ts TIMESTAMPTZ NOT NULL,
            funding_rate NUMERIC(12,10) NOT NULL,
            predicted_next_rate NUMERIC(12,10),
            funding_interval_hours SMALLINT NOT NULL,
            mark_price NUMERIC(24,10),
            PRIMARY KEY (instrument_id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE TABLE funding_rate_default PARTITION OF funding_rate DEFAULT")

    op.execute(
        """
        CREATE TABLE open_interest (
            instrument_id INT REFERENCES instrument(id),
            ts TIMESTAMPTZ NOT NULL,
            oi_contracts NUMERIC(24,8) NOT NULL,
            oi_usd NUMERIC(24,4),
            PRIMARY KEY (instrument_id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE TABLE open_interest_default PARTITION OF open_interest DEFAULT")

    op.execute(
        """
        CREATE TABLE price_basis (
            instrument_id INT REFERENCES instrument(id),
            ts TIMESTAMPTZ NOT NULL,
            mark_price NUMERIC(24,10) NOT NULL,
            index_price NUMERIC(24,10) NOT NULL,
            basis NUMERIC(24,10) GENERATED ALWAYS AS (mark_price - index_price) STORED,
            basis_pct NUMERIC(12,8) GENERATED ALWAYS AS ((mark_price - index_price) / NULLIF(index_price,0)) STORED,
            PRIMARY KEY (instrument_id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE TABLE price_basis_default PARTITION OF price_basis DEFAULT")

    op.execute(
        """
        CREATE TABLE orderbook_snapshot (
            instrument_id INT REFERENCES instrument(id),
            ts TIMESTAMPTZ NOT NULL,
            bids JSONB NOT NULL,
            asks JSONB NOT NULL,
            bid_depth_usd_1pct NUMERIC(24,4),
            ask_depth_usd_1pct NUMERIC(24,4),
            PRIMARY KEY (instrument_id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE TABLE orderbook_snapshot_default PARTITION OF orderbook_snapshot DEFAULT")

    op.execute(
        """
        CREATE TABLE liquidation_event (
            id BIGSERIAL,
            instrument_id INT REFERENCES instrument(id),
            ts TIMESTAMPTZ NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('long','short')),
            qty NUMERIC(24,8) NOT NULL,
            price NUMERIC(24,10) NOT NULL,
            notional_usd NUMERIC(24,4),
            PRIMARY KEY (id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE TABLE liquidation_event_default PARTITION OF liquidation_event DEFAULT")

    op.execute(
        """
        CREATE TABLE market_sentiment (
            instrument_id INT REFERENCES instrument(id),
            ts TIMESTAMPTZ NOT NULL,
            long_short_ratio NUMERIC(10,4),
            top_trader_long_short_ratio NUMERIC(10,4),
            taker_buy_vol NUMERIC(24,8),
            taker_sell_vol NUMERIC(24,8),
            PRIMARY KEY (instrument_id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE TABLE market_sentiment_default PARTITION OF market_sentiment DEFAULT")

    op.execute(
        """
        CREATE TABLE ohlcv (
            instrument_id INT REFERENCES instrument(id),
            timeframe TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            open NUMERIC(24,10), high NUMERIC(24,10), low NUMERIC(24,10), close NUMERIC(24,10),
            volume NUMERIC(24,8),
            PRIMARY KEY (instrument_id, timeframe, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE TABLE ohlcv_default PARTITION OF ohlcv DEFAULT")

    # --- Trading vertical: domain / trading state ------------------------
    op.execute(
        """
        CREATE TABLE strategy (
            id SERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            params JSONB NOT NULL,
            is_paper BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE portfolio_target (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            strategy_id INT REFERENCES strategy(id) NOT NULL,
            computed_at TIMESTAMPTZ NOT NULL,
            instrument_id INT REFERENCES instrument(id) NOT NULL,
            target_weight NUMERIC(8,6),
            target_leverage NUMERIC(6,3),
            expected_return_components JSONB
        )
        """
    )

    op.execute(
        """
        CREATE TABLE position (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            account_id INT NOT NULL,
            venue_id SMALLINT REFERENCES venue(id) NOT NULL,
            instrument_id INT REFERENCES instrument(id) NOT NULL,
            is_paper BOOLEAN DEFAULT TRUE,
            side TEXT CHECK (side IN ('long','short')),
            qty NUMERIC(24,8),
            entry_price NUMERIC(24,10),
            leverage NUMERIC(6,3),
            liquidation_price NUMERIC(24,10),
            opened_at TIMESTAMPTZ,
            closed_at TIMESTAMPTZ
        )
        """
    )

    op.execute(
        """
        CREATE TABLE order_audit_log (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            ts TIMESTAMPTZ DEFAULT now(),
            account_id INT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            payload JSONB NOT NULL,
            is_paper BOOLEAN NOT NULL,
            result TEXT
        )
        """
    )

    op.execute(
        """
        CREATE TABLE risk_mandate (
            tenant_id UUID REFERENCES tenant(id),
            account_id INT NOT NULL,
            max_leverage NUMERIC(6,3) DEFAULT 3,
            max_position_notional_usd NUMERIC(24,4),
            max_daily_loss_usd NUMERIC(24,4),
            max_drawdown_pct NUMERIC(6,4) DEFAULT 0.15,
            symbol_universe TEXT[],
            kill_switch_active BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (tenant_id, account_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE tenant_credential (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            venue_id SMALLINT REFERENCES venue(id) NOT NULL,
            credential_type TEXT NOT NULL CHECK (credential_type IN ('api_key_trade_only','agent_wallet')),
            encrypted_payload BYTEA NOT NULL,
            data_key_encrypted BYTEA NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    # --- Meme-sniper (V2) / DLMM (V3) — created now so schema is stable,
    #     features themselves land later per the roadmap (B.9) -----------
    op.execute(
        """
        CREATE TABLE token_launch_event (
            id BIGSERIAL PRIMARY KEY,
            chain TEXT NOT NULL,
            token_address TEXT NOT NULL,
            pair_address TEXT,
            detected_at TIMESTAMPTZ NOT NULL,
            initial_liquidity_usd NUMERIC(24,4),
            safety_score NUMERIC(5,2),
            safety_flags JSONB
        )
        """
    )

    op.execute(
        """
        CREATE TABLE dlmm_position (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            pool_address TEXT NOT NULL,
            lower_bin INT, upper_bin INT,
            liquidity_usd NUMERIC(24,4),
            fees_earned_usd NUMERIC(24,4) DEFAULT 0,
            impermanent_loss_usd NUMERIC(24,4) DEFAULT 0,
            opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ
        )
        """
    )

    # --- Trader profile / Shadow Account (B.6b) --------------------------
    op.execute(
        """
        CREATE TABLE trade_annotation (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            instrument_id INT REFERENCES instrument(id) NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            swing_ref JSONB,
            fib_level NUMERIC(8,6),
            gann_angle TEXT,
            action TEXT NOT NULL,
            rationale_text TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    # order_audit_log is append-only: revoke UPDATE/DELETE from the
    # application role once that role exists (see infra/neon/README.md).
    # Left as a follow-up because the app DB role is provisioned per
    # environment, not by this migration.


def downgrade() -> None:
    for table in (
        "trade_annotation",
        "dlmm_position",
        "token_launch_event",
        "tenant_credential",
        "risk_mandate",
        "order_audit_log",
        "position",
        "portfolio_target",
        "strategy",
        "ohlcv",
        "market_sentiment",
        "liquidation_event",
        "orderbook_snapshot",
        "price_basis",
        "open_interest",
        "funding_rate",
        "data_source_health",
        "instrument",
        "venue",
        "tenant_token_ledger",
        "token_package",
        "llm_config",
        "platform_user",
        "tenant",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
