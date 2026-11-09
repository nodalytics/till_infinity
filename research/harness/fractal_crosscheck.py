"""Cross-validate this repo's fractal estimators against the one published library worth depending on.

    ./.secrets/lab.sh sync
    ./.secrets/lab.sh exec 'cd $HOME/till_infinity && PYTHONPATH=$HOME/till_infinity/repo \
        OMP_NUM_THREADS=1 $HOME/till_infinity/.venv-fractal/bin/python -W ignore -u \
        repo/research/harness/fractal_crosscheck.py'

**This needs `.venv-fractal`, not the usual lab venv.** `fractal-analysis`
declares `requires-python >= 3.13` from version 0.2.1 and `< 3.11` at 0.2.0 and
below, so on the lab's system Python 3.12 **no version of it installs at all** -
pip lists twenty-four releases and matches none. Built with:

    $HOME/.local/bin/uv venv --python 3.13 $HOME/till_infinity/.venv-fractal
    $HOME/.local/bin/uv pip install --python $HOME/till_infinity/.venv-fractal/bin/python \
        fractal-analysis

## Why this exists

`research/docs/fractal-rules.md` reports a null, and a null is an argument about
an estimator as much as about a market. An estimator written here, nulled
against a generator written here, read back by its own author, is
self-confirming: a sign error shared between the two is invisible.

So both crossings are run. The library supplies a **Wood-Chan** fractional
Brownian motion (circulant embedding, Wood and Chan 1994) and the **IR** and
**QV** Hurst estimators (Bardet and Surgailis 2013); this repo supplies a
Davies-Harte fractional Brownian motion and DFA, rescaled range and a
structure-function exponent.

* **This repo's estimators on the library's paths** - if they recover `H` from
  a generator nobody here wrote, the estimators are not reading their own plant.
* **The library's estimators on this repo's paths** - if IR and QV recover `H`
  from `fractalest.fbm`, the plant in the power curve is a fractional Brownian
  motion and not something that merely looks like one.

A disagreement in one direction localises the fault; agreement in both is the
only reading that licenses the power curve.
"""

from __future__ import annotations

from hashlib import sha256

import numpy as np

from research.harness import fractalest


def _seed(*parts: object) -> int:
    """A seed from the cell's name. **Not `hash()`**: it is salted per process
    for anything holding a string, so the same cell draws a different arm on
    every run, and that has broken four harnesses in this repo."""
    digest = sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:4], "big")

#: `alpha` sets the IR/QV estimator's local window as `n ** alpha`. The library
#: exposes it with no default, so it is swept rather than chosen: a single value
#: is a single cell and these estimators are known to be window-sensitive.
ALPHAS = (0.2, 0.3, 0.5)
PLANTED = (0.30, 0.40, 0.50, 0.60, 0.70)
SAMPLE = 1 << 14
DRAWS = 8
#: Window for this repo's estimators, matching the middle of `fractal_rules`'
#: swept reach so the numbers are comparable to the power table.
WIDTH = 256


def ours(path: np.ndarray) -> dict[str, float]:
    """This repo's three exponent estimators on one path, median over windows."""
    price = fractalest.windows(path, WIDTH, WIDTH)
    step = fractalest.windows(np.concatenate([[0.0], np.diff(path)]), WIDTH, WIDTH)
    hurst, _ = fractalest.structure_scaling(price)
    return {
        "dfa": float(np.nanmedian(fractalest.dfa(step))),
        "rs": float(np.nanmedian(fractalest.rescaled_range(step))),
        "struct": float(np.nanmedian(hurst)),
    }


def theirs(path: np.ndarray) -> dict[str, float]:
    """The library's IR and QV estimators on one path, median Hölder exponent."""
    from fractal_analysis.estimator.hurst_estimator import IrHurstEstimator, QvHurstEstimator

    out: dict[str, float] = {}
    for alpha in ALPHAS:
        for label, cls in (("ir", IrHurstEstimator), ("qv", QvHurstEstimator)):
            try:
                got = np.asarray(cls(path, alpha=alpha).holder_exponents, dtype=float)
                out[f"{label}@{alpha}"] = float(np.nanmedian(got))
            except Exception as exc:  # noqa: BLE001 - one failed cell must still print
                out[f"{label}@{alpha}"] = float("nan")
                print(f"      {label}@{alpha} failed: {str(exc)[:80]}")
    return out


def their_path(hurst: float, draw: int) -> np.ndarray:
    from fractal_analysis.simulator.wood_chan.wood_chan_fractal_simulator import (
        WoodChanFbmSimulator,
    )

    # The library draws from the legacy global state, so it is seeded there.
    np.random.seed(_seed("wood-chan", f"{hurst:.3f}", draw))
    return np.asarray(
        WoodChanFbmSimulator(sample_size=SAMPLE, hurst_parameter=hurst).get_fbm(), dtype=float
    ).ravel()[:SAMPLE]


def our_path(hurst: float, draw: int) -> np.ndarray:
    rng = np.random.default_rng(_seed("davies-harte", f"{hurst:.3f}", draw))
    return np.cumsum(fractalest.fbm(SAMPLE, hurst, rng))


def table(title: str, generator, estimator) -> None:
    print(f"\n{title}")
    keys: list[str] = []
    rows: dict[float, dict[str, tuple[float, float]]] = {}
    for h in PLANTED:
        per: dict[str, list[float]] = {}
        for d in range(DRAWS):
            for k, v in estimator(generator(h, d)).items():
                per.setdefault(k, []).append(v)
        keys = list(per)
        rows[h] = {k: (float(np.nanmean(v)), float(np.nanstd(v))) for k, v in per.items()}
    print("    " + f"{'H':>5s} " + " ".join(f"{k:>10s}" for k in keys))
    for h in PLANTED:
        print(f"    {h:>5.2f} " + " ".join(f"{rows[h][k][0]:>10.4f}" for k in keys))
    print("    " + f"{'bias':>5s} " + " ".join(f"{rows[h][k][0] - h:>+10.4f}" for k in keys))
    print(
        "    "
        + f"{'slope':>5s} "
        + " ".join(
            f"{np.polyfit(PLANTED, [rows[h][k][0] for h in PLANTED], 1)[0]:>10.4f}" for k in keys
        )
    )
    print(
        "    the bias row is the last H's; the slope is d(reading)/dH over the ladder - "
        "1.0 is a calibrated estimator, 0.0 is a blind one"
    )


def main() -> None:
    print(f"fractal estimator cross-check: {SAMPLE:,} points, {DRAWS} draws, window {WIDTH}")
    table(
        "A. this repo's estimators on the library's Wood-Chan paths",
        their_path,
        ours,
    )
    table(
        "B. the library's IR/QV estimators on this repo's Davies-Harte paths",
        our_path,
        theirs,
    )
    table(
        "C. each on its own, for reference - this repo's estimators on this repo's paths",
        our_path,
        ours,
    )
    table(
        "D. and the library's on its own",
        their_path,
        theirs,
    )
    print("\ndone", flush=True)


if __name__ == "__main__":
    main()
