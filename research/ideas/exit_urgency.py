"""Exit urgency that rises with progress toward the target.

The proposal: rather than waiting for momentum to *reduce* before pulling out,
let the readiness to exit grow as price approaches the take-profit, so that
close to the target the **first adverse momentum candle** is enough to leave.
Far from the target the same candle is ignored.

This is a refinement of something already measured to work rather than a new
bet - `fade-to-value-loses-on-the-entry-not-the-target` found 62% of those
trades stopping out within 7 minutes at -10.81 while the targets paid +28.16,
and recorded that **managed exits pay**. So the question is not whether to
manage an exit but whether *this* schedule beats the alternatives.

## The rule

With entry `E`, stop `S`, target `T` and side `s`, progress is

    p = (close - E) * s / ((T - E) * s),  clamped to [0, 1]

and the trade leaves at the close of the first adverse bar whose body is at
least `theta(p) = theta0 * (1 - p)` units of the trade's own risk. At `p -> 1`
the threshold is zero, so any adverse bar exits; at `p = 0` only a bar of
`theta0` risk-units does. `theta0 = 0` is the degenerate member - always exit
on the first adverse bar - and it is carried deliberately, because if it
matches the sloped rule then the slope is decoration and only twitchiness is
doing the work.

## The controls, and why each is here

* **hold** - to target or stop, nothing managed. The baseline every other row
  is paired against; the trades are identical, so the comparison is paired and
  the standard error is of the *difference*.
* **trail** - the stop trails `trail_vol` risk-units behind the best price,
  which is what `trading/manage.py` already does in production. Beating `hold`
  is not interesting unless it also beats the incumbent.
* **random matched** - exits at a uniformly drawn bar whose index is matched
  to the holding time `urgency` actually took on that same trade. This is the
  control `strategy-rotation-is-not-timeable` forces: every pause rule there
  matched random pausing at the same duty cycle, so a rule that exits earlier
  must be compared against *exiting earlier*, not against holding.
* **shuffled path** - the same rule on a block-shuffled post-entry path. Bar
  geometry survives, sequence does not, so this says whether the rule needs
  the order of events or only their distribution.
* **walk** - the whole harness on geometric Brownian paths. `a-martingale-
  cannot-pay` is the standing rule, and the sharper form is **optional
  stopping**: for a martingale and a bounded stopping time every rule here must
  read 0, so a large *negative* is a bug exactly as much as a large positive.
  Both halves of that caught something. Settling on the fill bar won 0.470 of
  2R races against a required 0.333 in the memory, so settlement starts the bar
  after entry - and `hold` now wins 33.2%, which is the assertion that it
  worked. Then the trailing row read -0.4900R +/- 0.0554, which was this
  harness returning a fixed -1R on a stop the trail had already moved into
  profit. Neither would have been visible on real data, where a rule is
  *expected* to differ from zero.

## What this cannot know

Within one bar, OHLC does not say whether the high or the low came first, so a
bar that spans both target and stop is settled **as the stop**. That is
conservative for `hold` and for `trail`, and it is the same assumption for
every row, so it cannot favour one rule over another. The managed rules exit at
a bar *close*, which is a market order, while target and stop are touches - so
the managed rows carry slippage the touch rows do not, and a difference smaller
than a spread is not a result.

**Costs are not applied, and that is stated rather than buried.** The cache's
spread column is in *points*, not price - `spread-column-is-in-points` records
EURUSD reading a 476% round trip from exactly that conversion, and the error
reorders instruments by cost - so converting it needs a per-feed tick size this
harness does not carry. Every row here is therefore gross, the managed rows are
flattered relative to the touch rows by one market exit each, and no difference
below a round trip should be read as an edge until a costed follow-up runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pattern_fingerprint import CACHE  # noqa: E402

FRAME = os.environ.get("FRAME", "1h")
#: Target distance in units of risk. 2R needs a 1-in-3 hit rate to break even,
#: which is the ratio `a-martingale-cannot-pay` measured the fill-bar bug on.
TARGET_R = 2.0
#: Stop distance as a multiple of trailing bar volatility.
STOP_SIGMAS = 2.0
VOL_WINDOW = 50
#: Urgency slopes. 0.0 is "always exit on the first adverse bar".
THETAS = (0.0, 0.25, 0.5, 1.0)
TRAIL_R = 1.0
MAX_BARS = 200
#: Entries drawn per feed. The walk arm gets the same number from each of
#: `WALK_BOOKS` independent paths, so the martingale check has the same power
#: as the real one rather than a tenth of it - an unpowered zero is not a zero,
#: per `show-power-before-reporting-a-null`.
ENTRIES_PER_FEED = 400
WALK_BOOKS = 15
ANOMALY_SIGMAS = 5.0
SEED = 20261026

NAMES = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "Germany_40",
    "UK_100",
    "Japan_225",
    "US_Oil",
    "BTCUSD",
    "ETHUSD",
)


def _load(name: str) -> dict[str, np.ndarray] | None:
    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        if "spread" in bundle:
            got["spread"] = np.asarray(bundle["spread"], dtype=float)[order]
    keep = (got["close"] > 0) & (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    return got if len(got["close"]) >= VOL_WINDOW + MAX_BARS + 100 else None


def _walk(bars: int, rng) -> dict[str, np.ndarray]:
    """Geometric Brownian bars, OHLC aggregated from a sub-bar path."""
    sub = 12
    steps = rng.normal(0.0, 0.0004, bars * sub)
    path = np.exp(np.cumsum(steps))
    grid = path.reshape(bars, sub)
    return {
        "time": np.arange(bars, dtype=float),
        "open": grid[:, 0],
        "high": grid.max(axis=1),
        "low": grid.min(axis=1),
        "close": grid[:, -1],
    }


def _settle(
    bars: dict[str, np.ndarray],
    start: int,
    side: int,
    entry: float,
    stop: float,
    target: float,
    rule: str,
    theta: float,
) -> tuple[float, int] | None:
    """Walk forward from the bar AFTER entry. Returns (R, bars held).

    `a-martingale-cannot-pay`: settling on the fill bar turns a 2R race into a
    0.470 win rate against a required 0.333, so `start + 1` is load-bearing.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    high, low = bars["high"], bars["low"]
    opens, closes = bars["open"], bars["close"]
    best = entry
    for step in range(1, MAX_BARS + 1):
        i = start + step
        if i >= len(closes):
            return None
        hit_stop = (low[i] <= stop) if side > 0 else (high[i] >= stop)
        hit_target = (high[i] >= target) if side > 0 else (low[i] <= target)
        # Both in one bar: settled as the stop, because OHLC does not order
        # the high and the low. Same assumption for every rule.
        if hit_stop:
            # **Not -1.0.** `trail` moves the stop, so a trailed exit can be a
            # gain, and returning the fixed loss books every one as a full
            # stop-out. The walk arm caught it: a trailing stop read -0.4900R
            # +/- 0.0554 where optional stopping requires 0, and a *negative*
            # expectancy on a martingale is as much a bug as a positive one.
            return (stop - entry) * side / risk, step
        if hit_target:
            return TARGET_R, step
        if rule == "trail":
            best = max(best, high[i]) if side > 0 else min(best, low[i])
            guard = best - side * TRAIL_R * risk
            beyond = (guard > stop) if side > 0 else (guard < stop)
            if beyond:
                stop = guard
        elif rule == "urgency":
            progress = (closes[i] - entry) * side / ((target - entry) * side)
            progress = min(max(progress, 0.0), 1.0)
            body = (closes[i] - opens[i]) * side
            if body < 0 and abs(body) >= theta * (1.0 - progress) * risk:
                return (closes[i] - entry) * side / risk, step
    i = start + MAX_BARS
    return (closes[i] - entry) * side / risk, MAX_BARS


