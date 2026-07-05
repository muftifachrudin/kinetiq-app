"""Controlled experiment following the Fase 6 campaign's own investigation
(docs/sonnet5-implementation-roadmap.md Fase 6, docs/fib-gann-validation-
brief.md Section 27): BTC failed promotion in every config tested so far
despite the walk-forward-refit model (fit_weights.ALL_CANDIDATE_FEATURE_
NAMES) showing genuine out-of-sample ranking power (median AUC 0.54-0.71
for BTC) -- that ranking power is never actually used to filter which
signals get traded. Separately, a direction x regime breakdown showed
BTC's "bull regime is worst" finding is largely an artifact of mixing
trend-aligned trades (good: bull+long PF 1.20, bear+short PF 1.38) with
counter-trend trades (bad: bull+short PF 0.64, bear+long PF 0.61).

This module tests BOTH as controlled gates, independently and combined,
same "let evidence decide, never auto-apply" discipline as every prior
phase (Fase 3's evaluate_adoption(), Fase 5/6's A/B framing) -- a new
default is never picked here, only measured.

CONFIDENCE GATE: per walk-forward window, fits a LogisticRegression on
TRAIN-range signals only (same model fit_weights._fit_binary() already
performs, replicated here to get direct access to the fitted model object
for per-signal predict_proba, which SchemeResult's aggregate summary
doesn't expose) using fit_weights.ALL_CANDIDATE_FEATURE_NAMES. The keep/
reject cutoff is the given percentile of the TRAIN set's OWN predicted-
probability distribution -- derived purely from train data, so applying
it to filter TEST-range signals introduces no lookahead. A window whose
train data can't support a fit (too few samples, single outcome class --
same MIN_TRAIN_SAMPLES guard fit_weights.py uses) passes every signal
through unfiltered for that window rather than raising or silently
dropping the window.

TREND-ALIGNMENT GATE: keeps only signals whose sma_trend_bias_alignment
(htf_bias.py, Fase 2/3 candidate column -- found more informative than
swing-based htf_alignment by the July deep-dive's F9 finding) exceeds a
threshold -- i.e., only trades a signal's own direction actually agrees
with the higher-timeframe SMA trend. No per-window fitting needed (this
factor is already computed at signal-generation time), so no lookahead
concern at all.

DAILY-BIAS GATE (F6b I1(b), the LITERAL variant -- docs/sonnet5-
implementation-roadmap.md): keeps only signals whose daily_bias_alignment
(signal_runner.py, single-timeframe swing-based Daily bias, distinct from
the SMA proxy above) exceeds a threshold -- the founder's original theory
v2 pasal (b) itself ("LONG melawan downtrend Daily = premis trade
invalid"), not a stand-in for it. Same no-lookahead reasoning as the
trend-alignment gate: this factor is already computed causally at
signal-generation time, so filtering on it introduces nothing new.

REGIME-DIRECTION GATE (F6b I2 follow-up, pre-registered 2026-07-05):
campaign.direction_regime_breakdown() found BTC's "bull regime is worst"
finding is actually a clean, consistent split -- bull+short is always the
worst cell, bear+short always the best -- across both venues and both
CAMPAIGN_CONFIGS. trend_alignment_only already exploits this INDIRECTLY
via a continuous sma_trend_bias_alignment score threshold; this gate
operationalizes the SAME finding DIRECTLY: veto a SHORT signal outright
whenever it fires during a classified bull regime, LONG signals are never
touched. Hypothesis (pre-registered BEFORE running against real data):
this more surgical, direct veto could clear BTC's promotion threshold
where the indirect proxy gate (trend_alignment_only, best BTC/Bybit
result so far: PF net 1.228, 6/10 windows) fell short of >=7/10 -- but
this is a hypothesis to test, not an assumed win; report the real number
either way, same discipline as every other gate here.

Critically, regime classification for THIS gate can NOT reuse campaign.
monthly_drift()/classify_regime() as-is -- that classifier deliberately
uses each FULL calendar month's REALIZED drift for a post-hoc breakdown
(campaign.py's own module docstring: "non-causal freedom... assumes of
its caller-supplied regime_of()"), which is fine for a retrospective
report but would be genuine lookahead bias if used as a LIVE gate (a
trade taken on the 3rd of the month would "know" whether the rest of
that month turns out bullish). trailing_drift()/_regime_by_signal_index()
below reuse the exact same classify_regime() thresholds (+/-5%) for
comparability, but compute drift over a TRAILING lookback window ending
at (and using only candles up to) each signal's own ts -- causal by
construction, same guarantee sma_trend_bias_alignment/daily_bias_
alignment already provide.

LTF FAKEOUT OVERRIDE (F6b I2 follow-up v2, pre-registered 5 Juli 2026,
founder's own 5-year trading experience -- run against real data 5 Juli
2026, result: LOST to no override in 3/4 series, see "LTF FAKEOUT
OVERRIDE v2" below and docs/fib-gann-validation-brief.md Section 33 for
the redesign this motivated): veto_short_bull's single 30-day
trailing-drift regime read can't tell a
genuine major-trend bull apart from a bullish blip inside a larger bear
trend (a relief rally that later fails) -- it vetoes SHORT in both cases
alike. The founder's hypothesis: the second case is exactly where a SHORT
entry is BEST, not worst -- fading a failed rally (a fakeout) inside a
larger downtrend. That distinction needs a finer, lower-timeframe read
than the 30-day macro drift can provide.

15m OHLCV for all 4 production series already exists in Neon (F0e P2's
--backfill-15m-since-days 1100, originally ingested for the unrelated
OI-fuel feature, never before consumed by any strategy/backtest code) --
verified here (5 Juli 2026, real HTTP-SQL queries against production, not
assumed from the backfill log alone): zero internal gaps and zero
null/high<low/zero-volume/flat-candle rows across all 4 series, full
2023-06-30..now coverage. Safe to use.

micro_structure_event()/micro_structure_event_by_signal_index() below
reuse market_structure.detect_structure_event() (already built for the
entry-timeframe structure_alignment score, docstring already anticipates
this exact case: "a fresh reversal INTO the trade's direction is the
textbook trigger for a new-trend entry") against a BOUNDED trailing
window of 15m candles ending at (and using only candles up to) each
signal's own ts -- same causal-by-construction guarantee as
trailing_drift(), never IncrementalSwingWalk's growing-prefix approach
since "freshness" (a recent reversal, not a stale one) is the whole point
here, not just performance.

GateConfig.use_ltf_fakeout_override (only meaningful together with
use_regime_direction_gate and/or use_long_bear_veto below): a signal that
would otherwise be vetoed for firing against its own direction's "wrong"
regime is let through anyway if the 15m series shows a CHoCH (NOT a BOS
-- a CHoCH is specifically the "potential reversal just starting" read
per market_structure.py's own docstring, which is the fakeout-failing
moment the founder described, whereas a BOS presupposes the opposite
trend already established at 15m and is a different, not-yet-tested
question) whose break_direction AGREES with the candidate's own direction
(BEARISH for a vetoed SHORT, BULLISH for a vetoed LONG) within LTF_
LOOKBACK_CANDLES of the signal.

VETO_LONG_BEAR (F6b I2 follow-up v3, pre-registered 5 Juli 2026 -- run
against real data 5 Juli 2026, result: made pooled PF net WORSE than
no_gate in ALL 4 series, not just weak as the prior below anticipated,
see docs/fib-gann-validation-brief.md Section 33): symmetric mechanism
to veto_short_bull -- veto
LONG signals firing in a causally-classified "bear" regime, same
trailing_drift()/regime_by_signal_index() machinery, no new regime
classifier. Evidence for this is WEAKER than short_bull's own (flagged,
not overstated): Section 30's formal direction x regime breakdown found
BTC long_bear mediocre-to-breakeven (PF 0.69-0.99 across venue/config),
not catastrophic like short_bull's 0.33-0.59 cell, and ETH long_bear was
similarly mixed (0.69-1.08) -- the module's own original veto_short_bull
docstring explicitly deferred this ("no long_bear veto exists yet...no
evidence... jangan menambah tebakan yg belum diuji"). Tested anyway now,
same "let evidence decide" discipline as every other gate here -- a
weaker prior is a reason to report the real number honestly, not a
reason to skip the experiment. GateConfig.use_long_bear_veto (new field)
+ GATE_CONFIGS entries veto_long_bear/veto_long_bear_ltf_override.

LTF FAKEOUT OVERRIDE v2 (pre-registered 5 Juli 2026, NOT yet run against
real data): v1 above lost to no override in 3/4 series -- the added-back
signals (a fresh same-direction 15m CHoCH, ~2-3% of the previously
vetoed population in every series) were on average WORSE, not better,
than what stayed vetoed. Root-cause hypothesis: a single 30-day regime
read can't distinguish two very different situations that both look like
"bull regime + a same-direction local 15m CHoCH" --
  (a) a genuine, sustained bull trend having an ORDINARY pullback (the
      15m CHoCH here is just noise/consolidation inside a real uptrend --
      shorting it is exactly the bad counter-trend trade veto_short_bull
      exists to block), vs.
  (b) an actual fakeout: the 30-day window barely tipped "bull" but the
      REAL, larger trend is still bearish or undirected (the 15m CHoCH
      here is the fake rally failing -- the founder's described case).
v1 couldn't tell these apart because it never checked anything beyond
the SAME 30-day window that triggered the veto in the first place. v2's
fix: GateConfig.require_major_regime_conflict (new) adds a SECOND,
LONGER regime read (major_regime_lookback_days, default MAJOR_REGIME_
LOOKBACK_DAYS=90 days, same trailing_drift()/regime_by_signal_index()
machinery, same regime_threshold, no new classifier) -- the CHoCH
override is only trusted when this major read DISAGREES with the local
30-day one (major regime is NOT "bull" for a signal veto_short_bull
would drop, NOT "bear" for one veto_long_bear would drop). An unknown
major regime (too early in the series for 90 days of history) can't
confirm a conflict, so the signal stays vetoed -- same can't-decide
fallback precedent as every other gate here. This directly restores the
"major trend vs local blip" distinction the founder's original story
described, which v1's single-timeframe regime check had dropped.
GATE_CONFIGS entries veto_short_bull_ltf_override_major_conflict/
veto_long_bear_ltf_override_major_conflict. "Major regime is NOT bull"
(i.e. bear OR range) is the deliberately LOOSER reading of "conflict" --
whether it should require strictly "bear" instead is left open, a
natural sensitivity-grid follow-up once this is measured at all.

Open questions deliberately NOT resolved by this initial pass (flagged,
not assumed): LTF_LOOKBACK_CANDLES=3 days is an initial, untested number
(same "initial numbers are free, evidence decides" convention as every
other new constant in this module) -- a sensitivity grid is a natural
follow-up, same discipline as veto_short_bull's own unresolved threshold/
window follow-up. Whether a same-direction BOS (not just CHoCH) should
also count is left open rather than guessed.

SENSITIVITY GRID (pre-registered, NOT yet run against real data): the
regime classifier's own 30-day lookback / +-5% threshold were borrowed
from campaign.classify_regime() purely for comparability with its
existing post-hoc breakdown -- REGIME-DIRECTION GATE above already flags
these were never independently validated as a live-gate classifier's own
parameters. GateConfig.regime_lookback_days/regime_threshold (new,
default to the borrowed 30-day/5% so every existing GATE_CONFIGS entry's
behavior is unchanged) + build_sensitivity_gate_configs() below run the
grid this follow-up asks for: lookback in {14, 30, 60} days x symmetric
threshold in {3%, 5%, 7%}, 9 combinations, for either mechanism
("veto_short_bull" or "veto_long_bear"). Kept out of GATE_CONFIGS itself
(see build_sensitivity_gate_configs()'s own docstring) -- generated on
demand instead, same apply_gates()/run_gated_series_batch() machinery.

SIZING MULTIPLIER (F6b I1(a)): a fundamentally different mechanism from
the three gates above -- instead of dropping signals, every kept signal is
RESIZED by a continuous multiplier derived from the same per-window
fitted confidence model the confidence gate uses (never a hard veto, per
the gate-vs-score standing principle in the F6b module docstring this
file's own header references). See size_multiplier()/run_sizing_series()
below and metrics.weighted_profit_factor() for how "PF tertimbang-size"
is computed net of fees/funding (SimulatedTrade.net_return_pct is already
both).

Reuses fit_weights.build_labeled_signals()/split_by_window() to fit the
confidence gate (full-hindsight-resolved outcomes for TRAIN, the same
convention fit_weights.py itself already uses for fitting purposes --
resolving whether a January trade eventually hit TP/SL using candles from
weeks later isn't lookahead into the DECISION itself, since every
feature going into the model is still computed strictly causally at
signal time; it only affects how many labels survive as non-censored).

PF/promotion measurement is a DIFFERENT concern and does NOT reuse those
hindsight-resolved trades directly -- once a window's surviving (post-
gate) signals are known, they are RE-simulated against candles restricted
to `< window.test_end` (campaign.py's own run_series_campaign() approach,
walk-forward-strict, no hindsight), so the PF-net/promoted numbers this
module reports are directly comparable to campaign.py's own Fase 6
figures. Mixing the two conventions in one PF number would have made
this module's "no_gate" baseline silently diverge from Fase 6's own
baseline for identical data -- caught by a sanity check before the real
4-series run (same "verify with real data before the expensive run"
discipline every prior phase has followed), not assumed correct from
synthetic tests alone.
"""

