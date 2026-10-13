"""Does the library's `pooling.Pooled` reproduce the measured 5.6x?

`statespace-pooling-exponent.md` measured member pooling in a research harness
and `pooling.Pooled` is that result moved into the library. A library
implementation of a measured finding is worth nothing until it is scored the
same way on the same data, because a reimplementation is a chance to change the
answer by accident - and the harness and the member differ in one respect that
matters: the member forms its combined state in `predict` and scores it in
`update`, where the harness did both inline.

So: the same six instruments, the same held-out half, the same three scores,
against the same single-member baseline. The figures to reproduce are a CRPS of
about **0.0016** for the pool against **0.0090** for the best single member.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.structures.statespace.diagnostics import crps, pit_flatness  # noqa: E402
from till_infinity.structures.statespace.family import members  # noqa: E402
from till_infinity.structures.statespace.pooling import Pooled  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "12000"))
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
GENERATED = tuple(os.environ.get("GENERATED", "Volatility_75_Index,Step_Index_200").split(","))
QUANTILES = tuple(i / 20.0 for i in range(1, 20))


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times, closes = bundle["time"][order], bundle["close"][order]
    keep = closes > 0
    times, closes = times[keep], closes[keep]
    if len(times) < 3000:
        return None
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return times.tolist(), np.log(closes).tolist()


def run(times, values, one):
    """Held-out `(loglike/bar, pit, crps)` for any `family.Filter`."""
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2
    total, scores, pits = 0.0, [], []
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        one.predict(float(when))
        mu, sd = float(one.value), max(float(one.sd), 1e-12)
        if i >= start:
            z = (value - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * sd * sd))
            pits.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
            # The member supplies its own quantiles, which is the point of
            # having `quantiles()` on it rather than in every caller.
            getter = getattr(one, "quantiles", None)
            if getter is not None:
                scores.append(crps(getter(QUANTILES), value))
            else:
                from till_infinity.structures.statespace.distance import _normal_quantile

                scores.append(
                    crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], value)
                )
        one.update(float(value), noise * noise, float(when))
    if not scores:
        return None
    return total / len(scores), pit_flatness(pits), statistics.mean(scores)


def main() -> None:
    print(f"frame {FRAME}  reproducing statespace-pooling-exponent.md with the library member\n")
    built = members()
    arms = {
        "one: kalman": lambda: built["kalman"](),
        "one: reverting": lambda: built["reverting"](),
        "one: robust": lambda: built["robust"](),
        "Pooled() defaults": Pooled,
        "Pooled(mixture)": lambda: Pooled(rule="mixture"),
        "Pooled(argmax)": lambda: Pooled(rule="argmax"),
        "Pooled(alpha=0.5)": lambda: Pooled(alpha=0.5),
    }
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print("=" * 78)
        print(group)
        print("=" * 78)
        print(f"{'arm':<22}{'loglike/bar':>13}{'pit':>10}{'crps':>12}{'cells':>7}")
        for label, make in arms.items():
            cells = []
            for name in names:
                got = load(name)
                if got is None:
                    continue
                out = run(got[0], got[1], make())
                if out and all(math.isfinite(v) for v in out):
                    cells.append(out)
            if not cells:
                continue
            print(
                f"{label:<22}{statistics.median(c[0] for c in cells):>13.4f}"
                f"{statistics.median(c[1] for c in cells):>10.2f}"
                f"{statistics.median(c[2] for c in cells):>12.6f}{len(cells):>7}"
            )
        print()
    print(
        "The harness measured 0.009007 for the best single member and 0.001601\n"
        "for the pool. If `Pooled() defaults` does not land on the second, the\n"
        "library does not carry the finding whatever its docstring says."
    )


if __name__ == "__main__":
    main()
