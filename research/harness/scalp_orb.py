"""The opening-range breakout, on the two openings an index CFD actually has.

    ./.secrets/lab.sh run research/harness/scalp_orb.py

`scalps.py` found one live candidate in 207 cells: an opening-range breakout at
15 minutes on the three US indices read **+0.0877R over 375 trades** where the
same rule on markets with no opening read **-0.0553R over 830**. That is 3 of 3
instruments positive with the control negative, on a sample small enough that
none of the three cleared its own interval. This run asks the same question
with the sample the problem deserves, and with the **anchor corrected**.

## The anchor was wrong, and it is the whole claim

A US index CFD here quotes about 23 hours a day with one daily break, so the
"session open" `scalps.py` found from the gaps in the feed is the **CFD
reopen** - around 22:00-23:00 UTC, a thin hour with no auction in it. A trader
asking for an opening-range breakout on US indices means **09:30 New York**,
the cash open, which is a different instant and the one the auction is at.
Both are measured here and reported separately, computed through
`zoneinfo.ZoneInfo("America/New_York")` so the daylight-saving shift is right
rather than approximated as a fixed UTC hour.

## And the control is the point

A Deriv synthetic has no opening of either kind: it quotes continuously and its
generator has no session. Running the identical rule on one, anchored at the
same 09:30 New York, is a control that **must read nothing** - and if it reads
the same as the indices then whatever the rule earns is not the opening.

Depth: `data/btc` holds 50,000 15-minute bars an index (2024-08 to 2026-10, 549
sessions) against the 20,000 that 300,000 M1 bars aggregate to, so the 15m
arms run off the 15m store. The 1m/3m/5m arms still come from M1 and cover ten
months, which is stated rather than pooled with the deeper window.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import zoneinfo
from collections import defaultdict
from pathlib import Path

import numpy as np

from research.harness import scalps
from research.harness.venue import quoted

HOME = Path.home() / "till_infinity" / "data"
OUT = Path.home() / "till_infinity" / "logs" / "scalp_orb.json"
NY = zoneinfo.ZoneInfo("America/New_York")
CASH_OPEN = dt.time(9, 30)
#: The cash session, 09:30 to 16:00 New York. A break is only an *opening* range
#: breakout inside the session that opened: without this bound a bar seventeen
#: hours later still carries the morning's range, and the rule becomes an
#: overnight trade wearing an ORB's name.
CASH_SPAN = 6.5 * 3600

INDICES = ("US Tech 100", "Wall Street 30", "US SP 500")
CONTROLS = ("Volatility 75 Index", "Step Index", "Volatility 25 Index")
FAST_CLOCKS = tuple(int(c) for c in os.environ.get("FAST_CLOCKS", "1,3,5").split(","))
ARMS = scalps.ARMS


def cash_anchor(time: np.ndarray) -> np.ndarray:
    """The epoch of 09:30 New York on each bar's own New York date.

    Through `zoneinfo`, not a fixed UTC hour: 09:30 New York is 13:30 UTC for
    most of the year and 14:30 UTC for the rest, and a fixed hour would put the
    opening range an hour off for half the sample - on the one statistic the
    whole study turns on.
    """
    days: dict[int, list[float]] = {}
    for stamp in np.unique((time // 86400).astype(np.int64)):
        # **Noon UTC, not midnight.** Midnight UTC is 19:00 or 20:00 of the
        # *previous* New York day, so `.date()` on it named the wrong day and
        # every bar took an anchor seventeen hours old. The opening range was
        # then never inside its own window and the rule fired **zero** times on
        # all six instruments - printing as "too few signals" rather than as an
        # error, which is how it survived one whole run.
        base = dt.datetime.fromtimestamp(int(stamp) * 86400 + 43200, dt.UTC).astimezone(NY).date()
        days[int(stamp)] = [
            dt.datetime.combine(base - dt.timedelta(days=offset), CASH_OPEN, tzinfo=NY).timestamp()
            for offset in (0, 1)
        ]
    out = np.full(len(time), np.nan)
    for i, t in enumerate(time):
        inside = [o for o in days.get(int(t // 86400), ()) if 0 <= t - o <= CASH_SPAN]
        if inside:
            out[i] = max(inside)
    return out


def bars_at(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as data:
        return {
            k: np.asarray(data[k], dtype=np.float64)
            for k in ("time", "open", "high", "low", "close")
        }


def features(bars: dict[str, np.ndarray], anchor: str) -> dict:
    """Indicators on bars already at the execution clock.

    The context filter here is the **previous bar on the same clock**, not a
    higher timeframe: these bars are 15-minute bars and there is no M1 under
    them to build an M15 from. Labelled rather than quietly reused, because
    "the M15 filter" means something different at a 15-minute execution clock.
    """
    f = dict(bars)
    f["atr"] = scalps.atr(bars["high"], bars["low"], bars["close"])
    f["fast"] = scalps.ema(bars["close"], scalps.FAST_N)
    f["slow"] = scalps.ema(bars["close"], scalps.SLOW_N)
    f["mid"], f["lower"], f["upper"] = scalps.bands(bars["close"])
    f["rsi"] = scalps.rsi(bars["close"])
    sign = np.sign(f["fast"] - f["slow"])
    sign[: scalps.SLOW_N * 2] = 0.0
    f["ctx"] = np.concatenate(([0.0], sign[:-1]))
    if anchor == "cash":
        f["session"] = cash_anchor(bars["time"])
    else:
        gaps = np.flatnonzero(np.diff(bars["time"]) > scalps.SESSION_GAP)
        opens = np.concatenate(([bars["time"][0]], bars["time"][gaps + 1]))
        at = np.searchsorted(opens, bars["time"], side="right") - 1
        f["session"] = np.where(at >= 0, opens[np.maximum(at, 0)], np.nan)
    f["real_session"] = anchor == "cash"
    return f


def run(symbol: str, bars: dict, clock: int, anchor: str, trip: float, rng, kind: str) -> dict:
    f = features(bars, anchor)
    unit = float(np.nanmedian(f["atr"]))
    cost = trip / unit if unit > 0 else float("inf")
    index, side = scalps.orb(f)
    if len(index) < 40:
        print(f"  {symbol:<22}{clock:>3}m {anchor:<6} {len(index)} signals, too few")
        return {}
    made = scalps.arms(f, "orb", index, side, trip, rng)
    got = {arm: scalps.summarise(made[arm], rng) for arm in ARMS if arm in made}
    gross = scalps.summarise(made["rule"], rng, key="gross")
    print(
        f"\n  == {symbol} {clock}m {anchor} ({kind}) ==  cost/R {cost:.3f}"
        f"  sessions {len(set(f['session'][index]))}"
    )
    for arm in ARMS:
        if arm in got:
            scalps.show(arm, got[arm])
    print(
        f"      {'rule, gross':<14} n {gross['n']:>6,}        gross {gross['mean']:+7.4f}"
        f" [{gross['lo']:+7.4f},{gross['hi']:+7.4f}] p {gross['p']:.3f}"
    )
    against = {}
    for other in ARMS[1:]:
        if other in made:
            diff = scalps.compare(made["rule"], made[other], rng)
            if diff:
                against[other] = diff
                print(
                    f"      vs {other:<11} diff {diff['diff']:+7.4f}"
                    f" [{diff['lo']:+7.4f},{diff['hi']:+7.4f}] p {diff['p']:.3f}"
                )
    power = {
        f"{s:g}": scalps.planted(f, made["rule"], s, rng).get("mean") for s in scalps.PLANTS
    }
    print("      power          " + "  ".join(f"{k}:{v:+.3f}" for k, v in power.items()))
    return {
        "symbol": symbol,
        "clock": clock,
        "anchor": anchor,
        "kind": kind,
        "cost_r": cost,
        "arms": got,
        "gross": gross,
        "against": against,
        "power": power,
        "trades": made["rule"],
    }


def main() -> int:
    rng = np.random.default_rng(scalps.SEED)
    print(
        "ORB: break of the opening 15 minutes, held one bar, 1 ATR stop / 2 ATR target.\n"
        "'cash' anchors at 09:30 New York through zoneinfo; 'reopen' at the gap in the feed.\n"
        "A synthetic has neither, so its rows are the control that must read nothing.\n"
    )
    rows: list[dict] = []
    trips = {}
    for symbol in INDICES + CONTROLS:
        trips[symbol] = quoted(symbol)

    print("### 15 minutes, off the 15-minute store (50,000 bars an index) ###")
    for kind, group, store in (
        ("index", INDICES, HOME / "btc"),
        ("control", CONTROLS, HOME / "seqlab"),
    ):
        for symbol in group:
            path = store / f"{symbol}.15m.npz"
            if not path.exists():
                print(f"  {symbol}: no 15m file in {store.name}")
                continue
            bars = bars_at(path)
            for anchor in ("cash", "reopen"):
                got = run(symbol, bars, 15, anchor, trips[symbol], rng, kind)
                if got:
                    rows.append(got)

    print("\n### 1m / 3m / 5m, off the 300,000-bar M1 store (ten months) ###")
    for kind, group in (("index", INDICES), ("control", CONTROLS)):
        for symbol in group:
            path = HOME / "scalp" / f"{symbol}.1m.npz"
            if not path.exists():
                continue
            m1 = bars_at(path)
            for clock in FAST_CLOCKS:
                bars = scalps.clock_bars(m1, clock)
                got = run(symbol, bars, clock, "cash", trips[symbol], rng, kind)
                if got:
                    rows.append(got)

    print("\n### pooled, by kind and clock and anchor ###")
    pooled = {}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["kind"], row["clock"], row["anchor"])].append(row)
    for key, members in sorted(groups.items()):
        trades = [t for row in members for t in row["trades"]]
        if not trades:
            continue
        got = scalps.summarise(trades, rng)
        gross = scalps.summarise(trades, rng, key="gross")
        pooled["|".join(str(x) for x in key)] = {"net": got, "gross": gross}
        print(
            f"  {key[0]:<8}{key[1]:>3}m {key[2]:<7} cells {len(members):>2}"
            f"  n {got['n']:>6,} d {got['days']:>4}  net {got['mean']:+7.4f}"
            f" [{got['lo']:+7.4f},{got['hi']:+7.4f}] p {got['p']:.3f}"
            f"  gross {gross['mean']:+7.4f} [{gross['lo']:+7.4f},{gross['hi']:+7.4f}]"
            f"  P(hit) {got['reached']:.3f} vs {got['breakeven']:.3f}"
        )

    print("\n### index minus control, the same clock and anchor, shared days ###")
    for clock in (15,) + FAST_CLOCKS:
        for anchor in ("cash", "reopen"):
            left = [t for r in rows if r["kind"] == "index" and r["clock"] == clock and r["anchor"] == anchor for t in r["trades"]]
            right = [t for r in rows if r["kind"] == "control" and r["clock"] == clock and r["anchor"] == anchor for t in r["trades"]]
            if not left or not right:
                continue
            diff = scalps.compare(left, right, rng)
            if diff:
                pooled[f"index-control|{clock}|{anchor}"] = diff
                print(
                    f"  {clock:>3}m {anchor:<7} diff {diff['diff']:+7.4f}"
                    f" [{diff['lo']:+7.4f},{diff['hi']:+7.4f}] p {diff['p']:.3f}"
                    f"  shared days {diff['days']}"
                )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "rows": [{k: v for k, v in r.items() if k != "trades"} for r in rows],
                "pooled": pooled,
            },
            indent=1,
            default=str,
        )
    )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