import bisect
import dataclasses
import datetime
import os
import statistics
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.dirname(__file__))

import campaign  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402
import fit_weights as fw  # noqa: E402
import market_structure as ms  # noqa: E402
import metrics  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

# Same "monthly" cadence as campaign.py's own calendar-month drift, but
# expressed as a trailing day-count so it can be computed causally at any
# signal's own ts rather than only at calendar-month boundaries.
REGIME_LOOKBACK_DAYS = 30

# LTF fakeout-override lookback (module docstring, "LTF FAKEOUT OVERRIDE")
# -- a bounded TRAILING window of 15m candles, not the whole series: a
# reversal from a year ago isn't "fresh" evidence of a fakeout happening
# now. 3 days * 96 fifteen-minute candles/day -- an initial, untested
# number (module docstring's own "open questions" section), not yet
# validated independently via a sensitivity grid.
LTF_LOOKBACK_CANDLES = 3 * 96

# Major-regime lookback for the v2 override redesign (module docstring,
# "LTF FAKEOUT OVERRIDE v2") -- deliberately much longer than REGIME_
# LOOKBACK_DAYS (30): the whole point is a coarser, slower-moving read
# that a genuine sustained trend satisfies but a mere 30-day blip inside a
# larger conflicting trend does not. 90 days -- an initial, untested
# number (same "initial numbers are free" convention as every other new
# constant here), not yet validated independently.
MAJOR_REGIME_LOOKBACK_DAYS = 90


