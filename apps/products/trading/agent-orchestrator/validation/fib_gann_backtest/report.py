"""Design brief Section 6: report.py -- dumps a run_validation.
ValidationRunResult to docs/validation-results/ as JSON (machine-readable,
for programmatic comparison across runs) and Markdown (human-readable
summary) -- per the brief's explicit "dump ke docs/validation-results/
(JSON/markdown dulu, bukan tabel DB baru)", no new DB table this round.
"""

import dataclasses
import json
import os


def _window_result_to_dict(window_result) -> dict:
    w = window_result.window
    return {
        "window_id": w.window_id,
        "train_start": w.train_start.isoformat(),
        "train_end": w.train_end.isoformat(),
        "test_start": w.test_start.isoformat(),
        "test_end": w.test_end.isoformat(),
        "signal_count": window_result.signal_count,
        "trade_count": window_result.trade_count,
        # "metrics" is net-of-funding-AND-fees once fees are configured (see
        # run_validation.py's run_window()); "metrics_net_funding_only" is
        # the same trades with fees zeroed out, isolating the fee-only cost
        # -- together with metrics.profit_factor_gross this gives the
        # 3-way gross/net-funding/net-fees comparison docs/validation-deep-
        # dive-2026-07.md Section 6a (F5) asked every report to show.
        "metrics": dataclasses.asdict(window_result.metrics) if window_result.metrics is not None else None,
        "metrics_net_funding_only": (
            dataclasses.asdict(window_result.metrics_net_funding_only) if window_result.metrics_net_funding_only is not None else None
        ),
    }


def to_dict(result) -> dict:
    return {
        "total_windows": result.total_windows,
        "windows_passing_pf": result.windows_passing_pf,
        "pf_net_threshold": result.pf_net_threshold,
        "pf_pass_fraction": result.pf_pass_fraction,
        "promotion_pf_criterion_met": result.promotion_pf_criterion_met,
        "promotion_agreement_rate_criterion": "not computable yet -- trade_annotation has no signal_id linkage (see migration 0005)",
        "windows": [_window_result_to_dict(wr) for wr in result.windows],
    }


def _format_metric(value) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def to_markdown(result) -> str:
    lines = [
        "# fib_gann_backtest validation run",
        "",
        f"- Total windows: {result.total_windows}",
        f"- Windows passing PF net > {result.pf_net_threshold}: {result.windows_passing_pf}/{result.total_windows}",
        f"- Promotion PF criterion (>= {result.pf_pass_fraction:.1%} of windows): "
        f"**{'MET' if result.promotion_pf_criterion_met else 'NOT MET'}**",
        "- Promotion agreement-rate criterion: not computable yet (trade_annotation has no signal_id linkage)",
        "",
        "| window | test_start | test_end | signals | trades | PF gross | PF net-funding | PF net-fees | Sharpe net-fees | max DD net-fees |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for wr in result.windows:
        m = wr.metrics
        # metrics_net_funding_only is None when fees weren't configured at
        # all -- in that case "net" already IS "net-funding-only", so fall
        # back to `m` rather than printing a redundant None column.
        m_funding = wr.metrics_net_funding_only if wr.metrics_net_funding_only is not None else m
        lines.append(
            f"| {wr.window.window_id} | {wr.window.test_start.isoformat()} | {wr.window.test_end.isoformat()} | "
            f"{wr.signal_count} | {wr.trade_count} | "
            f"{_format_metric(m.profit_factor_gross if m else None)} | {_format_metric(m_funding.profit_factor_net if m_funding else None)} | "
            f"{_format_metric(m.profit_factor_net if m else None)} | "
            f"{_format_metric(m.sharpe_net if m else None)} | {_format_metric(m.max_drawdown_pct_net if m else None)} |"
        )
    return "\n".join(lines) + "\n"


def write_report(result, output_dir: str, run_id: str) -> tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f"{run_id}.json")
    md_path = os.path.join(output_dir, f"{run_id}.md")
    with open(json_path, "w") as f:
        json.dump(to_dict(result), f, indent=2)
    with open(md_path, "w") as f:
        f.write(to_markdown(result))
    return json_path, md_path
