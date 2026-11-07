"""The triangle residual at M15: does a finer clock buy back executability?

`statespace-exploiting-relationships.md` measured the identity residual as
**real and not tradeable**: identity-specific, 112x its non-identity controls,
`p = 0.0050` at the floor of 200 nulls, individual legs reaching `t = +7.43` -
and then

    delay 0  +2.1626   not executable: the close the deviation is seen at
    delay 1  +0.7679   short of its own round trip
    delay 2  +0.0320   gone

The deviation's lifetime is about **two hours**. On the hourly-ish clock that
measurement used, a one-bar delay burns half of it, which is the whole of the
collapse from 2.16 to 0.77. At **M15 a bar is an eighth of the lifetime**, so
the same executable delay should cost 12.5% rather than 50%.

M1 would have been the clean test - a bar is 0.8% of the lifetime - and the
data refuses it: the broker serves 5,000 M1 bars, ten of the twenty-eight legs
are sparse, and every triangle touching one collapses to **1,315 common bars**,
about 22 hours, with one usable triangle. At M15 all 21 triangles carry
19,955-20,000 common bars at 99.8-100% coverage over 290 days.

  ./.secrets/lab.sh run research/harness/identity_m15.py \
      FX=$HOME/till_infinity/data/fx OMP_NUM_THREADS=1

## Pre-specified, because searching this already failed once

The original records that **maximising the search slice is worse than not
searching**: it found `|z| > 6, h = 240` at `p = 0.488` while the aggregate
pointed elsewhere. So every number below is fixed from the mechanism before
the run - thresholds, horizons and delays - and the whole grid is reported
rather than its best corner.

## One leg, one spread

Converting the relationship into a directional bet means trading a **single
leg**, so the cost is that leg's own round trip and not the basket's. Charging
three spreads would make a real effect look like it missed a cost it never
paid. This is the original's choice and it is kept.

## The control

**Non-identity triples**: three symbols with no arithmetic reason to compose.
If those read like the identities, the effect is in the measurement.
"""

from __future__ import annotations

import glob
import itertools
import os
import statistics as st
from pathlib import Path

import numpy as np

FX = Path(os.environ.get("FX", str(Path.home() / "till_infinity/data/fx")))
TF = os.environ.get("TF", "M15")
CCY = ("EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD")
#: The z-score's lookback, in bars. Five days at M15.
WINDOW = 480
#: **Matched to the original in TIME, not in bars.** Its horizons are 1, 3, 6
#: and 24 *hours* and its strongest rows sit at **h = 24** (`EURUSD +24.337`,
#: `t = +3.79`). The first cut of this file read "reversion is fastest at 1 to
#: 6 bars" as 1 to 6 M15 bars and used holds of 4, 8, 16 - one, two and four
#: hours - truncating the horizon by six to twenty-four times and measuring a
#: window the signal mostly lives outside. It returned -0.03 at every delay
#: and looked like a refutation of a result that reproduces to four decimal
#: places. The lesson is narrow and expensive: a horizon is a duration, and
#: porting one between clocks means converting it.
HOLDS = (4, 12, 24, 96)
ZS = (2.0, 3.0, 4.0)
DELAYS = (0, 1, 2, 3)
MIN_BARS = 5_000
#: Non-identity triples drawn for the control arm.
CONTROLS = 60


def load() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in glob.glob(str(FX / f"*.{TF}.npz")):
        name = os.path.basename(f).split(".")[0]
        z = np.load(f)
        if len(z["close"]) < MIN_BARS:
            continue
        out[name] = {
            "time": z["time"].astype(np.int64),
            "close": z["close"].astype(np.float64),
            "spread": z["spread"].astype(np.float64),
        }
    return out


def point_of(close: np.ndarray) -> float:
    d = np.abs(np.diff(np.unique(close)))
    d = d[d > 0]
    return float(np.min(d)) if d.size else 0.0