@dataclasses.dataclass(frozen=True)
class GateConfig:
    name: str
    use_confidence_gate: bool = False
    confidence_percentile: float = 50.0  # keep signals with predicted P(TP) >= this percentile of TRAIN's own predictions
    use_trend_alignment_gate: bool = False
    trend_alignment_threshold: float = 0.5  # keep signals with sma_trend_bias_alignment strictly above this
    use_daily_bias_gate: bool = False
    daily_bias_threshold: float = 0.5  # keep signals with daily_bias_alignment (F6b I1(b), literal) strictly above this
    use_regime_direction_gate: bool = False  # F6b I2 follow-up: veto SHORT signals fired during a causally-classified bull regime
    use_long_bear_veto: bool = False  # F6b I2 follow-up v3: veto LONG signals fired during a causally-classified bear regime -- symmetric mechanism, WEAKER evidence than short_bull (module docstring, "VETO_LONG_BEAR"), tested anyway
    use_ltf_fakeout_override: bool = False  # F6b I2 follow-up v2: let a fresh, direction-agreeing 15m CHoCH un-veto a signal that use_regime_direction_gate/use_long_bear_veto would otherwise drop -- only meaningful together with at least one of those
    regime_lookback_days: int = REGIME_LOOKBACK_DAYS  # F6b I2 sensitivity follow-up ("SENSITIVITY GRID" below): trailing_drift()'s own window, only meaningful together with use_regime_direction_gate/use_long_bear_veto
    regime_threshold: float = campaign.BULL_DRIFT_THRESHOLD  # symmetric +/- drift threshold -- bull regime is drift > this, bear is drift < -this; defaults to campaign's own 5% for comparability, overridable by the sensitivity grid
    require_major_regime_conflict: bool = False  # F6b I2 follow-up v2 redesign ("LTF FAKEOUT OVERRIDE v2"): only trust the LTF CHoCH override when a longer-lookback major regime disagrees with the local regime that triggered the veto -- only meaningful together with use_ltf_fakeout_override
    major_regime_lookback_days: int = MAJOR_REGIME_LOOKBACK_DAYS  # trailing_drift() window for the "major" regime read above, only meaningful together with require_major_regime_conflict


# Neither gate is assumed to help going in -- all run through the same
# campaign so the real numbers decide (module docstring). daily_bias_only
# is F6b I1(b)'s literal, pre-registered variant -- reported alongside
# (not instead of) trend_alignment_only, which already answered the SMA
# proxy question; both are kept so the comparison itself is visible in
# the same report ("laporkan juga yang kalah"). veto_short_bull is the I2
# follow-up (module docstring) -- reported alongside, not instead of, the
# indirect trend_alignment_only proxy it's compared against.
GATE_CONFIGS = (
    GateConfig(name="no_gate"),
    GateConfig(name="confidence_only", use_confidence_gate=True),
    GateConfig(name="trend_alignment_only", use_trend_alignment_gate=True),
    GateConfig(name="daily_bias_only", use_daily_bias_gate=True),
    GateConfig(name="both_gates", use_confidence_gate=True, use_trend_alignment_gate=True),
    GateConfig(name="veto_short_bull", use_regime_direction_gate=True),
    # F6b I2 follow-up v2 (module docstring, "LTF FAKEOUT OVERRIDE") --
    # requires candles_15m (run_gated_series(_batch)'s new optional param);
    # reported alongside, not instead of, veto_short_bull, same "let the
    # number decide" discipline as every other gate in this tuple.
    GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True),
    # F6b I2 follow-up v3 (module docstring, "VETO_LONG_BEAR") -- weaker
    # prior than veto_short_bull (Section 30: long_bear mediocre, not
    # catastrophic), tested anyway; reported alongside every other gate
    # here, not assumed to win.
    GateConfig(name="veto_long_bear", use_long_bear_veto=True),
    GateConfig(name="veto_long_bear_ltf_override", use_long_bear_veto=True, use_ltf_fakeout_override=True),
    # F6b I2 follow-up v2 REDESIGN (module docstring, "LTF FAKEOUT
    # OVERRIDE v2") -- pre-registered 5 Juli 2026, NOT yet run against
    # real data. v1 (plain veto_short_bull_ltf_override above) LOST to no
    # override in 3/4 series (docs/fib-gann-validation-brief.md Section
    # 33): a same-direction 15m CHoCH alone can't distinguish an ordinary
    # pullback inside a genuine sustained trend from an actual fakeout
    # inside a conflicting LARGER trend. require_major_regime_conflict
    # adds that missing check -- only trust the CHoCH when a longer
    # (90-day) regime read disagrees with the local (30-day) one that
    # triggered the veto.
    GateConfig(
        name="veto_short_bull_ltf_override_major_conflict",
        use_regime_direction_gate=True,
        use_ltf_fakeout_override=True,
        require_major_regime_conflict=True,
    ),
    GateConfig(
        name="veto_long_bear_ltf_override_major_conflict",
        use_long_bear_veto=True,
        use_ltf_fakeout_override=True,
        require_major_regime_conflict=True,
    ),
)


# --- SENSITIVITY GRID (F6b I2 follow-up, pre-registered, NOT yet run
# against real data): veto_short_bull/veto_long_bear both borrow
# trailing_drift()'s 30-day lookback and campaign's own +/-5% threshold
# purely for comparability with campaign.py's post-hoc breakdown -- module
# docstring's "REGIME-DIRECTION GATE" section already flags these were
# NEVER independently validated/tuned as a live-gate classifier in their
# own right. This grid tests that directly: does the gate's real PF/
# window-pass-rate actually depend on these two borrowed numbers, or are
# they incidental? Kept OUT of GATE_CONFIGS itself (a 3x3 grid per
# mechanism would blow up that tuple's "one row per named, reported
# variant" contract, and every existing test asserting GATE_CONFIGS'
# exact name set would need updating for numbers nobody has evidence for
# yet) -- build_sensitivity_gate_configs() generates them on demand,
# reusing the exact same GateConfig/apply_gates/run_gated_series_batch
# machinery, so a grid run is just as walk-forward-strict and just as
# comparable as every other gate here. ---

