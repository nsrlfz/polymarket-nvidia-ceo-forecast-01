import json
import math
import os
from pathlib import Path

PRICE_FLOOR = 0.0003
PRICE_SPREAD_CAP = 0.02
LOGIT_FLOOR = 0.02
LOGIT_SPREAD_CAP = 1.5
QUANTILE_BASES = (-1.644854, -0.674490, 0.0, 0.674490, 1.644854)
PRICE_MULTIPLIERS_SHORT = (
    -1.644854 * 1.6,
    -0.674490,
    0.0,
    0.674490,
    1.644854,
)
PRICE_MULTIPLIERS_LONG = (
    -1.644854 * 1.25,
    -0.674490,
    0.0,
    0.674490,
    1.644854 * 1.25,
)
LOGIT_MULTIPLIERS = QUANTILE_BASES
INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))


def percentile(values, fraction):
    """Return a linearly interpolated percentile of a non-empty sequence."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def price_spread(prices, window):
    """Estimate a bounded price-space spread from a recent price window."""
    recent = prices[-window:]
    changes = [
        abs(float(recent[index]) - float(recent[index - 1]))
        for index in range(1, len(recent))
    ]
    if changes:
        spread = (
            percentile(changes, 0.50) / 0.6745
            + percentile(changes, 0.90) / 1.6449
        ) / 2.0
    else:
        spread = PRICE_FLOOR
    return min(PRICE_SPREAD_CAP, max(PRICE_FLOOR, spread))


def price_to_log_odds(price):
    bounded = min(0.9999, max(0.0001, float(price)))
    return math.log(bounded / (1.0 - bounded))


def log_odds_to_price(value):
    if value >= 0.0:
        exp_value = math.exp(-value) if value < 746.0 else 0.0
        result = 1.0 / (1.0 + exp_value)
    else:
        exp_value = math.exp(value) if value > -746.0 else 0.0
        result = exp_value / (1.0 + exp_value)
    return min(1.0, max(0.0, result))


def logit_spread(prices, window):
    """Estimate a bounded log-odds spread from recent price changes."""
    recent = prices[-window:]
    logits = [price_to_log_odds(price) for price in recent]
    changes = [
        abs(logits[index] - logits[index - 1])
        for index in range(1, len(logits))
    ]
    if changes:
        spread = (
            percentile(changes, 0.50) / 0.6745
            + percentile(changes, 0.90) / 1.6449
        ) / 2.0
    else:
        spread = LOGIT_FLOOR
    return min(LOGIT_SPREAD_CAP, max(LOGIT_FLOOR, spread))


def enforce_rows(rows):
    """Clamp, round, and make each quantile row non-decreasing."""
    for row in rows:
        previous = 0.0
        for index, value in enumerate(row):
            value = round(min(1.0, max(0.0, value)), 6)
            if index and value < previous:
                value = previous
            row[index] = value
            previous = value
    return rows


def market_centre_and_drift(market, drift_factor):
    prices = market.get("prices", [])
    centre = float(prices[-1]) if prices else 0.5
    drift = drift_factor * centre
    return prices, centre, drift


def price_fan(market, drift_factor, horizon, window, multipliers):
    prices, centre, drift = market_centre_and_drift(market, drift_factor)
    spread = price_spread(prices, window)
    rows = []
    for minute in range(1, horizon + 1):
        moving_centre = centre + drift * minute / 60.0
        scale = spread * math.sqrt(minute)
        rows.append([moving_centre + multiplier * scale for multiplier in multipliers])
    return enforce_rows(rows)


def component_one(market, drift_factor, horizon):
    return price_fan(
        market, drift_factor, horizon, 720, PRICE_MULTIPLIERS_SHORT
    )


def component_two(market, drift_factor, horizon):
    return price_fan(
        market, drift_factor, horizon, 1440, PRICE_MULTIPLIERS_LONG
    )


def component_three(market, drift_factor, horizon):
    prices, centre, drift = market_centre_and_drift(market, drift_factor)
    spread = logit_spread(prices, 1440)
    rows = []
    for minute in range(1, horizon + 1):
        moving_centre = centre + drift * minute / 60.0
        logit_centre = price_to_log_odds(moving_centre)
        scale = spread * math.sqrt(minute)
        rows.append([
            log_odds_to_price(logit_centre + multiplier * scale)
            for multiplier in LOGIT_MULTIPLIERS
        ])
    return enforce_rows(rows)


def forecast_market(market, drift_factor, horizon):
    first = component_one(market, drift_factor, horizon)
    second = component_two(market, drift_factor, horizon)
    third = component_three(market, drift_factor, horizon)
    rows = []
    for row_index in range(horizon):
        rows.append([
            0.5 * first[row_index][column]
            + 0.25 * second[row_index][column]
            + 0.25 * third[row_index][column]
            for column in range(5)
        ])
    return enforce_rows(rows)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for input_path in sorted(INPUT_DIR.iterdir(), key=lambda path: path.name):
        if not input_path.name.endswith(".in") or not input_path.is_file():
            continue
        with input_path.open("r", encoding="utf-8") as source:
            case = json.load(source)
        markets = case.get("markets", [])
        horizon = int(case["horizon_minutes"])
        price_sum = sum(
            float(market["prices"][-1])
            for market in markets
            if market.get("prices")
        )
        drift_factor = -0.25 * (price_sum - 1.0)
        forecasts = [
            {
                "id": market["id"],
                "q": forecast_market(market, drift_factor, horizon),
            }
            for market in markets
        ]
        output_path = OUTPUT_DIR / (input_path.name[:-3] + ".out")
        with output_path.open("w", encoding="utf-8", newline="\n") as target:
            json.dump(
                {"forecasts": forecasts},
                target,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            target.write("\n")


if __name__ == "__main__":
    main()
