"""What the spread actually costs, as a fraction of a stop - the number that decides.

Run on the research machine:  python research/harness/spread_cost.py

`jump_odds.py` found the one positive result of this research: on Boom, shorts beat the
driftless fair-odds line by +4.1 points at a reward-to-risk of one, and on Crash longs
do the same. Expectancy there is

    2p - 1 - cost     with p = 0.541  ->  +0.082 - cost

**so the edge exists if and only if the round-trip cost is under 8.2% of the stop
distance**, and the stop distance is one true range. That is the whole question, and it
is measurable rather than arguable.

`history.py` writes only time, open, high, low, close and volume, so the saved files
cannot answer it - the bridge returns a `spread` on every bar and it was being dropped.
This reads it directly.

## The arithmetic, stated so it can be checked

MT5 reports `spread` in **points**, so it becomes a price by multiplying by the
symbol's point size. A market order opens at the ask and closes at the bid, so a round
trip pays the spread **once**, not twice - which is worth saying because doubling it
would halve the apparent headroom.

The quantity that matters is therefore

    cost_in_R = spread_in_price / (true_range * price)

and the thresholds from `jump_odds.py` are **0.082** at a reward-to-risk of one and
**0.113** at two. Anything below those and the edge survives; anything above and it was
an artefact of assuming 0.03.

Synthetics are quoted continuously, so there is no session effect to average away, but
the median is reported alongside the mean because a spread distribution has a tail and
the mean is the wrong summary for a cost you pay on every trade.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from history import PAGE, TIMEFRAMES, bridge_key  # noqa: E402

#: The thresholds from `jump_odds.py`, as cost in units of the stop distance.
BREAKEVEN = {1.0: 0.082, 2.0: 0.113}

#: Nights a position is carried. `jump_odds.py` resolves over 192 hourly bars, which
#: is eight days, so eight rollovers are paid and not one.
HOLD_NIGHTS = 8

#: Symbols worth asking about: the pair carrying the result, plus FX for scale.
DEFAULT = [
    "Boom 1000 Index",
    "Crash 1000 Index",
    "Boom 900 Index",
    "Crash 900 Index",
    "XAUUSD",
    "EURUSD",
]


def ask(url: str, path: str, query: dict, headers: dict):
    target = f"{url}/api/v1{path}?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(target, headers=headers)
    with urllib.request.urlopen(request, timeout=180) as answer:
        return json.loads(answer.read())


def point_size(url: str, symbol: str, headers: dict) -> float:
    """The symbol's point, which converts a spread in points into a price.

    Taken from the bridge rather than guessed from the number of decimals, because
    guessing is how a cost ends up out by a factor of ten and nobody notices.
    """
    try:
        info = ask(url, "/symbols/info", {"symbol": symbol}, headers)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0.0
    if not isinstance(info, dict):
        return 0.0
    for key in ("point", "trade_tick_size", "tick_size"):
        value = info.get(key)
        if isinstance(value, int | float) and value > 0:
            return float(value)
    digits = info.get("digits")
    return float(10 ** -int(digits)) if isinstance(digits, int) else 0.0


def swap_cost(url: str, symbol: str, headers: dict, unit: float) -> float | None:
    """Overnight financing over the holding period, in units of one stop.

    This is the cost the spread study nearly missed. `jump_odds.py` uses a 192-bar
    horizon on hourly bars, which is **eight days**, so a position is carried over
    roughly eight rollovers. A swap that is negligible per night is not negligible
    eight times over against an edge worth 8% of one stop.

    The sign matters and is reported as a cost, so a positive number is money lost. The
    Boom result is a *short*, so it is `swap_short` that applies; the mirrored Crash
    result is a long and takes `swap_long`. The worse of the two is returned, because a
    result that only survives on one side of the mirror is not the result claimed.
    """
    try:
        info = ask(url, "/symbols/info", {"symbol": symbol}, headers)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    longs, shorts = info.get("swap_long"), info.get("swap_short")
    if not isinstance(longs, int | float) or not isinstance(shorts, int | float):
        return None
    mode = info.get("swap_mode")
    # Only points mode converts straightforwardly; anything else is flagged rather
    # than silently turned into a number that looks authoritative.
    point = point_size(url, symbol, headers)
    if mode not in (None, 0, 1, 2) or point <= 0 or unit <= 0:
        return None
    worst = min(float(longs), float(shorts))  # most negative is the biggest cost
    return abs(worst) * point * HOLD_NIGHTS / unit


def measure(url: str, symbol: str, headers: dict, code: str) -> None:
    """One symbol's row: spread quiet, at the 99th percentile, and during spikes."""
    point = point_size(url, symbol, headers)
    try:
        raw = ask(
            url,
            "/symbols/rates/pos",
            {"symbol": symbol, "timeframe": code, "num_bars": PAGE},
            headers,
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"{symbol:<22} {type(exc).__name__}")
        return
    if not isinstance(raw, list) or len(raw) < 100:
        print(f"{symbol:<22} no bars")
        return

    spreads, highs, lows = [], [], []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            spreads.append(float(row.get("spread", 0.0)))
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(spreads) < 100 or point <= 0:
        print(f"{symbol:<22} {len(spreads):>7} bars, point={point}")
        return

    sp = np.array(spreads, dtype=float) * point
    rng = np.array(highs, dtype=float) - np.array(lows, dtype=float)
    good = rng > 0
    if good.sum() < 100:
        print(f"{symbol:<22} no ranges")
        return
    unit = float(np.median(rng[good]))

    # The median is the wrong statistic for this edge and it is worth being explicit
    # about why. The Boom trade is entered on or just after a spike, and a spread that
    # is 0.4% of a range in a quiet hour can be many times that in the minute a spike
    # prints. So the spread is also taken **conditional on the widest 5% of bars**,
    # which is the population the trade actually lives in.
    loud = rng >= np.quantile(rng[good], 0.95)
    cost_r = float(np.median(sp)) / unit
    cost_loud = (float(np.median(sp[loud])) / unit) if loud.sum() else float("nan")
    decides = max(cost_r, cost_loud)

    if decides < BREAKEVEN[1.0]:
        verdict = "survives at R:R 1"
    elif decides < BREAKEVEN[2.0]:
        verdict = "only at R:R 2"
    else:
        verdict = "edge is gone"
    print(
        f"{symbol:<22}{len(sp):>7,}{point:>10.5f}{float(np.median(sp)):>11.4f}"
        f"{cost_r:>9.3f}{float(np.quantile(sp, 0.99)) / unit:>9.3f}"
        f"{cost_loud:>9.3f}{verdict:>20}"
    )
    carry = swap_cost(url, symbol, headers, unit)
    if carry is not None:
        print(f"{'':<22}{'8-day carry, in R:':>37}{carry:>9.3f}   <- add to the above")