# Both grids are the exact combination named in docs/sonnet5-
# implementation-roadmap.md's own unresolved F6b I2 follow-up: lookback in
# {14, 30, 60} days x symmetric threshold in {3%, 5%, 7%} -- 9 combinations
# per mechanism, none of them assumed better than the borrowed 30-day/5%
# default going in.
SENSITIVITY_LOOKBACK_DAYS_GRID = (14, 30, 60)
SENSITIVITY_THRESHOLD_GRID = (0.03, 0.05, 0.07)


def build_sensitivity_gate_configs(
    mechanism: str = "veto_short_bull",
    lookback_days_grid=SENSITIVITY_LOOKBACK_DAYS_GRID,
    threshold_grid=SENSITIVITY_THRESHOLD_GRID,
) -> tuple[GateConfig, ...]:
    """One GateConfig per (lookback_days, threshold) combination for the
    given mechanism ("veto_short_bull" or "veto_long_bear") -- name encodes
    both parameters (e.g. "veto_short_bull_lb14_th3") so a grid run's
    output table is self-describing without a separate lookup. Every
    combination uses the SAME mechanism flag (use_regime_direction_gate for
    "veto_short_bull", use_long_bear_veto for "veto_long_bear") -- this
    grid is about the regime CLASSIFIER'S OWN parameters, not about
    comparing the two mechanisms against each other (GATE_CONFIGS already
    reports both mechanisms at the borrowed default)."""
    if mechanism not in ("veto_short_bull", "veto_long_bear"):
        raise ValueError(f"mechanism must be 'veto_short_bull' or 'veto_long_bear', got {mechanism!r}")
    mechanism_kwargs = {"use_regime_direction_gate": True} if mechanism == "veto_short_bull" else {"use_long_bear_veto": True}
    configs = []
    for lookback_days in lookback_days_grid:
        for threshold in threshold_grid:
            threshold_pct = round(threshold * 100)
            configs.append(
                GateConfig(
                    name=f"{mechanism}_lb{lookback_days}_th{threshold_pct}",
                    regime_lookback_days=lookback_days,
                    regime_threshold=threshold,
                    **mechanism_kwargs,
                )
            )
    return tuple(configs)


def trailing_drift(candle_ts: list[datetime.datetime], candles: list[fgt.Candle], as_of_ts: datetime.datetime, lookback_days: int = REGIME_LOOKBACK_DAYS) -> float | None:
    """Causal regime proxy for GATING -- see module docstring ("REGIME-
    DIRECTION GATE") for why this can't just reuse campaign.monthly_drift().
    Realized price drift over the trailing `lookback_days` window ending at
    (and including) as_of_ts, using ONLY candles with ts <= as_of_ts.
    `candle_ts` is `[c.ts for c in candles]` -- passed in rather than
    recomputed so callers classifying many signals against the same series
    only build it once (bisect needs a plain sorted list, not Candle
    objects). None if there isn't at least `lookback_days` of history
    before as_of_ts yet (too early in the series to classify -- caller
    treats this as "unknown", never vetoed, same fallback precedent as
    every other gate's can't-decide case in this module)."""
    window_start = as_of_ts - datetime.timedelta(days=lookback_days)
    end_idx = bisect.bisect_right(candle_ts, as_of_ts) - 1
    if end_idx < 0:
        return None
    start_idx = bisect.bisect_left(candle_ts, window_start)
    if start_idx > end_idx or candle_ts[start_idx] > window_start:
        return None  # not enough trailing history yet
    start_candle, end_candle = candles[start_idx], candles[end_idx]
    if start_candle.open == 0:
        return None
    return (end_candle.close - start_candle.open) / start_candle.open


def regime_by_signal_index(
    signals: list[sr.Signal],
    candles: list[fgt.Candle],
    lookback_days: int = REGIME_LOOKBACK_DAYS,
    bull_threshold: float = campaign.BULL_DRIFT_THRESHOLD,
    bear_threshold: float = campaign.BEAR_DRIFT_THRESHOLD,
) -> dict[int, str]:
    """signal.index -> "bull"/"bear"/"range" (campaign.classify_regime(),
    defaulting to ITS OWN thresholds for comparability with campaign.py's
    post-hoc breakdown, but overridable -- F6b I2's own unresolved
    "sensitivity test threshold ±5%/window 30-hari itu sendiri belum
    divalidasi independen" follow-up, GateConfig.regime_lookback_days/
    regime_threshold below wire these through), computed causally per
    trailing_drift() above. Signals too early in the series to have
    `lookback_days` of trailing history are simply absent from the result
    (caller/gate treats a missing key as "unknown", never vetoed)."""
    candle_ts = [c.ts for c in candles]
    result = {}
    for signal in signals:
        drift = trailing_drift(candle_ts, candles, signal.ts, lookback_days)
        if drift is not None:
            result[signal.index] = campaign.classify_regime(drift, bull_threshold, bear_threshold)
    return result


def micro_structure_event(
    candles_15m_ts: list[datetime.datetime],
    candles_15m: list[fgt.Candle],
    as_of_ts: datetime.datetime,
    lookback_candles: int = LTF_LOOKBACK_CANDLES,
) -> ms.StructureEvent | None:
    """Causal LTF (15m) micro-structure read for GATING -- module docstring
    ("LTF FAKEOUT OVERRIDE"). Uses ONLY 15m candles with ts <= as_of_ts
    (bisect, same technique as trailing_drift() above), and only the most
    recent `lookback_candles` of those -- a BOUNDED trailing window, not
    the whole series, since a stale reversal from a year ago isn't evidence
    of a fakeout happening right now. `candles_15m_ts` is
    `[c.ts for c in candles_15m]`, passed in rather than recomputed so
    callers classifying many signals against the same 15m series only
    build it once.

    None if there aren't enough 15m candles before as_of_ts yet to run
    detect_swings() at all (too early in the series, or as_of_ts before the
    first 15m candle) -- caller treats this the same as "no event", never
    an override (same can't-decide-so-pass-through fallback precedent as
    every other gate in this module)."""
    end_idx = bisect.bisect_right(candles_15m_ts, as_of_ts) - 1
    if end_idx < 0:
        return None
    start_idx = max(0, end_idx - lookback_candles + 1)
    window = candles_15m[start_idx : end_idx + 1]
    if len(window) < fgt.DEFAULT_ATR_PERIOD + 2:
        return None
    swings = fgt.detect_swings(window)
    return ms.detect_structure_event(swings, reference_price=window[-1].close)


