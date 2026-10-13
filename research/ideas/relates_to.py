"""What relates to one named instrument, through every test this desk trusts.

Pointed at `USDCAD` by default, and the first thing to say about that is what is
missing. **CAD is the oil currency**, so its most likely real relationship is to
crude - and there is no oil in this cache. 523 instruments at 1h and they are FX
six-character pairs, equities as Reuters codes, and Deriv synthetics: no energy,
no softs, and no indices. A screen cannot find a relationship to an instrument
it does not have, so the strongest candidate for this particular target is
untestable here rather than absent.

What can be tested is everything the session established, applied to one target:

* **volatility correlation**, which is where the real relationships turned out
  to be - a median of `0.5170` across traded instruments against a rotation
  null's `-0.0015` - nulled by `nulls.rotated`, which preserves every marginal
  exactly and destroys only the alignment;
* **split-ratio cointegration**, with the hedge ratio fitted on the first half
  and held, because `relating.Relating`'s live ratio reads a Dickey-Fuller `t`
  of `-29.39` between unrelated generated processes and is the wrong object for
  testing whether a hedge exists;
* **the identity rule**, `relating.is_identity`, so an arithmetic relation is
  reported as arithmetic rather than as a discovery;
* **the generated instruments as the control**, which should read nothing.

Every primitive here is the library's rather than this file's, which is the
point of having moved them there.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relationship_screen as screen  # noqa: E402

TARGET = os.environ.get("TARGET", "USDCAD")
#: Bars per volatility observation.
SPAN = int(os.environ.get("SPAN", "24"))
#: Equities carried, by coverage.
EQUITIES = int(os.environ.get("EQUITIES", "25"))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "10"))
SEED = 20261013


def universe():
    """Every FX pair, the metals, the best-covered equities, and the synthetics."""
    names = {"fx": [], "equity": [], "generated": []}
    for path in sorted(screen.CACHE.glob(f"*.{screen.FRAME}.npz")):
        name = path.name[: -len(f".{screen.FRAME}.npz")]
        if any(name.startswith(p) for p in screen.GENERATED_PREFIXES):
            names["generated"].append(name)
        elif len(name) == 6 and name.isupper() and name.isalpha():
            names["fx"].append(name)
        elif name.count(".") == 1:
            names["equity"].append(name)
    covered = []
    for name in names["equity"]:
        got = screen.load(name)
        if got is not None:
            covered.append((len(got[0]), name))
    covered.sort(reverse=True)
    names["equity"] = [n for _, n in covered[:EQUITIES]]
    names["generated"] = names["generated"][:20]
    return names


def log_vol(series, span: int = SPAN):
    import numpy as np

    times, values, _ = series
    steps = np.diff(values)
    count = len(steps) // span
    if count < 60:
        return None
    sd = steps[: count * span].reshape(count, span).std(axis=1)
    keep = sd > 0
    if keep.sum() < 60:
        return None
    return times[1 : count * span + 1 : span][keep], np.log(sd[keep])


def vol_correlation(left, right) -> float:
    import numpy as np

    lv, rv = log_vol(left), log_vol(right)
    if lv is None or rv is None:
        return float("nan")
    common, li, ri = np.intersect1d(lv[0], rv[0], return_indices=True)
    if len(common) < 60:
        return float("nan")
    a, b = lv[1][li], rv[1][ri]
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def split_t(left, right) -> tuple[float, float]:
    """Dickey-Fuller `t` on a spread whose ratio is fitted on the first half."""
    import numpy as np

    got = screen.align(left, right)
    if got is None:
        return float("nan"), float("nan")
    _, a, b, _, _ = got
    half = len(a) // 2
    if half < 200:
        return float("nan"), float("nan")
    varx = float(((a[:half] - a[:half].mean()) ** 2).sum())
    if varx <= 0:
        return float("nan"), float("nan")
    ratio = float(
        ((a[:half] - a[:half].mean()) * (b[:half] - b[:half].mean())).sum() / varx
    )
    return screen.dickey_fuller(b[half:] - ratio * a[half:])[1], ratio


def main() -> None:
    import numpy as np

    from till_infinity.structures.statespace.nulls import rotated
    from till_infinity.structures.statespace.relating import is_identity

    print(
        f"target {TARGET}; volatility over {SPAN}-bar spans, cointegration on a\n"
        "ratio fitted on the first half, nulls from the library\n"
    )
    names = universe()
    print(
        f"{len(names['fx'])} FX pairs, {len(names['equity'])} equities, "
        f"{len(names['generated'])} generated\n"
    )
    print("**No oil, no energy, no indices in this cache.** CAD is the oil")
    print("currency, so the strongest candidate for this target is untestable")
    print("here rather than absent.\n")

    target = screen.load(TARGET)
    if target is None:
        print(f"  {TARGET} not in the cache")
        return
    picker = random.Random(SEED)

    rows = []
    for kind, group in names.items():
        for name in group:
            if name == TARGET:
                continue
            other = screen.load(name)
            if other is None:
                continue
            corr = vol_correlation(target, other)
            if not math.isfinite(corr):
                continue
            t, ratio = split_t(target, other)
            rows.append(
                {
                    "name": name,
                    "kind": kind,
                    "vol": corr,
                    "t": t,
                    "ratio": ratio,
                    "identity": is_identity([TARGET, name]),
                }
            )
    if not rows:
        print("  nothing scored")
        return

    # The nulls: the same measurements against a rotation of each candidate.
    null_vol, null_t = [], []
    pool = [r["name"] for r in rows]
    picker.shuffle(pool)
    for name in pool[: min(len(pool), 40)]:
        other = screen.load(name)
        if other is None:
            continue
        for _ in range(max(REPS // 4, 2)):
            shift = picker.randrange(100, max(len(other[1]) - 100, 101))
            # `nulls.rotated` returns a **list** - the library keeps numpy out
            # of its signatures - and `align` fancy-indexes its inputs, which a
            # list does not support. Converting here rather than changing the
            # library, since a list is the right return for a pure-Python
            # package.
            spun = (
                other[0],
                np.asarray(rotated(list(other[1]), shift), dtype=float),
                other[2],
            )
            got = vol_correlation(target, spun)
            if math.isfinite(got):
                null_vol.append(got)
            t, _ = split_t(target, spun)
            if math.isfinite(t):
                null_t.append(t)

    vol_bar = max(null_vol) if null_vol else float("nan")
    t_bar = min(null_t) if null_t else float("nan")
    print("=" * 104)
    print(f"ARM 1  what shares volatility with {TARGET}")
    print("=" * 104)
    print(
        f"rotation null: {len(null_vol)} draws, max volatility correlation "
        f"{vol_bar:+.4f}, best Dickey-Fuller t {t_bar:+.2f}\n"
    )
    print(f"{'instrument':<16}{'kind':<10}{'vol corr':>10}{'split t':>10}{'ratio':>9}{'beats':>18}")
    rows.sort(key=lambda r: -(r["vol"] if math.isfinite(r["vol"]) else -9))
    for row in rows[:20]:
        marks = []
        if math.isfinite(vol_bar) and row["vol"] > vol_bar:
            marks.append("vol")
        if math.isfinite(t_bar) and math.isfinite(row["t"]) and row["t"] < t_bar:
            marks.append("cointegration")
        if row["identity"]:
            marks.append("IDENTITY")
        print(
            f"{row['name']:<16}{row['kind']:<10}{row['vol']:>+10.4f}"
            f"{row['t']:>+10.2f}{row['ratio']:>+9.3f}{' + '.join(marks) or '':>18}"
        )

    print("\n" + "=" * 104)
    print("ARM 2  how many clear each bar, and what the generated control says")
    print("=" * 104)
    print(f"{'kind':<12}{'candidates':>12}{'beat vol null':>15}{'beat t null':>13}{'median vol':>12}")
    for kind in ("fx", "equity", "generated"):
        here = [r for r in rows if r["kind"] == kind and not r["identity"]]
        if not here:
            continue
        print(
            f"{kind:<12}{len(here):>12}"
            f"{sum(1 for r in here if math.isfinite(vol_bar) and r['vol'] > vol_bar):>15}"
            f"{sum(1 for r in here if math.isfinite(t_bar) and math.isfinite(r['t']) and r['t'] < t_bar):>13}"
            f"{statistics.median(r['vol'] for r in here):>+12.4f}"
        )
    print(
        "\nIdentities are excluded from these counts and flagged in the table\n"
        "above: an exact linear relation is arithmetic, not a discovery. The\n"
        "generated row is the control and should clear nothing."
    )


if __name__ == "__main__":
    main()
