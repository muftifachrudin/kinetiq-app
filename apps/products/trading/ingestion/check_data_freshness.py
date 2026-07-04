"""F0e P5 (docs/sonnet5-implementation-roadmap.md): reads the Neon HTTP-SQL
JSON response .github/workflows/data-freshness.yml's own `curl` step
produces and fails (exit 1) if ohlcv/funding_rate/the signal loop's own
heartbeat is missing or older than a given threshold. Kept as a standalone
script (not inline workflow YAML) so this staleness-decision logic is
unit-testable like everything else in this repo, rather than "verified
manually in CI" the way ingest.py's own DB-touching functions are.

Deliberately checks the SIGNAL LOOP's data_source_health heartbeat
(last_success_at for data_type='signal', see signal_loop.run_signal_loop_
once()), NOT max(signal.ts) directly -- signal is a SPARSE table by design
("one row per gated touch-bar, not per candle", per the Signal model's own
docstring), so a quiet market with no new signal for a while is normal and
would falsely trip a max(ts)-based staleness check even though the loop
itself is running fine every cycle. ohlcv/funding_rate don't have this
problem (both are written every single poll cycle unconditionally), so
those two genuinely can use max(ts) directly.
"""

import datetime
import json
import sys

LABELS = (
    ("ohlcv", "ohlcv_max"),
    ("funding_rate", "funding_max"),
    ("signal loop heartbeat", "signal_heartbeat"),
)


def check_freshness(response_json: str, threshold_hours: float, now: datetime.datetime) -> list[str]:
    """Returns a list of human-readable staleness problems -- empty means
    everything is fresh. Pure function of the parsed response + an
    explicit `now` (no real clock read here), so this is fully testable
    without real time passing."""
    row = json.loads(response_json)["rows"][0]
    problems = []
    for label, key in LABELS:
        value = row.get(key)
        if value is None:
            problems.append(f"{label}: NO DATA AT ALL")
            continue
        ts = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        age_hours = (now - ts).total_seconds() / 3600.0
        if age_hours > threshold_hours:
            problems.append(f"{label} is {age_hours:.2f}h stale (> {threshold_hours}h threshold)")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    response_json, threshold_hours = argv[0], float(argv[1])
    now = datetime.datetime.now(datetime.timezone.utc)
    problems = check_freshness(response_json, threshold_hours, now)
    if problems:
        print("::error::" + "; ".join(problems))
        return 1
    print("all fresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