def align(legs: list[dict]) -> list[np.ndarray] | None:
    """Common timestamps across the legs, as index arrays.

    **Aligned before anything is differenced.** Aligning returns only the
    shared stamps, so differencing afterwards turns every gap into a fake
    one-bar return. The residual here is contemporaneous - a ratio of three
    prices at one stamp - so nothing is differenced across a gap at all.
    """
    common = set(legs[0]["time"])
    for leg in legs[1:]:
        common &= set(leg["time"])
    if len(common) < MIN_BARS:
        return None
    keep = np.array(sorted(common))
    return [np.searchsorted(leg["time"], keep) for leg in legs]


def rate(name: str, want: tuple[str, str], price: np.ndarray) -> np.ndarray:
    """`price` oriented as units of `want[1]` per one `want[0]`."""
    base, quote = name[:3], name[3:]
    if (base, quote) == want:
        return price
    if (quote, base) == want:
        return 1.0 / price
    raise ValueError(f"{name} is not {want}")


def residual(a: str, b: str, legs: dict[str, np.ndarray]) -> np.ndarray:
    """`log(actual cross) - log(implied)`, contemporaneous.

    `implied = rate(a->USD) * rate(USD->b)`, which is `b` per `a` - the same
    thing the cross quotes, whichever way round the venue names it.
    """
    au = legs["au_name"]
    bu = legs["bu_name"]
    cr = legs["cr_name"]
    a_usd = rate(au, (a, "USD"), legs["au"])
    usd_b = rate(bu, ("USD", b), legs["bu"])
    actual = rate(cr, (a, b), legs["cr"])
    implied = a_usd * usd_b
    ok = (actual > 0) & (implied > 0)
    out = np.full(len(actual), np.nan)
    out[ok] = np.log(actual[ok]) - np.log(implied[ok])
    return out


def rolling_z(x: np.ndarray, window: int) -> np.ndarray:
    """Trailing z, using only bars strictly before each point."""
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(window, n):
        past = x[i - window : i]
        good = past[np.isfinite(past)]
        if len(good) < window // 2:
            continue
        sd = float(np.std(good))
        if sd <= 0:
            continue
        out[i] = (x[i] - float(np.mean(good))) / sd
    return out


def score(
    res: np.ndarray, z: np.ndarray, leg: np.ndarray, spread: np.ndarray, point: float,
    sign: float, thresh: float, hold: int, delay: int,
) -> tuple[int, float] | None:
    """Mean signed log return over `hold`, as a multiple of one round trip.

    `sign` is +1 where the leg must rise to close a positive residual and -1
    where it must fall. A positive residual means the cross is rich against its
    implied, so the bet is that the gap closes - and the direction on each leg
    follows from the arithmetic, not from a fit.
    """
    n = len(leg)
    fired = np.where(np.isfinite(z) & (np.abs(z) >= thresh))[0]
    fired = fired[(fired + delay + hold) < n]
    if len(fired) < 50:
        return None
    #: The round trip on the traded leg, in log terms.
    px = leg[fired + delay]
    cost = 2.0 * spread[fired + delay] * point / np.maximum(px, 1e-12)
    cost = float(np.median(cost[np.isfinite(cost)]))
    if cost <= 0:
        return None
    entry = leg[fired + delay]
    exit_ = leg[fired + delay + hold]
    move = np.log(np.maximum(exit_, 1e-12)) - np.log(np.maximum(entry, 1e-12))
    #: A positive residual closes by the cross falling or the implied rising.
    want = -np.sign(z[fired]) * sign
    earned = move * want
    earned = earned[np.isfinite(earned)]
    if len(earned) < 50:
        return None
    return len(earned), float(np.mean(earned)) / cost


