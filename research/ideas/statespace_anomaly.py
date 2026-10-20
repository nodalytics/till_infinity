"""Does the statespace service beat what the anomaly model already has?

`anomalies.md` measured shocks and range blowouts at AUC **0.76-0.81** an hour
or more ahead on real markets, with the Deriv generators dead flat at
0.486-0.518 - and it named what carries it: the 14-bar EWMA of true range over
its 500-bar mean (0.60-0.77 alone) and `tr_percentile` (0.60-0.73). Those are
incumbents with no model in them.

The statespace service publishes a filtered log variance, a one-step predictive
spread, a coverage-addressed band and a standardised innovation, and **nothing
has ever scored them against those incumbents**. Until that is run, "statespace
can see expansions coming" rests on the band holding its coverage, which is a
calibration claim rather than a skill claim.

## Four arms on one target, and the third is the one that matters

* `base` - `anomalies.py`'s own feature set, unchanged. The incumbent.
* `+ss` - the service's four outputs added to it.
* `+ewma` - an exponentially-weighted mean of log Garman-Klass and an EWMA
  standard deviation of its residuals, added instead. **This is the control
  `changepoint-increment.md` asked for**: a Normal-Inverse-Gamma predictive
  scale tracks recent residual magnitude, so a plain EWMA may supply the same
  thing. If `+ewma` matches `+ss`, the filter is not what is paying.
* `+bocpd` - the inferred predictive standard deviation alone, which is the
  column that carried the whole +0.2 increment on a 48-lag ridge.

## Scored twice, and the second column is the claim

Raw test-block AUC, and then AUC **within deciles of `trpct`** - the incumbent
percentile. `auc-is-free-on-volatility-targets` is the standing rule here:
`gk_cc` read 0.8052 on a constant-sigma generator and 0.5250 once current
volatility was held fixed, so an arm that only restates the volatility the
model already sees will look strong in the first column and vanish in the
second. The controls are `anomalies.py`'s: Boom/Crash, Jump and Volatility,
whose anomalies are published memoryless.

`R` is the value `dispersion_noise.py` measured for `log(garman_klass)` rather
than the shipped guess, and BOCPD keeps the `noise = 1.0` the published arm
used so this is the same column that was scored before.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parent / "harness", HERE.parents[1]):
    sys.path.insert(0, str(q))

import spikerisk  # noqa: E402
from anomalies import FEATS, GROUPS, frame, releases  # noqa: E402

from till_infinity.statespace.changepoint import Changepoint  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.facade import Desk  # noqa: E402

#: The measurement variance of `log(garman_klass)`, measured rather than
#: derived: `dispersion_noise.py` Part A reads 0.2589 at 5,760 ticks a bar and
#: 0.3517 at 60, against the shipped 0.67 and the alternative derivation's
#: 0.145. The denser end is the right read for a 15m or 1h bar.
NOISE = 0.265

#: Bars folded before any feature is offered. `Desk._quantiles` needs
#: `facade.LEAST` residuals before `covering` is measured rather than assumed,
#: and `anomalies.py` already drops its first 1,500 rows.
WARM = 500

#: EWMA memory for the control arm, matched to the incumbent's 14-bar EWMA of
#: true range so the only difference is the estimator and the filter.
ALPHA = 1.0 / 14.0

KINDS = ("shock", "range")
SS = ("ss_logvar", "ss_spread", "ss_width", "ss_abs")
EWMA = ("ew_logvar", "ew_sd")
BOCPD = ("bo_sd",)
ARMS = {"base": (), "+ss": SS, "+ewma": EWMA, "+bocpd": BOCPD}
STRATA = 10
SECONDS = {"5m": 300.0, "15m": 900.0, "1h": 3600.0, "4h": 14400.0}


def _columns(df: pd.DataFrame, sym: str, interval: str) -> dict[str, np.ndarray]:
    """Every arm's features for one series, causal and one pass each."""
    o, h, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    n = len(c)
    step = SECONDS.get(interval, 3600.0)

    logvar = np.full(n, np.nan)
    for i in range(n):
        got = dispersion(o[i], h[i], lo[i], c[i])
        if got is not None:
            logvar[i] = got

    out = {k: np.full(n, np.nan) for k in SS + EWMA + BOCPD}
    desk = Desk()
    model = Changepoint()
    mean = sd2 = None
    when = 0.0
    seen = 0
    for i in range(n):
        value = logvar[i]
        if not np.isfinite(value):
            continue
        when += step
        seen += 1

        # The EWMA control, updated before the readings are taken so it is as
        # causal as the filter it is standing in for.
        if mean is None:
            mean, sd2 = value, 0.0
        else:
            resid = value - mean
            mean += ALPHA * resid
            sd2 += ALPHA * (resid * resid - sd2)

        got = desk.read(sym, interval, when, value, NOISE)
        model.update(value, 1.0, when)
        if seen <= WARM:
            continue
        band = got.covering(0.90)
        out["ss_logvar"][i] = got.value
        out["ss_spread"][i] = got.spread
        out["ss_width"][i] = band.high - band.low
        out["ss_abs"][i] = abs(got.surprise)
        out["ew_logvar"][i] = mean
        out["ew_sd"][i] = math.sqrt(max(sd2, 0.0))
        out["bo_sd"][i] = float(model.sd)
    return out