def micro_structure_event_by_signal_index(
    signals: list[sr.Signal], candles_15m: list[fgt.Candle], lookback_candles: int = LTF_LOOKBACK_CANDLES
) -> dict[int, ms.StructureEvent | None]:
    """signal.index -> micro_structure_event() (or None), for every signal
    -- always present (unlike regime_by_signal_index(), which omits
    too-early signals entirely) since the gate only ever reads this via
    .get(index), which already defaults missing keys to None; storing an
    explicit None costs nothing and keeps this function's contract
    "one entry per signal" rather than a partial mapping."""
    candles_15m_ts = [c.ts for c in candles_15m]
    return {signal.index: micro_structure_event(candles_15m_ts, candles_15m, signal.ts, lookback_candles) for signal in signals}


def _fit_confidence_model(train: list[fw.LabeledSignal]) -> tuple[LogisticRegression, np.ndarray] | None:
    """Same fit fit_weights._fit_binary() performs (same solver/l1_ratio/
    guards), but returns the model itself (plus its train feature matrix,
    needed for the percentile cutoff) instead of a summarized SchemeResult
    -- this experiment needs per-signal predictions, not aggregate
    AUC/Brier. Returns None when the guards fit_weights.py already
    documents (too few samples, single outcome class) mean no fit is
    possible; callers pass every signal through unfiltered in that case."""
    train_pairs = [(ls, fw._binary_label(ls.trade.label.outcome)) for ls in train]  # noqa: SLF001
    train_pairs = [(ls, y) for ls, y in train_pairs if y is not None]
    if len(train_pairs) < fw.MIN_TRAIN_SAMPLES:
        return None
    y_train = [y for _, y in train_pairs]
    if len(set(y_train)) < 2:
        return None
    x_train = np.array([fw._feature_vector(ls.signal, fw.ALL_CANDIDATE_FEATURE_NAMES) for ls, _ in train_pairs])  # noqa: SLF001
    model = LogisticRegression(solver="saga", l1_ratio=fw.DEFAULT_L1_RATIO, max_iter=1000)
    model.fit(x_train, y_train)
    if 1 not in list(model.classes_):
        return None  # TAKE_PROFIT never seen in training -- nothing to rank confidence against
    return model, x_train


def _predict_proba(model: LogisticRegression, signal: sr.Signal) -> float:
    x = np.array([fw._feature_vector(signal, fw.ALL_CANDIDATE_FEATURE_NAMES)])  # noqa: SLF001
    return float(model.predict_proba(x)[0][list(model.classes_).index(1)])


def apply_gates(
    train: list[fw.LabeledSignal],
    test: list[fw.LabeledSignal],
    gate_config: GateConfig,
    regime_by_index: dict[int, str] | None = None,
    ltf_events_by_index: dict[int, ms.StructureEvent | None] | None = None,
    major_regime_by_index: dict[int, str] | None = None,
) -> list[fw.LabeledSignal]:
    """regime_by_index (regime_by_signal_index()'s output) is only needed
    when gate_config.use_regime_direction_gate and/or use_long_bear_veto is
    True -- every other gate ignores it, same optional-until-needed shape
    as every other gate-specific input this function already takes (e.g.
    train is unused unless use_confidence_gate). ltf_events_by_index
    (micro_structure_event_by_signal_index()'s output) is only needed on
    top of that when gate_config.use_ltf_fakeout_override is ALSO True.
    major_regime_by_index (regime_by_signal_index()'s output computed at a
    LONGER lookback, module docstring's "LTF FAKEOUT OVERRIDE v2") is only
    needed on top of THAT when gate_config.require_major_regime_conflict
    is ALSO True."""
    candidates = list(test)

    if gate_config.use_confidence_gate:
        fit = _fit_confidence_model(train)
        if fit is not None:
            model, x_train = fit
            train_probs = model.predict_proba(x_train)[:, list(model.classes_).index(1)]
            cutoff = float(np.percentile(train_probs, gate_config.confidence_percentile))
            candidates = [ls for ls in candidates if _predict_proba(model, ls.signal) >= cutoff]
        # else: train data can't support a fit this window -- pass everything through (module docstring)

    if gate_config.use_trend_alignment_gate:
        candidates = [ls for ls in candidates if ls.signal.sma_trend_bias_alignment > gate_config.trend_alignment_threshold]

    if gate_config.use_daily_bias_gate:
        candidates = [ls for ls in candidates if ls.signal.daily_bias_alignment > gate_config.daily_bias_threshold]

    if gate_config.use_regime_direction_gate or gate_config.use_long_bear_veto:
        regimes = regime_by_index or {}
        events = ltf_events_by_index or {}
        major_regimes = major_regime_by_index or {}

        def _vetoed_by_regime_direction(ls: fw.LabeledSignal) -> bool:
            regime = regimes.get(ls.signal.index)
            # A signal is either SHORT or LONG, never both, so at most one
            # of these two can be true for any given signal -- no conflict
            # in picking `wanted_break`/`major_conflicts` below from
            # whichever one fired.
            wants_veto_short_bull = (
                gate_config.use_regime_direction_gate and ls.signal.direction is fgt.TradeDirection.SHORT and regime == "bull"
            )
            wants_veto_long_bear = gate_config.use_long_bear_veto and ls.signal.direction is fgt.TradeDirection.LONG and regime == "bear"
            wants_veto = wants_veto_short_bull or wants_veto_long_bear
            if not wants_veto or not gate_config.use_ltf_fakeout_override:
                return wants_veto

            # LTF FAKEOUT OVERRIDE v2 (module docstring, "MAJOR/LOCAL
            # REGIME CONFLICT"): Section 33's real-data finding was that a
            # plain fresh CHoCH override (v1) LOSES to no override in 3/4
            # series -- the local 30-day regime read alone can't tell a
            # genuine sustained trend's ordinary pullback (a same-direction
            # 15m CHoCH here is just noise/consolidation, NOT the fakeout
            # the founder described) from an actual fakeout inside a
            # conflicting LARGER trend. require_major_regime_conflict adds
            # exactly the missing piece: only trust the 15m CHoCH when a
            # LONGER-lookback regime read disagrees with the local one
            # that triggered the veto in the first place (major regime is
            # NOT "bull" for a vetoed SHORT, NOT "bear" for a vetoed LONG)
            # -- an unknown major regime (too early in the series) can't
            # confirm a conflict, so it stays vetoed, same can't-decide
            # fallback precedent as every other gate here.
            if gate_config.require_major_regime_conflict:
                major_regime = major_regimes.get(ls.signal.index)
                major_conflicts = (major_regime is not None) and (
                    (major_regime != "bull") if wants_veto_short_bull else (major_regime != "bear")
                )
                if not major_conflicts:
                    return wants_veto  # local regime alone, unconfirmed by a major/local conflict -- stays vetoed

            # LTF FAKEOUT OVERRIDE (module docstring): a fresh 15m CHoCH
            # breaking in the SAME direction as this candidate's own
            # direction (BEARISH for a vetoed SHORT, BULLISH for a vetoed
            # LONG) un-vetoes it -- treated as the fakeout failing, not as
            # evidence the regime read itself was wrong.
            wanted_break = ms.StructureBreakDirection.BEARISH if wants_veto_short_bull else ms.StructureBreakDirection.BULLISH
            event = events.get(ls.signal.index)
            fakeout_confirmed = event is not None and event.event_type is ms.StructureEventType.CHOCH and event.break_direction is wanted_break
            return not fakeout_confirmed

        candidates = [ls for ls in candidates if not _vetoed_by_regime_direction(ls)]

    return candidates


