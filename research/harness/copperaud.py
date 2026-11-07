"""Does a copper breakout lead AUD/JPY?

    ./.secrets/lab.sh run research/harness/copperaud.py

The rule as supplied: copper's H1 close breaks its highest close of the
previous 96 hours and you buy AUD/JPY at the next H1 open, or breaks the
lowest and you sell; exit after 24 H1 bars or at the Friday 20:00 UTC cut;
no entries 19-23 UTC; 1R is AUD/JPY's H1 ATR(14); one position at a time.
Claimed +0.91R on 35 trades.

## This is a mechanics study, not an edge study

The terminal serves **3,970 H1 bars of XCUUSD - 288 days**, against 20,000
for AUDJPY. Copper is the binding constraint and no amount of care fixes it,
so n will land near the 35 the claim arrives with, and this desk's own rule is
that under about 100 trades the prior is noise. What this run can settle is
whether the rule reproduces, what it costs, and whether it beats the one
control that matters.

## The control the claim needs

The named property is **copper leads AUD/JPY**. So the control is AUD/JPY's
*own* 96-hour breakout on the same bars: if following AUDJPY's own breakout
pays the same, copper is not leading anything and the rule is a momentum rule
wearing a cross-asset story. `crossing.md` already measured 336 pairs and
found no instrument leads another - the largest implied move anywhere was
0.089bps against a 2.35bps spread - and `linear-algebra.md` explains why,
finding one factor in this book carrying 45.6% of variance. Copper and AUD
both loading on it would produce exactly this rule's appearance.

## Cost

Spread floored at 1.2x the hourly median as specified, converted from points
with the venue's own `digits`, and charged once per round trip. The per-bar
spread column is the one this repository measured as unusable as a *level*;
its median across 20,000 bars is used only to scale, and the floor is the
claim's own.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request as request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cotfade as cf  # noqa: E402

FX = Path.home() / "till_infinity" / "data" / "cotfx"
LOOKBACK = 96
HOLD = 24
ATR_N = 14
NO_ENTRY_HOURS = {19, 20, 21, 22, 23}
FRIDAY_CUT = 20
SPREAD_FLOOR = 1.2
DRAWS = 2000
SEED = 20261107
BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"


def digits(symbol: str) -> int:
    key = (Path.home() / ".mt5key").read_text().strip()
    req = request.Request(  # noqa: S310
        f"{BASE}/symbols/info/{symbol}", headers={"X-API-Key": key}
    )
    with request.urlopen(req, timeout=60) as response:  # noqa: S310
        info = json.loads(response.read().decode())
    return int(info.get("digits") or 5)


def load(symbol: str) -> dict[str, np.ndarray]:
    with np.load(FX / f"{symbol}.1h.npz") as data:
        return {k: data[k] for k in ("time", "open", "high", "low", "close", "spread")}


def atr(bars: dict[str, np.ndarray], n: int) -> np.ndarray:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    for i in range(n, len(tr)):
        out[i] = tr[i - n : i].mean()
    return out


def signals(close: np.ndarray) -> np.ndarray:
    """+1 on a 96-hour closing high, -1 on a low, 0 otherwise."""
    side = np.zeros(len(close))
    for i in range(LOOKBACK, len(close)):
        window = close[i - LOOKBACK : i]
        if close[i] > window.max():
            side[i] = 1.0
        elif close[i] < window.min():
            side[i] = -1.0
    return side


def book(
    bars: dict[str, np.ndarray], risk: np.ndarray, side: np.ndarray, cost_px: float
) -> list[dict]:
    """One position at a time, entered at the next open, exited on time."""
    time, open_, close = bars["time"], bars["open"], bars["close"]
    out: list[dict] = []
    free = -1
    for i in range(len(side)):
        if side[i] == 0.0 or i + 1 >= len(time) or i + 1 <= free:
            continue
        entry = i + 1
        when = datetime.fromtimestamp(float(time[entry]), UTC)
        if when.hour in NO_ENTRY_HOURS:
            continue
        if not np.isfinite(risk[entry]) or risk[entry] <= 0.0:
            continue
        exit_i = min(entry + HOLD, len(time) - 1)
        for k in range(entry, exit_i + 1):
            at = datetime.fromtimestamp(float(time[k]), UTC)
            if at.weekday() == 4 and at.hour >= FRIDAY_CUT:
                exit_i = k
                break
        gross = side[i] * (close[exit_i] - open_[entry]) / risk[entry]
        out.append(
            {
                "ts": float(time[entry]),
                "gross": float(gross),
                "net": float(gross - cost_px / risk[entry]),
            }
        )
        free = exit_i
    return out


def report(name: str, rows: list[dict], rng) -> None:
    if not rows:
        print(f"{name:22s} {'0':>5s}")
        return
    gross = [row["gross"] for row in rows]
    net = [row["net"] for row in rows]
    boots = [
        float(np.mean([net[i] for i in rng.integers(0, len(net), len(net))]))
        for _ in range(DRAWS)
    ]
    print(
        f"{name:22s} {len(rows):5d} {np.mean(gross):8.3f} {np.mean(net):8.3f} "
        f"{np.percentile(boots, 2.5):8.3f} {np.percentile(boots, 97.5):8.3f} "
        f"{np.mean([v > 0 for v in net]):6.3f}"
    )


def main() -> int:
    rng = np.random.default_rng(SEED)
    copper, aud = load("XCUUSD"), load("AUDJPY")

    # Align on AUD/JPY's clock, keeping only hours both feeds served.
    shared = np.intersect1d(copper["time"], aud["time"])
    print(f"XCUUSD {len(copper['time'])} bars, AUDJPY {len(aud['time'])}, shared {len(shared)}")
    ci = np.searchsorted(copper["time"], shared)
    ai = np.searchsorted(aud["time"], shared)
    copper = {k: v[ci] for k, v in copper.items()}
    aud = {k: v[ai] for k, v in aud.items()}

    point = 10.0 ** -digits("AUDJPY")
    cost_px = SPREAD_FLOOR * float(np.median(aud["spread"])) * point
    risk = atr(aud, ATR_N)
    print(
        f"AUD/JPY point {point:g}, median spread {np.median(aud['spread']):.0f} pts, "
        f"round trip {cost_px:g} px = {np.nanmedian(cost_px / risk):.3f} R\n"
    )

    head = f"{'arm':22s} {'n':>5s} {'gross':>8s} {'net':>8s} {'lo':>8s} {'hi':>8s} {'win':>6s}"
    print(head)
    print("-" * len(head))

    real = signals(copper["close"])
    report("copper->audjpy", book(aud, risk, real, cost_px), rng)

    # The control for the named property: AUD/JPY's own breakout.
    report("audjpy own breakout", book(aud, risk, signals(aud["close"]), cost_px), rng)

    report("reversed", book(aud, risk, -real, cost_px), rng)

    stale = np.concatenate((np.zeros(24), real[:-24]))
    report("copper 24h stale", book(aud, risk, stale, cost_px), rng)

    shuffled = real.copy()
    nz = shuffled != 0.0
    shuffled[nz] = rng.permutation(shuffled[nz])
    report("sides shuffled", book(aud, risk, shuffled, cost_px), rng)

    fired = int((real != 0.0).sum())
    placed = np.zeros(len(real))
    if fired:
        where = rng.choice(np.arange(LOOKBACK, len(real)), size=fired, replace=False)
        placed[where] = rng.choice([-1.0, 1.0], size=fired)
    report("random time + coin", book(aud, risk, placed, cost_px), rng)

    print(
        "\nThe decisive row is `audjpy own breakout`. The claim is that COPPER leads;\n"
        "if AUD/JPY's own 96-hour breakout pays the same, nothing is being led."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
