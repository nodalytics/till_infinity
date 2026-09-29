"""Game theory at the chart: are the levels everyone watches self-fulfilling, or hunted?

A price level that many traders watch is a Schelling focal point: orders collect there because
everyone expects everyone else's to. Two published forms of it are testable:
  Osler (2003, "Currency orders and exchange rate dynamics"): take-profit orders cluster AT round
  numbers, so trends tend to reverse there; stop-loss orders cluster just BEYOND them, so once a
  round number is crossed the move tends to accelerate (a stop cascade).
  The stop hunt: price pokes just beyond a widely watched extreme (yesterday's high or low),
  triggers the stops resting there, and comes back - the "liquidity sweep".

Levels, per series (the lab's broker 15m bars):
  round        the big figure, a step of 10^(floor(log10 price) - 2) - 1.1000 on EURUSD, 150.00 on
               USDJPY, $10 on gold, $100 on BTC - and the half figure between them
  placebo      the same grid shifted by a random 20-80% of a step: as many levels, the same spacing,
               nobody watching
  prior day    yesterday's UTC high and low; placebo: yesterday's high/low shifted by a random
               0.5-1.5 baseline moves
Every UTC day, each level's first touch is followed (price was at least a baseline move away at the
day's open). All units are the trailing baseline move (sigma).
  bounce     from the touch, one sigma back the way it came before one sigma through, within 1h
             (a bar reaching both = through)
  cascade    once a 15m close is half a sigma beyond the level, one more sigma onward before price
             returns to the level, within 1h
  sweep      a bar trades beyond the level by up to one sigma and closes back on the near side; then
             does price reach one sigma further back before a new extreme beyond the bar's, within 1h
Each is compared with its placebo on the same series. The random walks (Deriv Volatility indices)
have round numbers too, and nobody places orders at them, so they are the control for the
arithmetic. Reported on each series' last 40% by time, with halves.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

RNG = np.random.default_rng(29)
H = 4  # 1h of 15m bars


def race(lh, ll, i, up, dn):
    """+1 if `up` is reached first, -1 if `dn`, 0 neither, over bars i+1..i+H; a bar with both = -1."""
    for j in range(i + 1, min(i + 1 + H, len(lh))):
        a, b = lh[j] >= up, ll[j] <= dn
        if a and b:
            return -1
        if a:
            return 1
        if b:
            return -1
    return 0


def series_events(sym, test_frac=0.6):
    df = spikerisk.load(None, sym, "SEQLAB", "15m")
    t = pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True)
    lh, ll, lc = (np.log(df[k].to_numpy()) for k in ("high", "low", "close"))
    price = df["close"].to_numpy()
    r = np.diff(lc, prepend=np.nan)
    sig = pd.Series(np.abs(r)).shift(1).rolling(500, min_periods=250).mean().to_numpy()
    day = t.floor("1D")
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    n0 = int(test_frac * len(lc))
    half_at = int(0.8 * len(lc))
    step = 10.0 ** (np.floor(np.log10(np.nanmedian(price))) - 2)
    shift = RNG.uniform(0.2, 0.8)
    rows = []
    for si, s in enumerate(starts):
        e = starts[si + 1] if si + 1 < len(starts) else len(lc)
        if s < n0 or si == 0 or not np.isfinite(sig[s]):
            continue
        p0 = price[s]
        grid = np.arange(np.floor(p0 / step) - 3, np.floor(p0 / step) + 4) * step
        halves = grid + step / 2
        ps, pe = starts[si - 1], s
        yh, yl = np.log(df["high"].to_numpy()[ps:pe].max()), np.log(df["low"].to_numpy()[ps:pe].min())
        jig = RNG.uniform(0.5, 1.5) * sig[s] * RNG.choice([-1, 1])
        levels = ([("round", np.log(x)) for x in grid] + [("half", np.log(x)) for x in halves]
                  + [("round placebo", np.log(x + shift * step)) for x in grid]
                  + [("prior day", yh), ("prior day", yl), ("prior day placebo", yh + jig), ("prior day placebo", yl + jig)])
        for kind, L in levels:
            if abs(lc[s - 1] - L) < sig[s]:
                continue
            side = 1.0 if lc[s - 1] > L else -1.0  # from above: a floor being tested
            u = sig[s]
            for i in range(s, min(e, len(lc) - H - 1)):
                if ll[i] <= L <= lh[i]:
                    # bounce
                    res = race(lh, ll, i, L + u, L - u) if side > 0 else -race(lh, ll, i, L + u, L - u)
                    # sweep: poked beyond by <= 1 sigma, closed back on the near side
                    beyond = (L - ll[i]) if side > 0 else (lh[i] - L)
                    swept = 0 < beyond <= u and ((lc[i] > L) if side > 0 else (lc[i] < L))
                    sw = np.nan
                    if swept:
                        ext = ll[i] if side > 0 else lh[i]
                        back = (L + u) if side > 0 else (L - u)
                        o = race(lh, ll, i, back, ext) if side > 0 else -race(lh, ll, i, ext, back)
                        sw = o
                    # cascade: the first later close half a sigma through, then one more sigma onward
                    cas = np.nan
                    for j in range(i, min(e, len(lc) - H - 1)):
                        through = (L - lc[j]) if side > 0 else (lc[j] - L)
                        if through >= 0.5 * u:
                            onward = (lc[j] - u) if side > 0 else (lc[j] + u)
                            o = race(lh, ll, j, L, onward) if side > 0 else race(lh, ll, j, onward, L)
                            cas = -o if side > 0 else o  # +1 = accelerated onward, -1 = came back to the level
                            break
                    rows.append(dict(sym=sym, kind=kind, bounce=res, sweep=sw, cascade=cas, half=i >= half_at))
                    break
    return rows


def main():
    groups = {"fx": FAMILIES["fx"], "metals": FAMILIES["metal"], "crypto": FAMILIES["crypto"],
              "random walks": ["Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index",
                               "Volatility_75_Index", "Volatility_100_Index"]}
    print(f"\n{'=' * 110}\nFOCAL POINTS - 15m, first touch per level per day, test block (last 40% by time); +-1 sigma races within 1h")
    for name, syms in groups.items():
        rows = []
        for s in syms:
            try:
                rows += series_events(s)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {s}: {str(exc)[:60]}")
        d = pd.DataFrame(rows)
        print(f"\n  {name}: {len(d):,} touches")
        for kind in ("round", "half", "round placebo", "prior day", "prior day placebo"):
            k = d[d["kind"] == kind]
            if not len(k):
                continue
            cells = []
            for col, lab in (("bounce", "bounce"), ("cascade", "accelerates after crossing"), ("sweep", "sweep reverses")):
                x = k[col].dropna()
                x = x[x != 0]
                if len(x) < 20:
                    cells.append(f"{lab} n/a")
                    continue
                p = np.mean(x > 0)
                h = [np.mean(x[k.loc[x.index, 'half'] == v] > 0) for v in (False, True)]
                cells.append(f"{lab} {p:.1%} +- {np.sqrt(p * (1 - p) / len(x)):.1%} (n={len(x)}, halves {h[0]:.1%}/{h[1]:.1%})")
            print(f"    {kind:<18} " + " | ".join(cells))


if __name__ == "__main__":
    main()