def _within(y: np.ndarray, p: np.ndarray, strata: np.ndarray) -> float:
    """Mean AUC inside deciles of the incumbent, weighted by stratum size."""
    good = np.isfinite(strata)
    if good.sum() < 1_000:
        return float("nan")
    edges = np.quantile(strata[good], np.linspace(0, 1, STRATA + 1)[1:-1])
    which = np.digitize(strata, edges)
    total = weight = 0.0
    for band in range(STRATA):
        keep = good & (which == band)
        if keep.sum() < 200 or len(np.unique(y[keep])) < 2:
            continue
        total += roc_auc_score(y[keep], p[keep]) * keep.sum()
        weight += keep.sum()
    return total / weight if weight else float("nan")


def main() -> None:
    print(
        "Does the statespace service add to the anomaly model, or restate it?\n"
        "anomalies.py's own labels, features, split and controls, with four arms:\n"
        "the incumbent alone, plus the service's outputs, plus an EWMA control,\n"
        "plus BOCPD's inferred sd. Second column is AUC within trpct deciles,\n"
        f"which is where a restatement of volatility goes to die. R = {NOISE}.\n",
        flush=True,
    )
    cal = releases()
    for interval in os.environ.get("INTERVALS", "15m,1h").split(","):
        print(f"\n{'=' * 104}\nSTATESPACE AGAINST THE ANOMALY INCUMBENTS - {interval}")
        for group, syms in GROUPS.items():
            frames = []
            for sym in syms:
                try:
                    df = spikerisk.load(None, sym, "SEQLAB", interval)
                    got = frame(sym, interval, cal)
                except (ValueError, FileNotFoundError, KeyError) as exc:
                    print(f"  skip {sym}: {str(exc)[:60]}", flush=True)
                    continue
                rows = got["t"].to_numpy()
                if rows.max() >= len(df):
                    print(f"  skip {sym}: {len(df)} bars against index {rows.max()}", flush=True)
                    continue
                for name, series in _columns(df, sym, interval).items():
                    got[name] = series[rows]
                frames.append(got)
            if not frames:
                continue
            d = pd.concat(frames, ignore_index=True)
            tr, te = ~d["test"].to_numpy(), d["test"].to_numpy()
            fit = np.random.default_rng(0).choice(
                np.flatnonzero(tr), min(400_000, int(tr.sum())), replace=False
            )
            strata = d["trpct"].to_numpy()[te]
            print(f"\n  {group}: {len(d):,} bars", flush=True)
            for kind in KINDS:
                y = d[f"y_{kind}_1-4"].to_numpy()
                if y[tr].mean() < 0.002 or y[te].mean() < 0.002:
                    print(f"    {kind:<6} too rare to score", flush=True)
                    continue
                singles = []
                for feature in ("lvol", "trpct") + SS + EWMA + BOCPD:
                    x = d[feature].fillna(-1).to_numpy()[te]
                    if np.std(x) > 0:
                        auc = roc_auc_score(y[te], x)
                        singles.append(f"{feature} {max(auc, 1 - auc):.3f}")
                base = None
                line = []
                for arm, extra in ARMS.items():
                    X = d[list(FEATS) + list(extra)].fillna(-1).to_numpy()
                    model = HistGradientBoostingClassifier(
                        max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300
                    ).fit(X[fit], y[fit])
                    p = model.predict_proba(X)[:, 1]
                    auc = roc_auc_score(y[te], p[te])
                    inside = _within(y[te], p[te], strata)
                    if base is None:
                        base = (auc, inside)
                        line.append(f"{arm} {auc:.4f} / {inside:.4f}")
                    else:
                        line.append(
                            f"{arm} {auc:.4f} ({auc - base[0]:+.4f}) / "
                            f"{inside:.4f} ({inside - base[1]:+.4f})"
                        )
                print(f"    {kind:<6} rate {y[te].mean():.2%} | " + " | ".join(line), flush=True)
                print(f"           singles: {', '.join(singles)}", flush=True)
    print(
        "\n\nRead the second number in each pair. An arm that restates the volatility\n"
        "the incumbent already holds gains in the raw AUC and nothing inside the\n"
        "strata. An arm that gains in both is carrying something the EWMA of true\n"
        "range does not - and if `+ewma` moves as much as `+ss`, what pays is the\n"
        "estimator rather than the filter.",
        flush=True,
    )


if __name__ == "__main__":
    main()
