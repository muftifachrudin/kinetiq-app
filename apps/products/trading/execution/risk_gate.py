"""Risk Hard Gate v1 (docs/prd.md's ENGGANG Layer 3) -- kill-switch,
symbol-universe permission, and a defensive R:R/entry-validity re-check.

ENGGANG's Layer 3 spec names 4 sub-gates: regime gate (FREEZE/RISK_OFF),
kNN risk memory veto, R:R gate, exposure caps. Only the 2 covered here are
well-specified enough to build responsibly today. Regime gate has no
classifier (market_regime.py doesn't exist yet -- see
fib-gann-validation-brief.md) and kNN risk memory has no algorithm spec
anywhere (no feature list, distance metric, k value, or veto threshold) --
building either now would mean inventing new hand-tuned logic for a
CODEOWNERS-gated safety-critical file, exactly what this project's own
ConfluenceWeights lesson (pearson r=-0.05, docs/CLAUDE.md) warns against.
Both are deferred to their own future design sessions. Exposure caps
(leverage/notional) already live in position_sizing.py, downstream of this
gate -- not duplicated here.

This module is intentionally DB-free and does not import agent-orchestrator's
Signal/ExitPlan types -- execution/ and agent-orchestrator/ are separate app
directories with no existing cross-app import precedent in this repo.
RiskMandateSnapshot is this module's own plain input shape; a future
orchestration layer is what translates a real signal into it.

All rejection reasons are collected, not fail-fast -- matches this
project's audit-transparency ethos (an operator debugging a rejected
signal should see every reason, not just the first check that ran).
"""

import dataclasses
import enum

# Reuses fib_gann_timing.DEFAULT_MIN_RR_THRESHOLD's value (1.5) rather than
# importing across the execution/agent-orchestrator app boundary for a
# single constant -- see design decision 4 in the Risk Hard Gate v1 plan.
DEFAULT_MIN_RR_THRESHOLD = 1.5


class TradeDirection(enum.Enum):
    LONG = "long"
    SHORT = "short"


@dataclasses.dataclass(frozen=True)
class RiskMandateSnapshot:
    """This gate's own plain input shape -- not the SQLAlchemy RiskMandate
    model, keeping this module DB-free like position_sizing.py/
    fib_gann_timing.py. symbol_universe=None means no restriction (every
    symbol permitted); an empty tuple means nothing is permitted."""

    kill_switch_active: bool
    symbol_universe: tuple[str, ...] | None


@dataclasses.dataclass(frozen=True)
class GateResult:
    passed: bool
    rejections: tuple[str, ...]


def evaluate_risk_gate(
    direction: TradeDirection,
    entry_price: float,
    stop_loss: float,
    take_profit_1: float | None,
    risk_reward_ratio: float | None,
    instrument_symbol: str,
    mandate: RiskMandateSnapshot,
    min_rr_threshold: float = DEFAULT_MIN_RR_THRESHOLD,
) -> GateResult:
    rejections: list[str] = []

    if mandate.kill_switch_active:
        rejections.append("kill_switch_active is True on the account mandate -- all trading halted")

    if mandate.symbol_universe is not None and instrument_symbol not in mandate.symbol_universe:
        rejections.append(f"{instrument_symbol!r} is not in the mandate's permitted symbol_universe {mandate.symbol_universe!r}")

    if take_profit_1 is None or risk_reward_ratio is None:
        rejections.append("no take_profit_1/risk_reward_ratio -- signal has no valid TP1 (defensive re-check of generate_signals()'s own invariant)")
    else:
        if risk_reward_ratio < min_rr_threshold:
            rejections.append(f"risk_reward_ratio {risk_reward_ratio:.3f} is below min_rr_threshold {min_rr_threshold:.3f}")
        if direction is TradeDirection.LONG and not (stop_loss < entry_price < take_profit_1):
            rejections.append(f"LONG entry_price {entry_price} is not between stop_loss {stop_loss} and take_profit_1 {take_profit_1}")
        if direction is TradeDirection.SHORT and not (take_profit_1 < entry_price < stop_loss):
            rejections.append(f"SHORT entry_price {entry_price} is not between take_profit_1 {take_profit_1} and stop_loss {stop_loss}")

    return GateResult(passed=not rejections, rejections=tuple(rejections))