def main() -> int:
    legs = load()
    if not legs:
        print(f"no {TF} npz under {FX}")
        return 1
    print(f"{len(legs)} legs at {TF}, window {WINDOW}, holds {HOLDS}, "
          f"z {ZS}, delays {DELAYS}")

    def find(x: str, y: str) -> str | None:
        return f"{x}{y}" if f"{x}{y}" in legs else (f"{y}{x}" if f"{y}{x}" in legs else None)

    rows: list[tuple] = []
    tri = 0
    for a, b in itertools.combinations(CCY, 2):
        if "USD" in (a, b):
            continue
        au, bu, cr = find(a, "USD"), find(b, "USD"), find(a, b)
        if not (au and bu and cr):
            continue
        idx = align([legs[au], legs[bu], legs[cr]])
        if idx is None:
            continue
        tri += 1
        packed = {
            "au_name": au, "bu_name": bu, "cr_name": cr,
            "au": legs[au]["close"][idx[0]],
            "bu": legs[bu]["close"][idx[1]],
            "cr": legs[cr]["close"][idx[2]],
        }
        res = residual(a, b, packed)
        z = rolling_z(res, WINDOW)
        #: Each leg is a candidate instrument, with the sign the arithmetic
        #: gives: the cross falls, or either USD leg moves to lift the implied.
        traded = (
            (cr, packed["cr"], legs[cr]["spread"][idx[2]], -1.0),
            (au, packed["au"], legs[au]["spread"][idx[0]], +1.0),
            (bu, packed["bu"], legs[bu]["spread"][idx[1]], +1.0),
        )
        for name, px, sp, sign in traded:
            point = point_of(px)
            if point <= 0:
                continue
            for thresh in ZS:
                for hold in HOLDS:
                    for delay in DELAYS:
                        got = score(res, z, px, sp, point, sign, thresh, hold, delay)
                        if got:
                            rows.append(("identity", f"{a}/{b}", name, thresh, hold,
                                         delay, got[0], got[1]))

    #: The control: triples with no arithmetic reason to compose. The same
    #: machinery, scored the same way.
    rng = np.random.default_rng(13)
    names = sorted(legs)
    made = 0
    while made < CONTROLS:
        pick = list(rng.choice(names, 3, replace=False))
        letters = {c for n in pick for c in (n[:3], n[3:])}
        #: Reject anything that happens to be an identity.
        if len(letters) <= 3:
            continue
        idx = align([legs[n] for n in pick])
        if idx is None:
            continue
        made += 1
        p0 = legs[pick[0]]["close"][idx[0]]
        p1 = legs[pick[1]]["close"][idx[1]]
        p2 = legs[pick[2]]["close"][idx[2]]
        fake = np.log(np.maximum(p0, 1e-12)) - (
            np.log(np.maximum(p1, 1e-12)) + np.log(np.maximum(p2, 1e-12))
        )
        z = rolling_z(fake, WINDOW)
        point = point_of(p0)
        if point <= 0:
            continue
        for thresh in ZS:
            for hold in HOLDS:
                for delay in DELAYS:
                    got = score(fake, z, p0, legs[pick[0]]["spread"][idx[0]], point,
                                -1.0, thresh, hold, delay)
                    if got:
                        rows.append(("control", "+".join(pick), pick[0], thresh,
                                     hold, delay, got[0], got[1]))

    print(f"{tri} triangles, {made} control triples, {len(rows)} configurations\n")
    print(f"{'delay':>6} {'arm':>9} {'configs':>8} {'median edge/cost':>18} "
          f"{'share > 1.0':>12} {'observations':>13}")
    table: dict[tuple, list[tuple]] = {}
    for r in rows:
        table.setdefault((r[5], r[0]), []).append(r)
    for delay in DELAYS:
        for arm in ("identity", "control"):
            got = table.get((delay, arm))
            if not got:
                continue
            ratios = [g[7] for g in got]
            print(f"{delay:>6} {arm:>9} {len(got):8d} {st.median(ratios):>18.4f} "
                  f"{sum(r > 1.0 for r in ratios) / len(ratios):>11.1%} "
                  f"{sum(g[6] for g in got):>13d}")

    print(f"\n{'the executable question':>26}")
    for delay in DELAYS:
        a = table.get((delay, "identity")) or []
        c = table.get((delay, "control")) or []
        if not a or not c:
            continue
        ma = st.median([g[7] for g in a])
        mc = st.median([g[7] for g in c])
        verdict = "CLEARS its round trip" if ma > 1.0 else "short of its round trip"
        print(f"  delay {delay}: identities {ma:+.4f}  control {mc:+.4f}  -> {verdict}")
    print("\n1.0 is one round trip on the traded leg. Pre-specified grid, reported whole.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
