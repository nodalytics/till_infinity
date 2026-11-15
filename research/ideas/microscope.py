"""One feature at a time, by decile, against the same feature on shuffled days.

**The aggregate answer and the microscopic one are different questions.**
[`atr-ml.md`](../docs/atr-ml.md) put candle geometry and the regime through two
models and found nothing that survived a second window - but a model's verdict
is a single number, and it cannot say "a hammer with a five-times wick does
this". This does: every feature is cut into deciles and each decile reports the
forward move it was followed by.

Everything is in **ATR units**, for the reason `reactive-zones.md` measures:
ATR is twice the mean close-to-close move in every instrument-frame cell
tested, so dividing by it puts five instruments and eight years on one scale.

## The two controls, and what each is for

* **Day-shuffled bars.** Every wick, body and range is exactly as the market
  made it - only the order of days changes - so a decile pattern that survives
  is a property of bar shapes in isolation and one that vanishes needed the
  market's own sequence. `re-hung-bar-shapes-break-bar-derived-nulls` is why
  the shuffle moves whole days rather than resampling bar components.
* **Per instrument.** A pooled decile table here once agreed with a claim every
  subgroup refuted, and the gold drift measured in `atr-ml.md` - **+0.088 ATR**
  a bar over the training years - is exactly the shape that does it, so each
  instrument's own mean is removed before pooling.

Run as:

    uv run python research/ideas/microscope.py --feature tsi,wick,body
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import CATALOGUE, Candles, atr, fold, load, shuffled, tsi  # noqa: E402

SYMBOLS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")
HORIZON = 16


def features(bars: Candles) -> dict[str, np.ndarray]:
    """Every reading, aligned to the bar it is known at.

    The candle ones are the shapes the operator's rule names - the wick that
    makes a pin bar, the body that makes an engulf - taken as continuous
    quantities rather than as a threshold somebody chose. A threshold hides
    the shape of the relationship, which is the thing a microscope is for.
    """
    band = atr(bars)
    span, body = bars.high - bars.low, np.abs(bars.close - bars.open)
    alive = span > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        upper = (bars.high - np.maximum(bars.open, bars.close)) / np.where(alive, span, np.nan)
        lower = (np.minimum(bars.open, bars.close) - bars.low) / np.where(alive, span, np.nan)
        strength = tsi(bars.close)
        slope = np.concatenate(([np.nan], np.diff(strength)))
        return {
            # The candle, microscopically.
            "body_ratio": body / np.where(alive, span, np.nan),
            "bar_size": span / band,
            "upper_wick": upper,
            "lower_wick": lower,
            "wick_imbalance": lower - upper,
            "close_in_range": (bars.close - bars.low) / np.where(alive, span, np.nan),
            # The TSI, microscopically: its level, its distance from zero, and
            # its change - three different claims that one threshold conflates.
            "tsi": strength,
            "tsi_abs": np.abs(strength),
            "tsi_slope": slope,
        }


def forward(bars: Candles, horizon: int = HORIZON) -> np.ndarray:
    """The move over the next `horizon` bars, in ATR of the entry bar."""
    band = atr(bars)
    out = np.full(bars.close.size, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:-horizon] = (bars.close[horizon:] - bars.close[:-horizon]) / band[:-horizon]
    return out


def floor(values: np.ndarray, target: np.ndarray, deciles: int = 10, draws: int = 20) -> float:
    """The largest decile mean a **permuted** feature produces, averaged over draws.

    **The right null for "does this feature sort the targets", and the day
    shuffle is not it.** At a 16-bar horizon on 15m bars the forward window
    lies inside the same day, and shuffling whole days leaves each day's
    internal sequence intact - so that arm barely perturbs the quantity being
    measured and reads as a near-copy of the real one by construction.

    Permuting the feature while holding the targets fixed destroys exactly the
    association under test and nothing else. What comes back is how large a
    decile mean this many rows produce from nothing, which is the number every
    table above has to beat.
    """
    ok = np.isfinite(values) & np.isfinite(target)
    v, y = values[ok], target[ok]
    rng = np.random.default_rng(3)
    peaks = []
    for _ in range(draws):
        shuffled_v = rng.permutation(v)
        edges = np.percentile(shuffled_v, np.linspace(0, 100, deciles + 1))
        best = 0.0
        for i in range(deciles):
            lo, hi = edges[i], edges[i + 1]
            m = (shuffled_v >= lo) & (shuffled_v < hi) if i < deciles - 1 else (shuffled_v >= lo)
            if m.sum() >= 100:
                best = max(best, abs(float(y[m].mean())))
        peaks.append(best)
    return float(np.mean(peaks))


def table(name: str, values: np.ndarray, target: np.ndarray, deciles: int = 10) -> None:
    """One feature, by decile, with the forward move each decile was followed by."""
    ok = np.isfinite(values) & np.isfinite(target)
    if ok.sum() < 1000:
        print(f"  {name}: too few rows")
        return
    v, y = values[ok], target[ok]
    edges = np.percentile(v, np.linspace(0, 100, deciles + 1))
    noise = floor(values, target, deciles)
    print(f"  {name}  ({ok.sum():,} rows)   a permuted feature peaks at {noise:.4f}")
    for i in range(deciles):
        lo, hi = edges[i], edges[i + 1]
        m = (v >= lo) & (v < hi) if i < deciles - 1 else (v >= lo)
        if m.sum() < 100:
            continue
        mean = float(y[m].mean())
        # The bar is the sign and the size, so a column of them reads as a
        # shape rather than as ten numbers.
        width = int(round(abs(mean) * 150))
        bar = ("+" if mean > 0 else "-") * min(width, 40)
        print(f"    d{i + 1:<2} {lo:+9.3f}..{hi:+9.3f}  n {m.sum():>7,}  {mean:+7.4f}  {bar}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--frame", default="15m")
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--feature", default="tsi,tsi_abs,tsi_slope,body_ratio,wick_imbalance")
    parser.add_argument("--arms", default="real,shuffled")
    args = parser.parse_args()

    wanted = [f.strip() for f in args.feature.split(",") if f.strip()]
    for arm in (a.strip() for a in args.arms.split(",") if a.strip()):
        pooled: dict[str, list[np.ndarray]] = {name: [] for name in wanted}
        targets: list[np.ndarray] = []
        for symbol in (s for s in args.symbols.split(",") if s):
            base = load(Path(args.catalogue), symbol)
            if arm == "shuffled":
                base = shuffled(base, seed=11)
            bars = fold(base, args.frame)
            found = features(bars)
            y = forward(bars)
            # **Each instrument's own drift out first.** Gold's forward move
            # averages +0.088 ATR over these years; pooling without removing it
            # reports that as whatever feature happens to be high on gold.
            finite = np.isfinite(y)
            if finite.any():
                y = y - float(np.mean(y[finite]))
            targets.append(y)
            for name in wanted:
                pooled[name].append(found[name])
        target = np.concatenate(targets)
        print(f"\n=== {arm}, pooled, each instrument's drift removed")
        for name in wanted:
            table(name, np.concatenate(pooled[name]), target)


if __name__ == "__main__":
    main()
