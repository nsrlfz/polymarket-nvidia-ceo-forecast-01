import json
import math
import os
from pathlib import Path
import statistics

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

SPREAD_FLOOR = 0.0005
SPREAD_CEILING = 0.02
NORMAL_QUANTILES = (-1.644854, -0.674490, 0.0, 0.674490, 1.644854)


def _percentile(values, fraction):
    """Return a linearly interpolated percentile for a nonempty sequence."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def estimate_spread(prices):
    """Estimate and bound one-minute price movement from recent observations."""
    if not prices:
        return SPREAD_FLOOR

    recent = prices[-720:]
    changes = [
        abs(float(recent[index]) - float(recent[index - 1]))
        for index in range(1, len(recent))
    ]
    if not changes:
        spread = SPREAD_FLOOR
    else:
        median_change = statistics.median(changes)
        percentile_90 = _percentile(changes, 0.90)
        spread = 0.5 * (
            median_change / 0.6745 + percentile_90 / 1.6449
        )

    return min(SPREAD_CEILING, max(SPREAD_FLOOR, spread))


def forecast_market(market, horizon):
    """Build forecast rows for one market."""
    prices = market.get("prices") or []
    if prices:
        centre = float(prices[-1])
        spread = estimate_spread(prices)
    else:
        centre = 0.5
        spread = SPREAD_FLOOR

    rows = []
    for minute in range(1, horizon + 1):
        scale = spread * math.sqrt(minute)
        row = [
            round(min(1.0, max(0.0, centre + quantile * scale)), 6)
            for quantile in NORMAL_QUANTILES
        ]
        for index in range(1, len(row)):
            if row[index] < row[index - 1]:
                row[index] = row[index - 1]
        rows.append(row)
    return {"id": market.get("id"), "q": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for input_path in sorted(INPUT_DIR.iterdir(), key=lambda path: path.name):
        if not input_path.is_file() or not input_path.name.endswith(".in"):
            continue

        with input_path.open("r", encoding="utf-8") as source:
            case = json.load(source)

        horizon = int(case["horizon_minutes"])
        forecasts = [
            forecast_market(market, horizon)
            for market in case.get("markets", [])
        ]
        result = {"forecasts": forecasts}
        output_path = OUTPUT_DIR / (input_path.name[:-3] + ".out")
        with output_path.open("w", encoding="utf-8", newline="") as destination:
            json.dump(result, destination, separators=(",", ":"), ensure_ascii=False)
            destination.write("\n")


if __name__ == "__main__":
    main()
