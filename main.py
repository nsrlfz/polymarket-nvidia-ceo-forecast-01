import json
import math
import os
from pathlib import Path


INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
SPREAD_FLOOR = 0.0003
SPREAD_CEILING = 0.02
QUANTILE_MULTIPLIERS = (
    -1.644854 * 1.25,
    -0.674490,
    0.0,
    0.674490,
    1.644854 * 1.25,
)


def interpolated_percentile(values, fraction):
    """Return a linearly interpolated percentile for a non-empty sequence."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = position - lower_index
    return ordered[lower_index] * (1.0 - weight) + ordered[upper_index] * weight


def estimate_spread(prices):
    """Estimate a bounded per-root-minute spread from recent absolute moves."""
    recent = prices[-720:]
    changes = [
        abs(float(recent[index]) - float(recent[index - 1]))
        for index in range(1, len(recent))
    ]
    if changes:
        median_term = interpolated_percentile(changes, 0.50) / 0.6745
        upper_term = interpolated_percentile(changes, 0.90) / 1.6449
        spread = (median_term + upper_term) / 2.0
    else:
        spread = SPREAD_FLOOR
    return min(SPREAD_CEILING, max(SPREAD_FLOOR, spread))


def build_market_rows(market, case_price_sum, horizon):
    prices = market.get("prices", [])
    centre_price = float(prices[-1]) if prices else 0.5
    if prices:
        spread = estimate_spread(prices)
    else:
        spread = SPREAD_FLOOR
    drift = -0.25 * (case_price_sum - 1.0) * centre_price

    rows = []
    for minute in range(1, horizon + 1):
        minute_centre = centre_price + drift * minute / 60.0
        scale = spread * math.sqrt(minute)
        row = []
        for multiplier in QUANTILE_MULTIPLIERS:
            forecast = minute_centre + multiplier * scale
            rounded = round(min(1.0, max(0.0, forecast)), 6)
            if row and rounded < row[-1]:
                rounded = row[-1]
            row.append(rounded)
        rows.append(row)
    return rows


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_files = sorted(
        (path for path in INPUT_DIR.iterdir() if path.name.endswith(".in")),
        key=lambda path: path.name,
    )
    for input_path in input_files:
        with input_path.open("r", encoding="utf-8") as source:
            case = json.load(source)

        markets = case.get("markets", [])
        horizon = int(case.get("horizon_minutes", 0))
        case_price_sum = sum(
            float(market["prices"][-1])
            for market in markets
            if market.get("prices")
        )
        forecasts = [
            {
                "id": market.get("id"),
                "q": build_market_rows(market, case_price_sum, horizon),
            }
            for market in markets
        ]
        output_path = OUTPUT_DIR / (input_path.name[:-3] + ".out")
        with output_path.open("w", encoding="utf-8", newline="") as destination:
            json.dump({"forecasts": forecasts}, destination, separators=(",", ":"))
            destination.write("\n")


if __name__ == "__main__":
    main()