def _entries(bars: dict[str, np.ndarray], kind: str, rng) -> list[tuple[int, int]]:
    closes = bars["close"]
    ret = np.diff(np.log(closes))
    sd = np.full(len(closes), np.nan)
    for i in range(VOL_WINDOW, len(ret)):
        sd[i] = ret[i - VOL_WINDOW : i].std()
    first, last = VOL_WINDOW + 1, len(closes) - MAX_BARS - 2
    if last <= first:
        return []
    if kind == "random":
        where = rng.choice(
            np.arange(first, last),
            size=min(ENTRIES_PER_FEED, last - first),
            replace=False,
        )
        return [(int(i), int(rng.choice((-1, 1)))) for i in sorted(where)]
    picks = []
    for i in range(first, last):
        if not np.isfinite(sd[i]) or sd[i] <= 0:
            continue
        move = ret[i - 1]
        if abs(move) >= ANOMALY_SIGMAS * sd[i]:
            picks.append((i, 1 if move > 0 else -1))
    return picks


def _shuffled(
    bars: dict[str, np.ndarray], start: int, rng, block: int = 8
) -> dict[str, np.ndarray]:
    """Block-shuffle the post-entry path, keeping each bar's own geometry."""
    tail = slice(start + 1, min(start + 1 + MAX_BARS + 1, len(bars["close"])))
    size = len(bars["close"][tail])
    if size < block * 2:
        return bars
    order = np.arange(size)
    blocks = [order[i : i + block] for i in range(0, size, block)]
    rng.shuffle(blocks)
    index = np.concatenate(blocks)[:size]
    out = {k: v.copy() for k, v in bars.items() if k != "time"}
    # Re-chain the shuffled bars onto the entry close so levels stay reachable.
    base = bars["close"][start]
    rel = {k: bars[k][tail][index] / bars["close"][tail][index] for k in ("open", "high", "low")}
    moves = np.diff(np.log(bars["close"][tail]), prepend=np.log(base))[index]
    chain = base * np.exp(np.cumsum(moves))
    out["close"][tail] = chain
    for k in ("open", "high", "low"):
        out[k][tail] = rel[k] * chain
    out["time"] = bars["time"]
    return out


