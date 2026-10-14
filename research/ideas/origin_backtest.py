"""The displacement origin traded, with every filter this session found.

`fade-to-origin.md` traded this structure three ways and found no edge, with
**89-91% of fades stopped out** and -0.259R on 1d. The measurements since then
give four filters it did not have, so the question is whether they turn it:

1. **Freshness.** The edge wears out in about **three days** - fresh zones beat
   a matched price by 2 to 4 points, three-day-old ones by nothing, and
   fourteen-day-old ones by exactly zero. `drawing/displacement.py` says this
   had never been measured.
2. **Horizon.** The return-rate edge **peaks at twenty bars** (+0.037) and
   decays to +0.011 by five hundred, so the 300-bar convention was mostly
   noise around a twenty-bar effect.
3. **Formation volume.** The volume on the bar that *formed* the zone predicts
   holding at **0.5516 to 0.5625** - the one orderflow reading that is a level
   property rather than a property of arrivals.
4. **Depth.** The large effect is not the level at all: a retracement to **any**
   price at about two and a half typical bars is rejected 75% of the time and
   breaks under 10%, against the origin's 8.2%. The level is worth 1.6 points
   of that.

And the stop is the thing that killed it before: *a stop beyond an extreme that
was just made is close by definition*. So the stop distance is swept rather than
chosen, and the spread is charged on both legs in **points**, not price.

The honest expectation is that this stays negative. A 1.6-point edge in break
rate against an 89% stop-out rate is not a trade, and this file exists to say so
with the filters applied rather than to assume it.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screen import load  # noqa: E402

PUSH_BODY, PUSH_N = 0.65, 2
ORIGIN_BODY_MIN, ORIGIN_BODY_MAX = 0.10, 0.60
MIN_LEG_VOL = 1.5
LOOK = int(os.environ.get("LOOK", "100"))
#: Bars the arrival is waited for - twenty is where the edge peaks.
WAIT = int(os.environ.get("WAIT", "20"))
#: Bars the trade is held before it is marked out.
HOLD = int(os.environ.get("HOLD", "60"))
#: Stop distances beyond the band, in typical bars.
STOPS = tuple(float(k) for k in os.environ.get("STOPS", "0.5,1.0,2.0,4.0").split(","))
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h,1d").split(","))
PER_DAY = {"15m": 96, "1h": 24, "4h": 6, "1d": 1}


def points(name: str) -> float:
    if name.endswith("JPY") or name.startswith("XAU"):
        return 100.0
    if name.startswith("XAG"):
        return 1000.0
    return 10000.0


def trades(bars, name: str, stop_pad: float, frame: str) -> list[dict]:
    o, h, l_, c, v, s = (
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
        bars["spread"],
    )
    scale = points(name)
    out: list[dict] = []
    at = LOOK + 2
    end = len(c) - WAIT - HOLD - 4
    while at < end:
        window = slice(at - LOOK, at)
        typical = float(np.median(h[window] - l_[window]))
        if not (typical > 0):
            at += 1
            continue
        bodies = []
        ok = True
        for k in range(PUSH_N):
            span = float(h[at + k] - l_[at + k])
            if span <= 0:
                ok = False
                break
            bodies.append((float(c[at + k]) - float(o[at + k])) / span)
        if not ok or not all(abs(b) >= PUSH_BODY for b in bodies):
            at += 1
            continue
        if len({b > 0 for b in bodies}) != 1:
            at += 1
            continue
        up = bodies[0] > 0
        oi = at - 1
        span = float(h[oi] - l_[oi])
        if span <= 0:
            at += 1
            continue
        share = abs(float(c[oi]) - float(o[oi])) / span
        if not (ORIGIN_BODY_MIN <= share <= ORIGIN_BODY_MAX):
            at += 1
            continue
        body_low, body_high = min(float(o[oi]), float(c[oi])), max(float(o[oi]), float(c[oi]))
        entry = body_low if up else body_high
        band_low, band_high = float(l_[oi]), float(h[oi])
        run_end = at + PUSH_N - 1
        target = float(h[run_end]) if up else float(l_[run_end])
        if abs(target - entry) < MIN_LEG_VOL * typical:
            at += 1
            continue
        stop = (band_low - stop_pad * typical) if up else (band_high + stop_pad * typical)
        risk = abs(entry - stop)
        if risk <= 0:
            at += 1
            continue
        # Formation volume, the one level-specific orderflow reading.
        quiet = slice(max(oi - 20, 0), oi)
        base = float(np.mean(v[quiet])) if oi > 20 else 0.0
        form = float(v[oi]) / base if base > 0 else 1.0
        # The arrival, within WAIT bars.
        arrival = -1
        for step in range(1, WAIT + 1):
            i = run_end + step
            if i >= len(c):
                break
            if (float(l_[i]) <= entry) if up else (float(h[i]) >= entry):
                arrival = i
                break
        if arrival < 0:
            at = run_end + 1
            continue
        recent = float(np.mean(v[arrival - 20 : arrival])) if arrival > 20 else 0.0
        arrival_volume = float(v[arrival]) / recent if recent > 0 else 1.0
        # The trade: stop or target first, else marked at HOLD.
        reward = abs(target - entry)
        got = None
        for i in range(arrival + 1, min(arrival + 1 + HOLD, len(c))):
            if up:
                if float(l_[i]) <= stop:
                    got = -1.0
                    break
                if float(h[i]) >= target:
                    got = reward / risk
                    break
            else:
                if float(h[i]) >= stop:
                    got = -1.0
                    break
                if float(l_[i]) <= target:
                    got = reward / risk
                    break
        if got is None:
            last = float(c[min(arrival + HOLD, len(c) - 1)])
            got = ((last - entry) if up else (entry - last)) / risk
        # Costs: the spread crossed twice, in R.
        spread = float(s[arrival]) / scale + float(s[min(arrival + 1, len(s) - 1)]) / scale
        out.append(
            {
                "r": got - spread / risk,
                "raw_r": got,
                "cost_r": spread / risk,
                "won": 1.0 if got > 0 else 0.0,
                "age_days": (arrival - run_end) / PER_DAY.get(frame, 24),
                "form": form,
                "arrival_volume": arrival_volume,
                "depth": abs(target - entry) / typical,
                "rr": reward / risk,
            }
        )
        at = run_end + 1
    return out


def summarise(label: str, rows: list[dict]) -> None:
    if len(rows) < 60:
        print(f"    {label:<26}{len(rows):>6}  too few")
        return
    raw = np.array([x["raw_r"] for x in rows])
    cost = np.array([x["cost_r"] for x in rows])
    # **The mean R did not cohere, so cost is reported separately.** A win rate
    # of 0.340 at an R:R of 1.92 is an uncosted expectancy near zero, so a
    # costed -0.604R implies about 0.6R of cost a trade, which no FX spread
    # justifies. `spread / risk` is unbounded when the band is narrow and the
    # typical bar small, so a handful of trades can carry a mean - which is why
    # the median is here beside it.
    print(
        f"    {label:<26}{len(rows):>6}{float(np.median(raw)):>+8.2f}"
        f"{float(raw.mean()):>+9.3f}{float(np.mean([x['won'] for x in rows])):>8.3f}"
        f"{float(np.median([x['rr'] for x in rows])):>7.2f}"
        f"{float(np.median(cost)):>8.3f}{float(cost.mean()):>8.3f}"
        f"{float(raw.mean()) / (float(raw.std()) / math.sqrt(len(raw))):>8.2f}"
    )


def main() -> None:
    names = tuple(
        os.environ.get(
            "PAIRS",
            "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,GBPJPY,EURGBP,USDCHF,XAGUSD,NZDUSD",
        ).split(",")
    )
    print(
        f"origin fade: enter at the body edge on arrival within {WAIT} bars,\n"
        f"target the push extreme, held {HOLD} bars, spread charged both legs\n"
    )
    for frame in FRAMES:
        for stop_pad in STOPS:
            rows: list[dict] = []
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                rows += trades(bars, name, stop_pad, frame)
            if len(rows) < 60:
                continue
            print(f"  {frame}, stop {stop_pad:g} typical bars beyond the band")
            print(
                f"    {'filter':<26}{'n':>6}{'med R':>8}{'mean R':>9}{'win':>8}"
                f"{'R:R':>7}{'med c':>8}{'mean c':>8}{'t':>8}"
            )
            summarise("all", rows)
            fresh = [x for x in rows if x["age_days"] <= 3.0]
            summarise("fresh, <= 3 days", fresh)
            loud = [x for x in rows if x["form"] >= np.median([y["form"] for y in rows])]
            summarise("formed on high volume", loud)
            still = [
                x
                for x in rows
                if x["arrival_volume"] <= np.median([y["arrival_volume"] for y in rows])
            ]
            summarise("quiet arrival", still)
            deep = [x for x in rows if x["depth"] >= 2.5]
            summarise("depth >= 2.5", deep)
            both = [
                x
                for x in fresh
                if x["form"] >= np.median([y["form"] for y in rows])
                and x["arrival_volume"] <= np.median([y["arrival_volume"] for y in rows])
            ]
            summarise("all three filters", both)
            print()


if __name__ == "__main__":
    main()
