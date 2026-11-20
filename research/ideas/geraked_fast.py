"""The 13 EAs at 5 minutes, and over short windows beside their shuffled twins.

[`geraked-eas.md`](../docs/geraked-eas.md) measured every EA of
`github.com/geraked/metatrader5` (MIT) across **441 EA x class x timeframe
cells**, pre-registered, and closed them: 12 of 13 lose 0.02-0.09R a trade in
Mode S, `P(N R)` sits on `1/(N+1)` and on matched walks at every N, and the
author's best-looking equity curve has a random-walk twin that looks better.

**Two things that study did not do**, and this does:

1. **Five minutes.** Its data section reads "15m, 1h, 4h and 1d". `SEC` in
   `geraked_eas.py` defines 5m and `TFS` excludes it, so the clock below the
   study's floor was never measured for these signals.
2. **Short windows, each beside its own shuffled twin.** The operator asked for
   2 years, 3 months and 7 days. The last two are order statistics and the
   twin is how that is made visible rather than argued:
   [`rsi-ma-momentum.md`](../docs/rsi-ma-momentum.md) measured a 414-cell grid
   over 7 days whose leaders read +0.24 to +0.32R, where **0 of the top 10 was
   positive in the prior 30 days** and a **day-shuffled market's best cell beat
   the real market's** (+0.5679R against +0.3171R at 15m).

**The signal definitions are imported, not re-implemented.** They are frozen
and pre-registered; a second copy that drifts would make the two studies
disagree for a reason that is not the market. Only the data path and the
windowing are new.

Why the deep catalogue rather than the study's database: `prices.db` is a
snapshot ending **2026-08-26** holding **19 days** of 5m and 14 of 1m, so it
can answer neither "the last 7 days" nor two years of 5m. The deep catalogue is
**native 5-minute, eight years, ending 2026-11-12**. One minute remains
unmeasurable here, and is reported as that rather than approximated.

Run as:

    uv run python research/ideas/geraked_fast.py --frames 5m,15m --windows 730,90,7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from geraked_eas import SIGNALS, Bars  # noqa: E402
from reactive_zones import CATALOGUE, atr, fold, load, shuffled, window  # noqa: E402
from rsi_momentum import SPREADS, SYMBOLS  # noqa: E402

DAY = 86_400_000_000_000


def bars_for(series, point: float) -> Bars:
    """The study's own `Bars`, built from a deep-catalogue `Candles`."""
    return Bars(
        o=np.asarray(series.open, float),
        h=np.asarray(series.high, float),
        l=np.asarray(series.low, float),
        c=np.asarray(series.close, float),
        ts=np.asarray(series.ts, float) / 1e9,
        point=point,
    )


def race(bars: Bars, signal: dict, patience: int, cost: float) -> tuple[np.ndarray, int]:
    """Mode S, simplified: the EA's own stop, a target at `tpcoef` times it.

    Entry at the **next bar's open**, which is what the signal dict means by
    bar `t` - `Bars.on` exists for exactly that and the study is explicit about
    it. One position at a time, so no two outcomes share bars.
    """
    buy, sell = signal["buy"], signal["sell"]
    sl_buy, sl_sell = signal["sl_buy"], signal["sl_sell"]
    coef = float(signal.get("tpcoef") or 0.0)
    n = bars.c.size
    out: list[float] = []
    fired = np.flatnonzero(buy | sell)
    at = 0
    while at < fired.size:
        i = int(fired[at])
        if i >= n - 2:
            break
        up = bool(buy[i])
        entry = float(bars.on[i])
        stop = float(sl_buy[i] if up else sl_sell[i])
        risk = abs(entry - stop)
        if not np.isfinite(risk) or risk <= 0:
            at += 1
            continue
        target = entry + coef * risk if up else entry - coef * risk
        done = None
        last = min(n, i + 2 + patience)
        for j in range(i + 1, last):
            stopped = bars.l[j] <= stop if up else bars.h[j] >= stop
            made = (bars.h[j] >= target if up else bars.l[j] <= target) if coef > 0 else False
            if stopped:
                done = -1.0
                break
            if made:
                done = coef
                break
        if done is None:
            j = last - 1
            done = (float(bars.c[j]) - entry) * (1.0 if up else -1.0) / risk
        out.append(done - cost / risk)
        at = int(np.searchsorted(fired, j + 1))
    return np.asarray(out), len(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--frames", default="5m,15m")
    parser.add_argument("--windows", default="730,90,7", help="window lengths in days")
    parser.add_argument("--eas", default="", help="a subset, else all 12 bar EAs")
    parser.add_argument("--patience", type=int, default=96)
    parser.add_argument("--least", type=int, default=20)
    parser.add_argument("--show", type=int, default=8)
    args = parser.parse_args()

    wanted = [e.strip() for e in args.eas.split(",") if e.strip()] or sorted(SIGNALS)
    print(
        f"{len(wanted)} EAs  frames {args.frames}  windows {args.windows}d  "
        f"patience {args.patience}  minimum {args.least} trades"
    )
    for frame in (f.strip() for f in args.frames.split(",") if f.strip()):
        for days in (float(d) for d in args.windows.split(",") if d.strip()):
            rows: dict[tuple[str, str], list[np.ndarray]] = {}
            for symbol in (s for s in args.symbols.split(",") if s):
                base = load(Path(args.catalogue), symbol)
                points, tick = SPREADS[symbol]
                cost = points * tick
                for arm in ("real", "shuffled"):
                    series = shuffled(base, seed=23) if arm == "shuffled" else base
                    series = window(series, days / 365.25)
                    folded = series if frame == args.unit else fold(series, frame, unit=args.unit)
                    if len(folded) < 400:
                        continue
                    bars = bars_for(folded, tick)
                    for name in wanted:
                        try:
                            signal = SIGNALS[name](bars)
                        except Exception:
                            continue
                        got, n = race(bars, signal, args.patience, cost)
                        if n >= args.least:
                            rows.setdefault((name, arm), []).append(got)
            if not rows:
                print(f"\n  {frame}, {days:g}d: nothing reached {args.least} trades")
                continue
            scored = []
            for (name, arm), parts in rows.items():
                if arm != "real":
                    continue
                mine = np.concatenate(parts)
                twin = rows.get((name, "shuffled"))
                other = np.concatenate(twin) if twin else np.asarray([])
                scored.append((float(mine.mean()), name, mine.size, other))
            scored.sort(reverse=True)
            best_twin = max(
                (float(np.concatenate(p).mean()) for (n, a), p in rows.items() if a == "shuffled"),
                default=float("nan"),
            )
            print(f"\n  {frame}, last {days:g} days - {len(scored)} EAs with enough trades")
            print("    EA            trades    net R      sd    shuffled twin")
            for mean, name, n, other in scored[: args.show]:
                twin = f"{other.mean():+.4f}" if other.size else "   thin"
                mine = np.concatenate(rows[(name, "real")])
                print(f"    {name:<12} {n:>7,}  {mean:+.4f}  {mine.std():.3f}      {twin}")
            print(
                f"    best real {scored[0][0]:+.4f} against the best shuffled "
                f"{best_twin:+.4f}  -> {'real leads' if scored[0][0] > best_twin else 'THE SHUFFLE WINS'}"
            )


if __name__ == "__main__":
    main()
