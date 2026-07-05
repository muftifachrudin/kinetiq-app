"""F7a (docs/sonnet5-implementation-roadmap.md), spec + design rationale in
docs/margin-mode-brief.md Section 4 -- read that first. Pure-function skill,
no DB/ccxt/LangGraph coupling, same discipline as fib_gann_timing.py/
shadow_pair.py/trade_simulator.py: this module answers the founder's two
pre-execution questions ("berapa initial margin, berapa leverage") for a
signal that has already passed every gate, before the trade is placed.

Margin mode comes from the MANDATE, not per-trade (brief Section 1): letting
it vary per-signal would add a new hand-tuned degree of freedom -- exactly
the class of mistake the F1 deep-dive (confidence anti-predictive) showed is
expensive -- and would make shadow-pair attribution across trades
incomparable. MVP only supports ISOLATED, where liquidation price is
deterministic at signal time with no portfolio state; CROSS raises
NotImplementedError pointing at F7b rather than pretending to compute a
number that would actually need total account equity/unrealized PnL to be
correct (brief Section 1, point 2).

Leverage/margin math is NOT reimplemented here -- max_safe_leverage(),
build_margin_context(), and assert_liquidation_safe() are reused directly
from trade_simulator.py (brief's explicit instruction: "jangan tulis
ulang"). leverage_used = min(mandate's max_leverage_cap, ETA_SAFETY_FACTOR
* max_safe_leverage, LEVERAGE_ONSET_CEILING) is the one new formula this
module adds: leverage is an OUTPUT of trade structure (risk_amount -> qty
-> leverage), never a user-chosen input, matching the same principle
shadow-simulator-brief Section 5 already established for risk sizing
generally.

ETA_SAFETY_FACTOR/LEVERAGE_ONSET_CEILING (brief Section 7, PR #101's
empirical margin-envelope research replaying 622 real stack trades with
liquidation-before-SL mechanics): PF-vs-leverage is a flat 1.309 from
2x-20x -- structural leverage never touches PF at all while the
liquidation price stays beyond SL+buffer, it's purely a capital-lock
dial -- then decays past ~20x as liquidations start appearing (25x: 0.5%
of trades liquidated, PF 1.282; 50x: 14.6% liquidated, PF 1.123). There is
no PF benefit whatsoever above ~20x, only tail-risk, so LEVERAGE_ONSET_
CEILING=20 is a hard cap independent of any mandate setting; ETA_SAFETY_
FACTOR=0.5 keeps leverage_used a further margin below max_safe_leverage's
own boundary (extra cushion for gap/wick risk max_safe_leverage's exact
algebraic derivation doesn't itself account for).

Two distance-vs-price scales, deliberately both reported (brief Section 4,
citing brief-utama bag. 13's lesson that margin_return can be -50% from a
notional move of only -1.5%): sl_distance_pct_notional/tp1_distance_pct_
notional are plain price-move percentages; the *_pct_margin variants
multiply by leverage_used, showing what the same move means against the
capital actually at risk. Reporting only one scale would hide exactly the
gap the founder flagged as their real-money experience.

assert_liquidation_safe() is invoked as a hard invariant, not merely one of
the warnings tuple -- brief Section 4: "kartu TIDAK terbit untuk kombinasi
yang melanggarnya." It raises trade_simulator.UnsafeLeverageError (letting
that exception propagate, not catching/wrapping it) before any PreTradeCard
is constructed, so a caller never receives a card for an unsafe setup.

derivatives_context (F4, optional) influence is one-directional by design
(brief Section 3's high-vol/liq-cascade finding): a high-vol flag can only
shrink effective_risk_pct, never enlarge it and never touch leverage_cap
upward. There is no path in this module that increases risk or leverage in
response to any input -- only the mandate's own values and the structural
safety invariant bound them.
"""

import dataclasses
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "validation", "fib_gann_backtest"))

import fib_gann_timing as fgt  # noqa: E402
import trade_simulator as ts  # noqa: E402

# Brief Section 3: derivatives_context can only ever shrink risk, applied as
# a flat multiplier when a high-vol/liq-cascade flag is set. Not fitted --
# a manual, conservative starting point like DEFAULT_LIQUIDATION_BUFFER_K.
HIGH_VOL_RISK_MULTIPLIER = 0.5

# Brief Section 7 / PR #101's empirical lev_curve.py finding (module
# docstring): no PF benefit above ~20x (only tail-risk from there), and an
# extra 0.5x safety margin below the trade's own algebraic max_safe_
# leverage boundary. Both are hard bounds on leverage_used -- neither is
# fitted, both are the "initial numbers are free, evidence decides
# adoption" kind of constant this codebase's other modules already use.
ETA_SAFETY_FACTOR = 0.5
LEVERAGE_ONSET_CEILING = 20.0


class CrossMarginNotImplementedError(NotImplementedError):
    """Raised when margin_mode is CROSS. Brief Section 1: cross needs
    portfolio-wide equity/unrealized-PnL state this per-signal card doesn't
    have; see F7b (docs/sonnet5-implementation-roadmap.md) for when it's
    built, once the shadow loop (F7) has real position state to derive it
    from. Never silently approximated in the meantime."""


@dataclasses.dataclass(frozen=True)
class PreTradeCard:
    risk_amount_usd: float
    qty: float
    notional_usd: float
    max_safe_leverage: float
    leverage_used: float
    initial_margin_usd: float
    est_liquidation_price: float
    margin_ratio_at_entry: float  # maintenance_margin_rate / initial_margin_fraction -- informative, not a gate
    sl_distance_pct_notional: float
    sl_distance_pct_margin: float
    tp1_distance_pct_notional: float | None  # None when exit_plan has no take_profits
    tp1_distance_pct_margin: float | None
    warnings: tuple[str, ...]