@dataclasses.dataclass(frozen=True)
class GatedSeriesResult:
    series: str
    gate_name: str
    total_signals: int  # before any gate -- same across every gate_config for a given series
    total_kept: int  # after gating, summed across windows
    total_windows: int
    windows_passing_pf: int
    promoted: bool
    pooled_pf_net: float | None


def _prepare_series_data(
    candles,
    campaign_config: campaign.CampaignConfig,
    derivatives_records,
    funding_events,
    max_holding_bars: int,
):
    """signals/labeled/windows depend only on (candles, campaign_config,
    derivatives_records, funding_events, max_holding_bars) -- NOT on which
    gate is being measured. Extracted so run_gated_series_batch() below can
    compute this ONCE per series and reuse it across every gate, instead of
    re-running generate_signals()'s O(n) walk (still a real cost at actual
    production series size, ~26k candles/3 years) once per gate for
    identical output every time."""
    signals = sr.generate_signals(
        candles,
        min_rr_threshold=campaign_config.min_rr_threshold,
        max_rr_threshold=campaign_config.max_rr_threshold,
        sl_atr_buffer_multiplier=campaign_config.sl_atr_buffer_multiplier,
        sl_method=campaign_config.sl_method,
        derivatives_records=derivatives_records,
    )
    labeled = fw.build_labeled_signals(signals, candles, funding_events or [], max_holding_bars)
    windows = campaign.exp.generate_windows_by_calendar(
        start=candles[0].ts,
        end=candles[-1].ts,
        train_months=campaign.exp.TRAIN_MONTHS,
        test_months=campaign.exp.TEST_MONTHS,
        embargo_days=campaign.exp.EMBARGO_DAYS,
        step_months=campaign.exp.STEP_MONTHS,
        mode=campaign.exp.WINDOW_MODE,
    )
    return signals, labeled, windows


def _run_gated_series_prepared(
    series_name: str,
    candles,
    gate_config: GateConfig,
    signals,
    labeled,
    windows,
    funding_events,
    max_holding_bars: int,
    candles_15m=None,
) -> GatedSeriesResult:
    """Shared body of run_gated_series()/run_gated_series_batch() -- takes
    _prepare_series_data()'s output directly rather than recomputing it.
    candles_15m (module docstring, "LTF FAKEOUT OVERRIDE") is only required
    when gate_config.use_ltf_fakeout_override is True -- fails loud (not a
    silent no-op) if that gate is requested without it, since a missing
    override input silently behaving like "never fires" would misreport
    veto_short_bull_ltf_override as identical to veto_short_bull instead of
    surfacing the caller's mistake."""
    if gate_config.use_ltf_fakeout_override and not candles_15m:
        raise ValueError(f"gate {gate_config.name!r} requires candles_15m but none were provided")

    # Computed once per series (not per window) -- trailing_drift() only
    # ever looks at candles <= a signal's own ts, so precomputing this
    # against the FULL candle list is still walk-forward-safe (no future
    # window's candles can affect an earlier signal's classification).
    # Same reasoning applies to micro_structure_event_by_signal_index():
    # its own lookback window is bounded and trailing, so precomputing
    # against the full 15m candle list can't leak a later window's data
    # into an earlier signal's classification either.
    needs_regime = gate_config.use_regime_direction_gate or gate_config.use_long_bear_veto
    regime_by_index = (
        regime_by_signal_index(
            signals,
            candles,
            lookback_days=gate_config.regime_lookback_days,
            bull_threshold=gate_config.regime_threshold,
            bear_threshold=-gate_config.regime_threshold,
        )
        if needs_regime
        else {}
    )
    ltf_events_by_index = micro_structure_event_by_signal_index(signals, candles_15m) if gate_config.use_ltf_fakeout_override else {}
    major_regime_by_index = (
        regime_by_signal_index(
            signals,
            candles,
            lookback_days=gate_config.major_regime_lookback_days,
            bull_threshold=gate_config.regime_threshold,
            bear_threshold=-gate_config.regime_threshold,
        )
        if gate_config.require_major_regime_conflict
        else {}
    )

    pooled_trades = []
    total_kept = 0
    windows_passing = 0
    for window in windows:
        train, test = fw.split_by_window(labeled, window)
        kept = apply_gates(
            train,
            test,
            gate_config,
            regime_by_index=regime_by_index,
            ltf_events_by_index=ltf_events_by_index,
            major_regime_by_index=major_regime_by_index,
        )
        total_kept += len(kept)

        # Gate SELECTION uses the hindsight-resolved labeled signals above
        # (fitting/filtering only reads each signal's own pre-computed
        # features, never its outcome) -- but the trade actually COUNTED
        # for PF/promotion is RE-simulated here against window-restricted
        # candles, matching campaign.py's own walk-forward-strict
        # convention exactly (module docstring).
        kept_signals = [ls.signal for ls in kept]
        window_candles = [c for c in candles if c.ts < window.test_end]
        trades = ts.simulate_trades(
            kept_signals, window_candles, funding_events or [], max_holding_bars, campaign.exp.FEE_ENTRY_FRACTION, campaign.exp.FEE_EXIT_FRACTION
        )
        non_censored = [t for t in trades if not t.label.censored]
        if non_censored:
            window_metrics = metrics.compute_metrics(trades)
            if window_metrics.profit_factor_net is not None and window_metrics.profit_factor_net > campaign.exp.PF_NET_THRESHOLD:
                windows_passing += 1
        pooled_trades.extend(trades)

    pooled_non_censored = [t for t in pooled_trades if not t.label.censored]
    pooled_metrics = metrics.compute_metrics(pooled_trades) if pooled_non_censored else None

    total_windows = len(windows)
    promoted = total_windows > 0 and (windows_passing / total_windows) >= campaign.PF_PASS_FRACTION

    return GatedSeriesResult(
        series=series_name,
        gate_name=gate_config.name,
        total_signals=len(signals),
        total_kept=total_kept,
        total_windows=total_windows,
        windows_passing_pf=windows_passing,
        promoted=promoted,
        pooled_pf_net=pooled_metrics.profit_factor_net if pooled_metrics else None,
    )