def main() -> int:
    url = os.environ.get("TRADING_MT5_URL", "").rstrip("/")
    if not url:
        print("TRADING_MT5_URL is not set - there is no bridge to read")
        return 1
    headers = {"Accept": "application/json"}
    key = bridge_key()
    if key:
        headers["X-API-Key"] = key

    # Underscores become spaces. `lab.sh` forwards env through an unquoted `$*`, so a
    # space in "Boom 1000 Index" stops the process starting and leaves no log at all -
    # which cost an hour the first time and is worth the two lines to avoid.
    wanted = [s.strip().replace("_", " ") for s in os.environ.get("MATCH", "").split(",")]
    symbols = [s for s in wanted if s] or DEFAULT
    interval = os.environ.get("INTERVAL", "1h")
    code = TIMEFRAMES.get(interval, "H1")

    print(
        f"spread on {interval} bars as a share of one true range. `loud/R` is the\n"
        "median spread on the widest 5% of bars - the population a spike trade\n"
        "actually lives in, and the column that decides the Boom result.\n"
    )
    print(
        f"{'symbol':<22}{'bars':>7}{'pt':>10}{'med price':>11}"
        f"{'cost/R':>9}{'p99/R':>9}{'loud/R':>9}{'verdict':>20}"
    )

    for symbol in symbols:
        measure(url, symbol, headers, code)

    print(
        "\n  cost/R is the median spread over the median bar range, a slightly\n"
        "  conservative stand-in for one true range - it understates the range and so\n"
        "  overstates the cost, which is the direction an honest approximation should\n"
        "  err in when it is deciding whether to trade.\n"
        "\n  The verdict reads the **worst** of the quiet and loud columns, because a\n"
        "  spike trade pays the loud one, and adds nothing for carry - the carry line\n"
        "  is printed separately and has to be added by hand, so it cannot be\n"
        "  forgotten the way it nearly was."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
