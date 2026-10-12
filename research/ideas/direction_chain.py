"""Is there a direction regime? The `hmm` member, measured.

`family.PENDING["hmm"]` has named this member since the package began, with a
specific job: velocity is two variables and only one is learnable, so the
state wants to be `(position, log speed)` with direction as a separate
discrete process - and the HMM is the direction half.

**The prediction, written before running it.** The same paragraph that
motivates the decomposition says direction agrees with its predecessor 49.5%
of the time against 50% +/- 3.1%. So the chain is being asked to model a fair
coin and should collapse to one: two states converging on the same up-rate,
and no gain over a single fitted coin.

The member can find a chain that is really there - on a planted series with
up-rates of 0.70 and 0.30 and fifty-bar regimes it recovers **exactly**
0.70/0.30 and beats a fitted coin by 101 nats, which is the arm that makes a
null here readable.

## Three nulls in the same space

A density over signs cannot be compared with `linear`'s density over a level,
so the comparisons are the ones that live in `{up, down}`:

* **a fair coin** at one half - the floor;
* **a fitted coin**, one `P(up)` estimated on the training half - the null
  that matters, because a chain which merely rediscovers the unconditional
  drift has learnt nothing about sequence;
* **a chain fitted on shuffled signs**, which keeps the up-share exactly and
  destroys the order. If the chain scores the same there, whatever it found
  was the marginal.

## And the other half, which should work

The decomposition's claim is that **speed** carries what direction does not.
So the second arm measures the same persistence the registry quotes - the sum
of the first five autocorrelations of speed against signed rate - on every
instrument rather than the one eurusd 4h series it was found on.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.structures.statespace.hmm import Direction, coin, fit, up_share

HOUR = 3600.0

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
GENERATED = ("Volatility_75_Index", "Step_Index")
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))

SINCE = float(os.environ.get("SINCE", "1420070400"))
LIMIT = int(os.environ.get("LIMIT", "30000"))
SEED = 20261012
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = np.asarray(bundle["time"], dtype=float)[order].tolist()
            closes = np.asarray(bundle["close"], dtype=float)[order].tolist()
        first = 0
        while first < len(times) and times[first] < SINCE:
            first += 1
        times, closes = times[first:], closes[first:]
        if len(times) > LIMIT:
            times, closes = times[-LIMIT:], closes[-LIMIT:]
        return (times, closes) if len(times) > 2000 else None
    return None


def persistence(values: list[float], lags: int = 5) -> float:
    """Sum of the first `lags` autocorrelations - the registry's own statistic."""
    if len(values) < 100:
        return float("nan")
    middle = statistics.fmean(values)
    den = sum((v - middle) ** 2 for v in values)
    if den <= 0:
        return float("nan")
    total = 0.0
    for lag in range(1, lags + 1):
        total += (
            sum((values[i] - middle) * (values[i + lag] - middle) for i in range(len(values) - lag))
            / den
        )
    return total


def main() -> None:
    print(
        f"frames {FRAMES}\n"
        "chain, coin and fair are held-out log-likelihoods over the **signs**\n"
        "of the second half. shuffled is the chain on the same signs reordered.\n"
        "A gain over the fitted coin is the only thing that would matter.\n"
    )
    print(
        f"{'instrument':<22}{'frame':<6}{'n':>7}{'up share':>9}"
        f"{'rates':>12}{'chain':>10}{'vs coin':>9}{'vs fair':>9}{'vs shuf':>9}"
    )

    rows = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            found = load(name, frame)
            if found is None:
                continue
            times, closes = found
            moves = [
                math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes))
                if closes[i] > 0 and closes[i - 1] > 0
            ]
            if len(moves) + 1 != len(times):
                continue
            stamps = times[1:]
            half = len(moves) // 2

            member, _ = fit(stamps[:half], moves[:half])
            live = Direction(persist_hours=member.persist_hours, rates=member.rates)
            for when, move in zip(stamps[half:], moves[half:], strict=True):
                live.predict(when)
                live.update(move, when)

            share = up_share(moves[:half])
            fitted = coin(moves[half:], share)
            fair = coin(moves[half:], 0.5)

            # The chain on the same signs reordered: the up-share is exactly
            # preserved and the sequence is gone.
            mixed = list(moves[half:])
            random.Random(SEED).shuffle(mixed)
            spun = Direction(persist_hours=member.persist_hours, rates=member.rates)
            for when, move in zip(stamps[half:], mixed, strict=True):
                spun.predict(when)
                spun.update(move, when)

            label = f"*{name}" if name in GENERATED else name
            print(
                f"{label:<22}{frame:<6}{len(moves):>7}{share:>9.3f}"
                f"{f'{member.rates[0]:.2f}/{member.rates[1]:.2f}':>12}"
                f"{live.loglike:>10.1f}{live.loglike - fitted:>9.1f}"
                f"{live.loglike - fair:>9.1f}{live.loglike - spun.loglike:>9.1f}"
            )
            rows.append(
                {
                    "label": label,
                    "spread": abs(member.rates[0] - 0.5),
                    "vs_coin": live.loglike - fitted,
                    "vs_shuf": live.loglike - spun.loglike,
                    "speed": persistence([abs(m) for m in moves]),
                    "signed": persistence(moves),
                }
            )

    traded = [r for r in rows if not r["label"].startswith("*")]
    if traded:
        print(
            f"\n   traded median: gain over the fitted coin "
            f"{statistics.median([r['vs_coin'] for r in traded]):+.1f} nats, "
            f"over the shuffled chain "
            f"{statistics.median([r['vs_shuf'] for r in traded]):+.1f}.\n"
            f"   fitted state separation, median "
            f"{statistics.median([r['spread'] for r in traded]):.3f} either side "
            "of a half - zero would be one coin."
        )

    print("\n== the other half: is speed more persistent than the signed rate?")
    print(f"{'instrument':<22}{'speed':>9}{'signed':>9}{'ratio':>8}")
    for row in rows:
        if math.isnan(row["speed"]) or row["signed"] == 0:
            continue
        print(
            f"{row['label']:<22}{row['speed']:>9.3f}{row['signed']:>9.3f}"
            f"{abs(row['speed'] / row['signed']):>8.1f}"
        )
    usable = [r for r in rows if not math.isnan(r["speed"]) and r["signed"] != 0]
    if usable:
        print(
            f"\n   The registry quotes +0.381 against -0.047 on eurusd 4h, a ratio\n"
            f"   of 8.1. Median here: speed "
            f"{statistics.median([r['speed'] for r in usable]):+.3f}, signed "
            f"{statistics.median([r['signed'] for r in usable]):+.3f}."
        )


if __name__ == "__main__":
    main()
