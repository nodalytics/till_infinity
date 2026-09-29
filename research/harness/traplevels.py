"""After a trap, is the new extreme (or the adjusted level) a better level than the old one?

A trap (`structures/reactions.py`) is a break that failed: price closed RESOLVE_VOL (1.5) through the
level, then within TRAP_BARS (6) came back TRAP_VOL (0.5) on the original side. Today the level is
kept as it was (`levels.Level.record`: "a trap is the level holding"), nudged only by the touch's
origin, and the trap's extreme - where the stops were run and the move turned - is not a level at
all. The suggestion: label that extreme, or an adjusted level, as the level from now on.

Measured with a label that cannot flatter anyone: every retest is a symmetric race of +-1 sigma from
the level (up first = held, for support), which reads 50% on a random walk whatever the geometry.
Candidates after each trap, at their first retest within the next 96 bars:
  extreme    the trap's lowest low (for a support)
  original   the level that was trapped
  adjusted   halfway between them
  placebo    a random price in the same span [extreme - 1 sigma, original + 1 sigma], at least 0.3 sigma
             from all three
Also the entry the trap itself suggests: from the close that confirms it, +-1 sigma, fading the
failed break. And for comparison, a completed break's retest from the other side (the flip).

Levels are 5-bar swing lows and highs (highs mirrored), sigma is the trailing mean |bar return| x 1.25
(about a bar's standard deviation, the production unit), on the lab's broker bars at 15m and 1h, 15
FX pairs, XAU, XAG, BTC, ETH, SOL; five random walks as the control. Halves by time.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

RNG = np.random.default_rng(43)
RESOLVE, TRAP, TRAP_BARS, WING, FOLLOW, LIFE = 1.5, 0.5, 6, 5, 96, 500


def race(lh, ll, i, up, dn, span=FOLLOW):
    for j in range(i + 1, min(i + 1 + span, len(lh))):
        a, b = lh[j] >= up, ll[j] <= dn
        if a and b:
            return 0  # undecidable inside one bar: dropped rather than scored either way
        if a:
            return 1
        if b:
            return -1
    return 0


def retest(lh, ll, lc, start, level, sig):
    """First bar after `start` whose low reaches `level` from above, then the symmetric race."""
    for i in range(start + 1, min(start + 1 + FOLLOW, len(lc))):
        if ll[i] <= level:
            if lc[i - 1] < level:  # already below: not a touch from above
                return 0
            return race(lh, ll, i, level + sig, level - sig)
    return 0


def supports(lh, ll, lc, sig, half_at, rows, label):
    n = len(lc)
    for p in range(WING, n - WING):
        if ll[p] != ll[p - WING:p + WING + 1].min() or not np.isfinite(sig[p]):
            continue
        L, s = ll[p], sig[p]
        for k in range(p + WING, min(p + WING + LIFE, n - TRAP_BARS - 2)):
            if lc[k] <= L - RESOLVE * s:  # a break starts
                trapped = None
                for j in range(k + 1, k + 1 + TRAP_BARS):
                    if lc[j] >= L + TRAP * s:
                        trapped = j
                        break
                h = k >= half_at
                if trapped is not None:
                    j = trapped
                    E = ll[k:j + 1].min()
                    A = 0.5 * (L + E)
                    lo, hi = E - s, L + s
                    pl = None
                    for _ in range(50):
                        x = RNG.uniform(lo, hi)
                        if min(abs(x - L), abs(x - E), abs(x - A)) >= 0.3 * s:
                            pl = x
                            break
                    rec = dict(kind=label, event="trap", half=h,
                               extreme=retest(lh, ll, lc, j, E, s), original=retest(lh, ll, lc, j, L, s),
                               adjusted=retest(lh, ll, lc, j, A, s),
                               placebo=retest(lh, ll, lc, j, pl, s) if pl is not None else 0,
                               fade=race(lh, ll, j, lc[j] + s, lc[j] - s))
                else:
                    j = k + TRAP_BARS
                    # a completed break: does the old support now resist from below? (-1 = held as resistance)
                    flip = 0
                    for i in range(j + 1, min(j + 1 + FOLLOW, n)):
                        if lh[i] >= L:
                            if lc[i - 1] > L:
                                break
                            flip = -race(lh, ll, i, L + s, L - s)
                            break
                    rec = dict(kind=label, event="break", half=h, flip=flip)
                rows.append(rec)
                break
            if lc[k] > L + 20 * s:
                break


def main():
    groups = {"fx": FAMILIES["fx"], "metals": FAMILIES["metal"], "crypto": FAMILIES["crypto"],
              "random walks": ["Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index",
                               "Volatility_75_Index", "Volatility_100_Index"]}
    for interval in ("15m", "1h"):
        print(f"\n{'=' * 110}\nTRAP LEVELS {interval} - symmetric +-1 sigma race at the first retest within {FOLLOW} bars; held = the level "
              "stopped price (50% on a random walk)")
        for name, syms in groups.items():
            rows = []
            for sym in syms:
                try:
                    df = spikerisk.load(None, sym, "SEQLAB", interval)
                except (ValueError, FileNotFoundError) as exc:
                    print(f"  skip {sym}: {str(exc)[:60]}")
                    continue
                lh, ll, lc = (np.log(df[k].to_numpy()) for k in ("high", "low", "close"))
                sig = 1.25 * pd.Series(np.abs(np.diff(lc, prepend=np.nan))).shift(1).rolling(500, min_periods=250).mean().to_numpy()
                half_at = int(0.5 * len(lc))
                supports(lh, ll, lc, sig, half_at, rows, "support")
                supports(-ll, -lh, -lc, sig, half_at, rows, "resistance")  # highs, mirrored
            d = pd.DataFrame(rows)
            traps, breaks = d[d["event"] == "trap"], d[d["event"] == "break"]
            print(f"\n  {name}: {len(traps):,} traps, {len(breaks):,} completed breaks (trap share {len(traps) / max(len(d), 1):.1%})")
            for col, lab in (("extreme", "new extreme"), ("original", "original level"), ("adjusted", "adjusted (midpoint)"),
                             ("placebo", "placebo"), ("fade", "fade at confirmation")):
                x = traps[col]
                decided = x[x != 0]
                if len(decided) < 20:
                    print(f"    {lab:<22} n/a")
                    continue
                p = np.mean(decided > 0)
                hh = [np.mean(decided[traps.loc[decided.index, 'half'] == v] > 0) for v in (False, True)]
                print(f"    {lab:<22} held {p:.1%} +- {np.sqrt(p * (1 - p) / len(decided)):.1%} (n={len(decided):,}, "
                      f"halves {hh[0]:.1%}/{hh[1]:.1%}, retested {len(decided) / len(traps):.0%})")
            x = breaks["flip"]
            decided = x[x != 0]
            if len(decided) >= 20:
                p = np.mean(decided > 0)
                print(f"    {'after a real break, flip':<22} held {p:.1%} +- {np.sqrt(p * (1 - p) / len(decided)):.1%} (n={len(decided):,})")


if __name__ == "__main__":
    main()