def run_gated_series(
    series_name: str,
    candles,
    gate_config: GateConfig,
    campaign_config: campaign.CampaignConfig = campaign.CAMPAIGN_CONFIGS[0],
    derivatives_records=None,
    funding_events=None,
    max_holding_bars: int = 20,
    candles_15m=None,
) -> GatedSeriesResult:
    """campaign_config (F6b I1, docs/sonnet5-implementation-roadmap.md):
    which R:R/SL config generates the underlying signals BEFORE any gate is
    applied -- defaults to campaign.CAMPAIGN_CONFIGS[0] (current production
    defaults, this module's original behavior, so every pre-existing call
    site/test is unaffected), but I1's own pre-registered A/B runs this on
    TOP of campaign.CAMPAIGN_CONFIGS[1] (F5's candidate) instead, per the
    roadmap's explicit "di atas config kandidat F5" framing -- reusing
    campaign.CampaignConfig rather than a parallel set of loose R:R/SL
    params. candles_15m: see _run_gated_series_prepared()'s own docstring
    -- only required for gate_config.use_ltf_fakeout_override.

    Single-gate convenience wrapper around _prepare_series_data()/_run_
    gated_series_prepared() -- comparing MULTIPLE gates for the same
    series should use run_gated_series_batch() instead, which shares the
    expensive signal-generation step across all of them."""
    signals, labeled, windows = _prepare_series_data(candles, campaign_config, derivatives_records, funding_events, max_holding_bars)
    return _run_gated_series_prepared(
        series_name, candles, gate_config, signals, labeled, windows, funding_events, max_holding_bars, candles_15m=candles_15m
    )


def run_gated_series_batch(
    series_name: str,
    candles,
    gate_configs,
    campaign_config: campaign.CampaignConfig = campaign.CAMPAIGN_CONFIGS[0],
    derivatives_records=None,
    funding_events=None,
    max_holding_bars: int = 20,
    candles_15m=None,
) -> list[GatedSeriesResult]:
    """Equivalent to [run_gated_series(series_name, candles, gc, ...) for gc
    in gate_configs], but generates signals ONCE and reuses them across
    every gate_configs entry -- the real motivating case (this module's own
    CLI entrypoint, comparing N gates for the same series): the first real
    6-gate x 4-series run against production's now ~26k-candle/3-year
    series ran past 90 minutes without completing, re-running generate_
    signals() from scratch for every single gate despite it producing
    IDENTICAL output each time for a fixed (candles, campaign_config,
    derivatives_records, funding_events, max_holding_bars) tuple."""
    signals, labeled, windows = _prepare_series_data(candles, campaign_config, derivatives_records, funding_events, max_holding_bars)
    return [
        _run_gated_series_prepared(
            series_name, candles, gate_config, signals, labeled, windows, funding_events, max_holding_bars, candles_15m=candles_15m
        )
        for gate_config in gate_configs
    ]


# --- F6b I1(a): sizing multiplier (module docstring) ---

# "dalam cap" -- confidence never vetoes a trade outright, only scales it
# within a bounded range; MIN_SIZE_MULTIPLIER=0.5/MAX=1.5 is a symmetric,
# undisputed starting band around the unscaled baseline of 1.0 (same
# "initial numbers are free, the fit/evidence decides whether it helps"
# convention as every other new constant in this harness -- not itself
# something Fase 3 fits).
MIN_SIZE_MULTIPLIER = 0.5
MAX_SIZE_MULTIPLIER = 1.5


def size_multiplier(confidence: float) -> float:
    """Linear map of a 0-1 confidence score to [MIN_SIZE_MULTIPLIER,
    MAX_SIZE_MULTIPLIER], clamped. confidence outside [0, 1] (shouldn't
    happen for a predict_proba output, but this is a pure function with no
    caller-trust assumption) is clamped first so the result never leaves
    the cap either."""
    clamped = max(0.0, min(1.0, confidence))
    return MIN_SIZE_MULTIPLIER + clamped * (MAX_SIZE_MULTIPLIER - MIN_SIZE_MULTIPLIER)


@dataclasses.dataclass(frozen=True)
class SizingConfig:
    name: str
    use_confidence_sizing: bool = False


# no_sizing (multiplier always 1.0) is the baseline every other variant is
# measured against -- same "let the number decide" discipline as
# GATE_CONFIGS' own no_gate entry.
SIZING_CONFIGS = (
    SizingConfig(name="no_sizing"),
    SizingConfig(name="confidence_sizing", use_confidence_sizing=True),
)


def _size_multipliers(train: list[fw.LabeledSignal], test: list[fw.LabeledSignal], sizing_config: SizingConfig) -> dict[int, float]:
    """signal.index -> multiplier for every signal in `test` -- keyed by
    index (not list position) since simulate_trades() can drop a signal
    entirely (the very last candle in the series has no forward data to
    label), and SimulatedTrade.signal_index is the stable join key back to
    whichever multiplier applies, regardless of any such drop."""
    if not sizing_config.use_confidence_sizing:
        return {ls.signal.index: 1.0 for ls in test}
    fit = _fit_confidence_model(train)
    if fit is None:
        return {ls.signal.index: 1.0 for ls in test}  # can't fit this window -- no scaling, same fallback precedent as the gate
    model, _ = fit
    return {ls.signal.index: size_multiplier(_predict_proba(model, ls.signal)) for ls in test}


@dataclasses.dataclass(frozen=True)
class SizingSeriesResult:
    series: str
    sizing_name: str
    total_signals: int
    total_windows: int
    pooled_pf_net: float | None  # unweighted (every trade at multiplier 1.0) -- directly comparable to campaign.py's own baseline
    pooled_weighted_pf_net: float | None  # size-weighted PF net, net of fees/funding (metrics.weighted_profit_factor)
    avg_multiplier: float | None  # funnel diagnostic: mean multiplier actually applied, across every non-censored trade
    min_multiplier: float | None
    max_multiplier: float | None


def run_sizing_series(
    series_name: str,
    candles,
    sizing_config: SizingConfig,
    campaign_config: campaign.CampaignConfig = campaign.CAMPAIGN_CONFIGS[0],
    derivatives_records=None,
    funding_events=None,
    max_holding_bars: int = 20,
) -> SizingSeriesResult:
    """campaign_config: see run_gated_series()'s own docstring -- same
    reasoning, same default, same I1 "on top of F5 candidate" override."""
    signals = sr.generate_signals(
        candles,
        min_rr_threshold=campaign_config.min_rr_threshold,
        max_rr_threshold=campaign_config.max_rr_threshold,
        sl_atr_buffer_multiplier=campaign_config.sl_atr_buffer_multiplier,
        sl_method=campaign_config.sl_method,
        derivatives_records=derivatives_records,
    )
    labeled = fw.build_labeled_signals(signals, candles, funding_events or [], max_holding_bars)
    windows = campaign.exp.generate_windows_by_calendar(
        start=candles[0].ts,
        end=candles[-1].ts,
        train_months=campaign.exp.TRAIN_MONTHS,
        test_months=campaign.exp.TEST_MONTHS,
        embargo_days=campaign.exp.EMBARGO_DAYS,
        step_months=campaign.exp.STEP_MONTHS,
        mode=campaign.exp.WINDOW_MODE,
    )

    pooled_trades: list[ts.SimulatedTrade] = []
    weighted_returns: list[tuple[float, float]] = []
    applied_multipliers: list[float] = []
    for window in windows:
        train, test = fw.split_by_window(labeled, window)
        multiplier_by_index = _size_multipliers(train, test, sizing_config)

        # Same walk-forward-strict re-simulation convention as apply_gates()
        # above (module docstring): sizing does not change WHICH signals
        # trade, only how much weight each gets, but PF is still measured
        # against window-restricted candles for direct comparability with
        # campaign.py/run_gated_series().
        test_signals = [ls.signal for ls in test]
        window_candles = [c for c in candles if c.ts < window.test_end]
        trades = ts.simulate_trades(
            test_signals, window_candles, funding_events or [], max_holding_bars, campaign.exp.FEE_ENTRY_FRACTION, campaign.exp.FEE_EXIT_FRACTION
        )
        for trade in trades:
            if not trade.label.censored:
                multiplier = multiplier_by_index[trade.signal_index]
                weighted_returns.append((multiplier, trade.net_return_pct))
                applied_multipliers.append(multiplier)
        pooled_trades.extend(trades)

    pooled_non_censored = [t for t in pooled_trades if not t.label.censored]
    pooled_metrics = metrics.compute_metrics(pooled_trades) if pooled_non_censored else None

    return SizingSeriesResult(
        series=series_name,
        sizing_name=sizing_config.name,
        total_signals=len(signals),
        total_windows=len(windows),
        pooled_pf_net=pooled_metrics.profit_factor_net if pooled_metrics else None,
        pooled_weighted_pf_net=metrics.weighted_profit_factor(weighted_returns) if weighted_returns else None,
        avg_multiplier=statistics.mean(applied_multipliers) if applied_multipliers else None,
        min_multiplier=min(applied_multipliers) if applied_multipliers else None,
        max_multiplier=max(applied_multipliers) if applied_multipliers else None,
    )


