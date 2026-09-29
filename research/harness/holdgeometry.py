"""Why a random walk "holds" at a level 87% of the time: the resolution rule, not the volatility unit.

`skill.md` found the production engine calls levels held 88.6% of the time on real markets and 87.3%
on exact random walks. Is that the volatility normalisation, or the rule itself? The rule, from
`structures/reactions.py` (`Tracker.update`), for price arriving from above:
  reject    price comes back RESOLVE_VOL (1.5) above the ORIGIN - the deepest close of the leg in,
            which follows price down until the leg turns (ARRIVAL_RUN_VOL 0.5 off the low)
  break     price closes RESOLVE_VOL beyond the LEVEL, provisionally; if within `trap_bars` (6) it
            comes back TRAP_VOL (0.5) above the level, it is a TRAP instead - and the break model
            and the direction label both count a trap as the level holding
  chop      neither within HORIZON_BARS (12)
Rejection is measured from a point that moves with price, and a break from a point that does not,
then has to survive a trap window. Both favour "held" on any path.

Simulated here on a pure Gaussian random walk (one step per bar, true sigma 1), arriving at the zone
edge w volatility units above the level, with the volatility unit deliberately mis-estimated at
0.5x, 1x and 2x the truth. Four rules:
  production    as above
  no trap       a break is final the moment it is 1.5 through
  fixed origin  rejection measured from the entry, not the running low (traps kept)
  symmetric     +-1.5 from the entry, no trap: the fair race
"""
from __future__ import annotations

import numpy as np

RNG = np.random.default_rng(41)
N, RESOLVE, TRAP, TRAP_BARS, HORIZON, TURN = 200_000, 1.5, 0.5, 6, 12, 0.5


def resolve(path, w, u, rule):
    """Outcome of one touch: 'reject', 'trap', 'break' or 'chop'. `path` is the price after each bar, in
    true sigmas, starting from the entry at w*u above the level (the level is 0)."""
    entry = w * u
    origin, turned, broke = entry, False, None
    for k, p in enumerate(path, start=1):
        if rule != "fixed origin" and not turned:
            if p <= origin:
                origin = p
            elif (p - origin) >= TURN * u:
                turned = True
        if broke is not None:
            if p / u >= TRAP:
                return "trap"
            if k - broke >= TRAP_BARS:
                return "break"
            continue
        if rule == "symmetric":
            if p - entry >= RESOLVE * u:
                return "reject"
            if entry - p >= RESOLVE * u:
                return "break"
        else:
            if (p - origin) / u >= RESOLVE:
                return "reject"
            if -p / u >= RESOLVE:
                if rule == "no trap":
                    return "break"
                broke = k
        if k >= HORIZON and broke is None:
            return "chop"
    return "break" if broke is not None else "chop"


def main():
    steps = RNG.standard_normal((N, HORIZON + TRAP_BARS + 2)).cumsum(axis=1)
    print(f"\n{'=' * 100}\nHOLD GEOMETRY - {N:,} touches on a Gaussian random walk; held = reject + trap, as the break model counts")
    for w in (0.35, 0.75):
        print(f"\n  arriving {w} volatility units above the level (the zone edge)")
        for rule in ("production", "no trap", "fixed origin", "symmetric"):
            cells = []
            for u in (0.5, 1.0, 2.0):
                out = [resolve(w * u + steps[i], w, u, rule) for i in range(N)]
                vals, counts = np.unique(out, return_counts=True)
                c = dict(zip(vals, counts))
                held = c.get("reject", 0) + c.get("trap", 0)
                decided = held + c.get("break", 0)
                cells.append(f"vol unit {u:.1f}x: held {held / decided:.1%} (traps {c.get('trap', 0) / decided:.1%}, "
                             f"chop {c.get('chop', 0) / N:.1%})")
            print(f"    {rule:<13} " + " | ".join(cells))


if __name__ == "__main__":
    main()