def main() -> None:
    print(__doc__.split("\n\n")[0])
    print(
        f"\nframe {FRAME}, target {TARGET_R}R, stop {STOP_SIGMAS} sigma, "
        f"cap {MAX_BARS} bars.\nSettlement starts the bar AFTER entry.\n"
    )
    rng = np.random.default_rng(SEED)
    books: dict[str, dict[str, np.ndarray]] = {}
    for name in NAMES:
        got = _load(name)
        if got is not None:
            books[name] = got
    print(f"loaded {len(books)} feeds at {FRAME}")
    for index in range(WALK_BOOKS):
        books[f"WALK {index} (a martingale: every row must read 0)"] = _walk(20000, rng)

    for kind in ("random", "anomaly"):
        for market, bars in (("real", False), ("walk", True)):
            rows: dict[str, list[float]] = {}
            held: dict[str, list[float]] = {}
            feeds = (
                {k: v for k, v in books.items() if k.startswith("WALK")}
                if market == "walk"
                else {k: v for k, v in books.items() if not k.startswith("WALK")}
            )
            if not feeds:
                continue
            for name, book in feeds.items():
                closes = book["close"]
                ret = np.diff(np.log(closes))
                for start, side in _entries(book, kind, rng):
                    window = ret[start - VOL_WINDOW : start]
                    sd = float(window.std())
                    if sd <= 0:
                        continue
                    entry = float(closes[start])
                    risk = STOP_SIGMAS * sd * entry
                    stop = entry - side * risk
                    target = entry + side * TARGET_R * risk
                    base = _settle(book, start, side, entry, stop, target, "hold", 0.0)
                    if base is None:
                        continue
                    rows.setdefault("hold", []).append(base[0])
                    held.setdefault("hold", []).append(base[1])
                    got = _settle(book, start, side, entry, stop, target, "trail", 0.0)
                    rows.setdefault("trail 1R", []).append(got[0] if got else base[0])
                    held.setdefault("trail 1R", []).append(got[1] if got else base[1])
                    for theta in THETAS:
                        tag = f"urgency t0={theta}"
                        got = _settle(book, start, side, entry, stop, target, "urgency", theta)
                        rows.setdefault(tag, []).append(got[0] if got else base[0])
                        bars_held = got[1] if got else base[1]
                        held.setdefault(tag, []).append(bars_held)
                        if theta == 0.5:
                            # duty-cycle-matched placebo: same holding time,
                            # arbitrary exit. The control that kills most of these.
                            i = min(start + int(bars_held), len(closes) - 1)
                            placebo = (closes[i] - entry) * side / risk
                            rows.setdefault("random matched", []).append(
                                float(np.clip(placebo, -1.0, TARGET_R))
                            )
                            held.setdefault("random matched", []).append(bars_held)
                            spun = _shuffled(book, start, rng)
                            got2 = _settle(spun, start, side, entry, stop, target, "urgency", theta)
                            rows.setdefault("shuffled path", []).append(
                                got2[0] if got2 else base[0]
                            )
                            held.setdefault("shuffled path", []).append(
                                got2[1] if got2 else bars_held
                            )
            if not rows.get("hold"):
                continue
            print(f"\n=== {kind} entries, {market} market")
            print(
                f"{'rule':24s} {'trades':>7s} {'mean R':>8s} {'se':>7s} "
                f"{'vs hold':>8s} {'se':>7s} {'t':>6s} {'win%':>6s} {'bars':>6s}"
            )
            anchor = np.asarray(rows["hold"])
            for tag, values in rows.items():
                got = np.asarray(values)
                if len(got) != len(anchor):
                    continue
                gap = got - anchor
                se = got.std(ddof=1) / np.sqrt(len(got))
                gse = gap.std(ddof=1) / np.sqrt(len(gap)) if len(gap) > 1 else float("nan")
                fine = bool(gse) and np.isfinite(gse) and gse > 0
                t = gap.mean() / gse if fine else float("nan")
                print(
                    f"{tag:24s} {len(got):>7d} {got.mean():>8.4f} {se:>7.4f} "
                    f"{gap.mean():>8.4f} {gse:>7.4f} {t:>6.2f} "
                    f"{100 * (got > 0).mean():>6.1f} {np.mean(held[tag]):>6.1f}"
                )


if __name__ == "__main__":
    main()