# --- CLI entrypoint (F6b I2 follow-up: veto_short_bull real 4-series run) ---
#
# Runs every GATE_CONFIGS entry against all 4 production series, on top of
# campaign.CAMPAIGN_CONFIGS[1] (F5's candidate: min_rr=2.0/max_rr=5.0/
# sl=1.0atr) -- matching I1's own established "di atas config kandidat F5"
# convention (docs/sonnet5-implementation-roadmap.md F6b), not production
# defaults, so results are directly comparable to I1's already-documented
# table. derivatives_records is intentionally left at its None default:
# veto_short_bull's mechanism (direction x causal-regime) never reads any
# derivatives factor, and per F6b's own "skor confidence tidak punya
# konsumen" finding, derivatives features don't influence which signals
# fire or their PF at all when the confidence/both_gates gates aren't in
# play for a given row -- this run reports every gate for comparability,
# but only no_gate/trend_alignment_only/daily_bias_only/veto_short_bull/
# veto_short_bull_ltf_override/veto_long_bear/veto_long_bear_ltf_override
# rows are unaffected by that omission either way (none of these read any
# derivatives factor, direction x causal-regime or LTF micro-structure
# only).
# 15m OHLCV coverage per series is ~105,600-105,603 rows over 1100 days
# (verified 5 Juli 2026 via real HTTP-SQL queries against production --
# zero internal gaps, zero null/high<low/zero-volume/flat-candle rows,
# module docstring's "LTF FAKEOUT OVERRIDE"). campaign.CANDLE_LOAD_LIMIT
# (100_000) is sized for the 1h series (~26k candles/3 years) and would
# silently drop the ~5,600 OLDEST 15m candles (data_loader.load_candles()
# orders DESC LIMIT then reverses) if reused here -- a separate, larger
# limit for the 15m load only.
LTF_TIMEFRAME = "15m"
LTF_CANDLE_LOAD_LIMIT = 120_000

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "docs", "validation-results", "gated_campaign.json"),
    )
    parser.add_argument(
        "--gates",
        default=None,
        help="comma-separated GATE_CONFIGS names to run (default: all) -- e.g. 'no_gate,trend_alignment_only,veto_short_bull' to skip the expensive per-window-refit gates (confidence_only/both_gates) when only comparing against the non-refit gates. Ignored if --sensitivity-grid is given.",
    )
    parser.add_argument(
        "--sensitivity-grid",
        default=None,
        choices=["veto_short_bull", "veto_long_bear"],
        help="run build_sensitivity_gate_configs() for this mechanism instead of --gates -- 9 (lookback_days x threshold) combinations, module docstring's 'SENSITIVITY GRID'. no_gate is always included alongside as the unaffected baseline.",
    )
    args = parser.parse_args()

    import data_loader  # deferred: see rr_sl_experiment.py's own comment for why

    if args.sensitivity_grid:
        gate_configs = (GateConfig(name="no_gate"),) + build_sensitivity_gate_configs(args.sensitivity_grid)
    elif args.gates:
        wanted = set(args.gates.split(","))
        gate_configs = tuple(c for c in GATE_CONFIGS if c.name in wanted)
    else:
        gate_configs = GATE_CONFIGS
    needs_ltf = any(c.use_ltf_fakeout_override for c in gate_configs)

    f5_candidate = campaign.CAMPAIGN_CONFIGS[1]
    all_results = []
    for venue, symbol, coin in campaign.SERIES:
        candles = data_loader.load_candles(venue, symbol, campaign.TIMEFRAME, limit=campaign.CANDLE_LOAD_LIMIT)
        if not candles:
            print(f"no candles for {venue}/{symbol} -- skipping")
            continue
        candles_15m = data_loader.load_candles(venue, symbol, LTF_TIMEFRAME, limit=LTF_CANDLE_LOAD_LIMIT) if needs_ltf else None
        if needs_ltf and not candles_15m:
            print(f"no 15m candles for {venue}/{symbol} -- skipping (needed by a requested gate)")
            continue
        series_name = f"{venue}_{coin}"
        print(f"{series_name}: {len(candles)} candles, {candles[0].ts} .. {candles[-1].ts}", flush=True)
        if needs_ltf:
            print(f"  + {len(candles_15m)} 15m candles, {candles_15m[0].ts} .. {candles_15m[-1].ts}", flush=True)
        # run_gated_series_batch(), not one run_gated_series() call per gate --
        # generate_signals() is the expensive part at real series size (~26k
        # candles/3 years) and produces IDENTICAL signals regardless of which
        # gate is being measured; the first real run of this loop called it
        # once per gate and ran past 90 minutes without finishing.
        for result in run_gated_series_batch(series_name, candles, gate_configs, campaign_config=f5_candidate, candles_15m=candles_15m):
            print(
                f"  {result.gate_name}: signals={result.total_signals} kept={result.total_kept} "
                f"promoted={result.promoted} windows_passing_pf={result.windows_passing_pf}/{result.total_windows} "
                f"pooled_pf_net={result.pooled_pf_net}",
                flush=True,
            )
            all_results.append(dataclasses.asdict(result))
            # Written after every (series, gate) combo, not just at the end --
            # a cancelled/timed-out run still leaves partial real results in
            # the uploaded artifact instead of nothing at all.
            with open(args.output, "w") as f:
                json.dump(all_results, f, indent=2)

    print(f"wrote {args.output}")
