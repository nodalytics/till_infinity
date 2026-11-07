"""Given the COT fade's direction, does *when* you enter change anything?

    ./.secrets/lab.sh run research/harness/cotentry.py

## The question, stated so it can fail

The fade's direction is the one thing in this data that carries signal:
`-sign(score)` reads +0.243R de-drifted over 290 trades, its 8-week-stale twin
reads -0.026, and the trend version of the same data is null at every horizon
from 1 to 20 days. What it does not have is a good entry: it enters at a fixed
weekly timestamp and holds four weeks with no stop.

So this holds the bias and the exit fixed and varies only the entry:

* `close`    - the registered rule, the usable Wednesday's close.
* `pullback` - wait up to `WINDOW` days for price to go X ATR **against** the
               bias, and enter there. A better price for the same thesis.
* `breakout` - wait for X ATR **with** the bias. Confirmation.
* `random`   - a uniformly random day inside the same window.

**`random` is the arm that decides it.** If `pullback` beats `close` but not
`random`, the gain is the window, not the rule - the same duty-cycle trap that
every pause rule on this desk fell into. `origin-zones.md` put 3,697 intraday
entry cells against random-time and coin twins and none beat them, so the
prior is that entry timing is empty and the burden is here.

## Why the denominator is frozen at the signal date

Every arm divides by the **same** risk - 2 x daily ATR(20) at the signal bar -
so a difference between arms is a difference in price obtained and nothing
else. Letting each arm use its own entry-bar ATR would let a volatile entry
flatter itself by shrinking its own denominator, which is the one direction of
error nobody notices.

## Why daily and not 1h

Cost in R is `cost_px / risk` and is set by the stop, not the hold, so an
intraday stop raises cost per R in proportion as it shrinks. Slicing a slow
drift into finer bars does not create edge; the only thing a lower timeframe
can add is a better price, and whether a better price is obtainable at all is
testable at a day with 12.8 years of data already in hand. If it is, the same
question is worth a 15m pull; if a 0.25-ATR pullback adds nothing at a day, a
finer one will not.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cotfade as cf  # noqa: E402

WINDOW = 5
PADS = [0.25, 0.5, 1.0]
DRAWS = 400
SEED = 20261107


def arms(
    bars: dict[str, np.ndarray], risk: np.ndarray, i: int, side: float, exit_i: int, rng
) -> dict[str, tuple[float, float]]:
    """(R, adverse excursion in R) per arm, all over the same denominator."""
    close, high, low = bars["close"], bars["high"], bars["low"]
    unit = risk[i]
    out: dict[str, tuple[float, float]] = {}

    def settle(entry_i: int, label: str) -> None:
        if entry_i >= exit_i:
            return
        r = side * (close[exit_i] - close[entry_i]) / unit
        worst = 0.0
        for k in range(entry_i, exit_i + 1):
            against = (low[k] - close[entry_i]) if side > 0 else (close[entry_i] - high[k])
            worst = min(worst, against / unit)
        out[label] = (float(r), float(worst))

    settle(i, "close")
    settle(min(i + int(rng.integers(0, WINDOW + 1)), exit_i - 1), f"random-{WINDOW}d")

    for pad in PADS:
        # Against the bias: a cheaper price for the same thesis.
        hit = None
        for k in range(i + 1, min(i + WINDOW + 1, exit_i)):
            moved = (close[i] - close[k]) if side > 0 else (close[k] - close[i])
            if moved >= pad * unit / 2.0:
                hit = k
                break
        if hit is not None:
            settle(hit, f"pullback-{pad}")
        # With the bias: confirmation.
        hit = None
        for k in range(i + 1, min(i + WINDOW + 1, exit_i)):
            moved = (close[k] - close[i]) if side > 0 else (close[i] - close[k])
            if moved >= pad * unit / 2.0:
                hit = k
                break
        if hit is not None:
            settle(hit, f"breakout-{pad}")
    return out


def interval(values: list[float], rng) -> tuple[float, float]:
    if len(values) < 8:
        return float("nan"), float("nan")
    means = [
        float(np.mean([values[k] for k in rng.integers(0, len(values), len(values))]))
        for _ in range(DRAWS)
    ]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    rng = np.random.default_rng(SEED)
    collected: dict[str, list[float]] = defaultdict(list)
    adverse: dict[str, list[float]] = defaultdict(list)
    taken: dict[str, int] = defaultdict(int)

    for feed, symbol in cf.PAIRS.items():
        bars = cf.load_bars(symbol)
        risk = 2.0 * cf.atr(bars)
        usable, score = cf.scores(feed)
        rows = cf.trades(feed, bars, usable, score, risk=risk)
        time = bars["time"]
        hold = cf.HOLD_WEEKS * 7 * 86400.0
        for row in rows:
            i = int(np.searchsorted(time, row["entry_ts"], side="left"))
            exit_i = int(np.searchsorted(time, row["entry_ts"] + hold, side="left"))
            if exit_i >= len(time):
                continue
            for label, (r, worst) in arms(bars, risk, i, row["side"], exit_i, rng).items():
                collected[label].append(r)
                adverse[label].append(worst)
                taken[label] += 1

    print(
        f"COT fade, bias and exit fixed, entry varied. window {WINDOW}d, "
        f"R frozen at the signal bar's 2 x ATR(20)\n"
    )
    head = f"{'arm':16s} {'n':>5s} {'meanR':>8s} {'lo':>8s} {'hi':>8s} {'adverse':>9s} {'win':>6s}"
    print(head)
    print("-" * len(head))
    order = ["close", f"random-{WINDOW}d"] + [
        f"{kind}-{pad}" for kind in ("pullback", "breakout") for pad in PADS
    ]
    for label in order:
        values = collected.get(label) or []
        if not values:
            continue
        lo, hi = interval(values, rng)
        print(
            f"{label:16s} {len(values):5d} {np.mean(values):8.3f} {lo:8.3f} {hi:8.3f} "
            f"{np.mean(adverse[label]):9.3f} {np.mean([v > 0 for v in values]):6.3f}"
        )

    base = float(np.mean(collected["close"])) if collected.get("close") else float("nan")
    rand = (
        float(np.mean(collected[f"random-{WINDOW}d"]))
        if collected.get(f"random-{WINDOW}d")
        else float("nan")
    )
    print(f"\nbaseline (close) {base:+.3f}   random-in-window {rand:+.3f}")
    print(
        "An arm beats the rule only if it beats BOTH. Beating `close` alone is the\n"
        "window; beating `random` is the entry."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