def _distance_pct(entry_price: float, level_price: float) -> float:
    return abs(level_price - entry_price) / entry_price


def build_pre_trade_card(
    exit_plan: fgt.ExitPlan,
    atr_value: float,
    equity_usd: float,
    risk_pct_per_trade: float,
    margin_mode: ts.MarginMode,
    max_leverage_cap: float,
    maintenance_margin_rate: float = ts.DEFAULT_MAINTENANCE_MARGIN_RATE,
    buffer_k: float = ts.DEFAULT_LIQUIDATION_BUFFER_K,
    free_balance_usd: float | None = None,
    high_vol_flag: bool = False,
) -> PreTradeCard:
    """Builds the pre-execution sizing/leverage card for a signal that has
    already passed signal_runner/gate logic -- this module never touches
    signal_runner or any gate, purely a downstream presentation+sizing layer
    (brief Section 4's explicit scope boundary).

    free_balance_usd is optional caller-supplied context (this module has no
    portfolio state of its own, same limitation trade_simulator.MarginContext
    documents for cross_buffer_pct) -- used only to emit a warning, never to
    change any computed number.
    """
    if margin_mode is ts.MarginMode.CROSS:
        raise CrossMarginNotImplementedError("cross margin mode sizing is F7b (docs/sonnet5-implementation-roadmap.md) -- not implemented yet")
    if equity_usd <= 0:
        raise ValueError("equity_usd must be positive")
    if risk_pct_per_trade <= 0:
        raise ValueError("risk_pct_per_trade must be positive")
    if max_leverage_cap <= 0:
        raise ValueError("max_leverage_cap must be positive")

    effective_risk_pct = risk_pct_per_trade * HIGH_VOL_RISK_MULTIPLIER if high_vol_flag else risk_pct_per_trade

    entry_price = exit_plan.entry_price
    stop_loss = exit_plan.stop_loss
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance <= 0:
        raise ValueError("exit_plan.stop_loss must differ from entry_price")

    risk_amount_usd = equity_usd * effective_risk_pct
    qty = risk_amount_usd / sl_distance
    notional_usd = qty * entry_price

    max_safe = ts.max_safe_leverage(entry_price, stop_loss, atr_value, maintenance_margin_rate, buffer_k)
    leverage_used = min(max_leverage_cap, ETA_SAFETY_FACTOR * max_safe, LEVERAGE_ONSET_CEILING)

    margin_context = ts.build_margin_context(entry_price, exit_plan.direction, leverage_used, margin_mode, maintenance_margin_rate)
    ts.assert_liquidation_safe(entry_price, stop_loss, atr_value, margin_context, buffer_k)

    initial_margin_usd = notional_usd / leverage_used
    margin_ratio_at_entry = maintenance_margin_rate / margin_context.initial_margin_fraction

    sl_distance_pct_notional = _distance_pct(entry_price, stop_loss)
    sl_distance_pct_margin = sl_distance_pct_notional * leverage_used

    tp1_distance_pct_notional = None
    tp1_distance_pct_margin = None
    if exit_plan.take_profits:
        tp1_distance_pct_notional = _distance_pct(entry_price, exit_plan.take_profits[0])
        tp1_distance_pct_margin = tp1_distance_pct_notional * leverage_used

    warnings = []
    if leverage_used < max_leverage_cap:
        binding_reason = (
            f"the {LEVERAGE_ONSET_CEILING:.0f}x empirical onset ceiling (brief Section 7 -- no PF benefit above this, only tail-risk)"
            if leverage_used == LEVERAGE_ONSET_CEILING
            else f"trade structure (SL distance vs ATR buffer, x{ETA_SAFETY_FACTOR} safety factor)"
        )
        warnings.append(f"leverage_used {leverage_used:.2f}x is below max_leverage_cap {max_leverage_cap:.2f}x -- {binding_reason}, not the mandate cap, is what's limiting leverage here")
    liq_distance_pct = _distance_pct(entry_price, margin_context.liquidation_price)
    required_pct = sl_distance_pct_notional + buffer_k * (atr_value / entry_price)
    if liq_distance_pct < required_pct * 1.1:
        warnings.append(
            f"liquidation distance ({liq_distance_pct:.4%}) sits close to the required safety buffer "
            f"({required_pct:.4%}) -- little room before a small ATR/parameter change would reject this setup"
        )
    if free_balance_usd is not None and initial_margin_usd > free_balance_usd:
        warnings.append(f"initial_margin_usd ({initial_margin_usd:.2f}) exceeds the supplied free_balance_usd ({free_balance_usd:.2f})")

    return PreTradeCard(
        risk_amount_usd=risk_amount_usd,
        qty=qty,
        notional_usd=notional_usd,
        max_safe_leverage=max_safe,
        leverage_used=leverage_used,
        initial_margin_usd=initial_margin_usd,
        est_liquidation_price=margin_context.liquidation_price,
        margin_ratio_at_entry=margin_ratio_at_entry,
        sl_distance_pct_notional=sl_distance_pct_notional,
        sl_distance_pct_margin=sl_distance_pct_margin,
        tp1_distance_pct_notional=tp1_distance_pct_notional,
        tp1_distance_pct_margin=tp1_distance_pct_margin,
        warnings=tuple(warnings),
    )
