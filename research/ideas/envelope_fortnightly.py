"""Production's own retrain loop, replayed over history: is a fortnight right?

`fortnightly-retrain.md` pointed the protocol at a research model. This points
it at **the model production actually promotes** - the offline envelope quantile
forecaster - and asks the three questions a desk can act on:

  does retraining help?   a model trained once in 2021 against one refitted on
                          the cadence, both judged on the same fresh fortnights
  is the gate earning?    production promotes only when the challenger beats
                          the champion on a held-out fortnight. How often does
                          that fire, and does the desk lose by obeying it
  is 14 days right?       the same loop at 14, 28 and 56 days. A cadence that
                          buys nothing over a slower one is compute and risk
                          spent for nothing

The trainer is production's own `envelope_train.train` - quantile boosting at
`MODEL_LEVELS`, the last `RECENT_DAYS` of rows, `ITERATIONS` trees - and the
score is production's own **pinball loss** over `ev.TARGETS`, lower being
better. Nothing here is a reimplementation.

The champion is only replaced when it loses on a fortnight neither model was
trained on, which is `retrain.GATES["vs_champion"]` in its simplest form. The
full gate set also checks calibration, a control band on memoryless walks and an
exactness reproduction; those guard against a broken export rather than against
a worse model, so the contest here is the pinball comparison alone and the run
is an upper bound on how often production would promote.

  MT5BT_DB=... HORIZON=20 python research/ideas/envelope_fortnightly.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

OUT = Path(os.environ.get("OUT", ".data/envfn"))
HORIZON = int(os.environ.get("HORIZON", 20))
HOLDOUT = int(os.environ.get("HOLDOUT", 14))
WARM = int(os.environ.get("WARM", 540))
CADENCES = tuple(int(c) for c in os.environ.get("CADENCES", "14,28,56").split(","))
DAY = 86400.0


#: `retrain.GATES["vs_champion"]`, the relative pinball a challenger may be
#: worse by and still ship.
VS_CHAMPION = float(os.environ.get("VS_CHAMPION", 0.01))


def et_pinball_rows(y, q_champ, q_chal):
    """Per-row pinball difference, for the standard error the gate widens by."""
    from till_infinity.models import envelope_train as et
    a = et._pinball(np.asarray(y), np.asarray(q_chal))
    b = et._pinball(np.asarray(y), np.asarray(q_champ))
    return (a - b) / max(float(np.mean(b)), 1e-12)


def pinball(y, q):
    from till_infinity.models import envelope_train as et
    return float(np.mean(et._pinball(np.asarray(y), np.asarray(q))))


def quote(spec, x):
    """The spec's quantiles for every row of `x`, through the fitted regressors."""
    fitted = spec.get("_sklearn")
    if not fitted:
        return None
    return np.column_stack([m.predict(x) for m in fitted])


def loop(when, x, y, cadence, mode, train_fn):
    """One pass of production's protocol at `cadence` days."""
    t0, t1 = when.min(), when.max()
    champion, rows = None, []
    gap = HORIZON * 900.0
    for k, now in enumerate(np.arange(t0 + WARM * DAY, t1, cadence * DAY)):
        hold_from = now - HOLDOUT * DAY
        train_to = hold_from - gap
        tr = when <= train_to
        ho = (when > hold_from) & (when <= now)
        nxt = (when > now) & (when <= now + cadence * DAY)
        if tr.sum() < 20_000 or ho.sum() < 500 or nxt.sum() < 500:
            continue
        chal = train_fn(when[tr], x[tr], y[tr], HORIZON, seed=k)
        chal_q = quote(chal, x[ho])
        chal_p = pinball(y[ho], chal_q)
        if champion is None:
            champ_p, promoted, slack = np.nan, True, np.nan
        else:
            champ_p = pinball(y[ho], quote(champion, x[ho]))
            # **Production's gate is a tolerance, not a contest.** `GATES` reads
            # "not worse than the model in service by more than this or two
            # standard errors, whichever is wider - two weeks of one family is a
            # small sample, and noise must not block every promotion". The first
            # version of this file required the challenger to *win*, which is
            # much stricter than what runs and understated how often production
            # promotes. The live report that caught it: a challenger 0.12% worse
            # than the champion, promoted on `reasons: []`.
            per = et_pinball_rows(y[ho], quote(champion, x[ho]),
                                  quote(chal, x[ho]))
            se = float(np.std(per, ddof=1) / np.sqrt(len(per))) if len(per) > 2 else np.nan
            slack = max(VS_CHAMPION, 2 * se) if np.isfinite(se) else VS_CHAMPION
            # relative, lower-is-better: positive means the challenger is worse
            rel = (chal_p - champ_p) / champ_p if champ_p else np.nan
            promoted = bool(np.isfinite(rel) and rel <= slack)
        if champion is None or mode == "always_new" or (mode == "gated" and promoted):
            champion = chal
        served = pinball(y[nxt], quote(champion, x[nxt]))
        rows.append(dict(cadence=cadence, mode=mode, k=k,
                         date=str(pd.to_datetime(now, unit="s").date()),
                         n_train=int(tr.sum()), n=int(nxt.sum()),
                         chal_pin=chal_p, champ_pin=champ_p, promoted=promoted,
                         slack=slack, pinball=served))
        if mode == "never" and k == 0:
            # trained once and then left alone, judged on every later fortnight
            for j, later in enumerate(np.arange(now + cadence * DAY, t1, cadence * DAY)):
                m = (when > later) & (when <= later + cadence * DAY)
                if m.sum() < 500:
                    continue
                rows.append(dict(cadence=cadence, mode=mode, k=j + 1,
                                 date=str(pd.to_datetime(later, unit="s").date()),
                                 n_train=int(tr.sum()), n=int(m.sum()),
                                 chal_pin=np.nan, champ_pin=np.nan, promoted=False,
                                 pinball=pinball(y[m], quote(champion, x[m]))))
            break
    return pd.DataFrame(rows)


def main() -> None:
    import run as R
    import survivors
    from till_infinity.models import envelope_train as et
    from till_infinity.prices.models import Bar
    from till_infinity.structures.vol import envelope as ev
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    fam = os.environ.get("FAMILY", "fx")

    series = {}
    for s in [k for k in R.FAMILY if R.FAMILY[k] == fam and k not in R.FRESH]:
        df = R.load(s, "15m")
        if df is None or len(df) < 5000 or not ev.model_applies(s.lower(), "15m"):
            continue
        df = df.tail(50_000).reset_index(drop=True)
        series[(s, "15m")] = [
            Bar(time=float(t), open=float(o), high=float(h), low=float(l), close=float(c),
                volume=0.0)
            for t, o, h, l, c in zip(df.ts, df.open, df.high, df.low, df.close)
        ]
    print(f"{len(series)} {fam} series, {sum(len(v) for v in series.values()):,} bars")
    try:
        found = et.tracks(series, family=fam)
    except TypeError:
        found = et.tracks(series)
    when, x, y = et.rows(found, HORIZON)
    ok = np.isfinite(y) & np.isfinite(x).all(axis=1)
    when, x, y = when[ok], x[ok], y[ok]
    order = np.argsort(when)
    when, x, y = when[order], x[order], y[order]
    span = (when.max() - when.min()) / DAY
    print(f"horizon {HORIZON}: {len(y):,} rows over {span:.0f} days\n")

    out = []
    for cadence in CADENCES:
        for mode in ("never", "always_new", "gated"):
            t = loop(when, x, y, cadence, mode, et.train)
            if t.empty:
                continue
            out.append(t)
            prom = f"{int(t.promoted.sum())}/{len(t)}" if mode != "never" else "-"
            print(f"  cadence {cadence:>2}d  {mode:<11} {len(t):>3} periods   "
                  f"pinball {t.pinball.mean():.4f}   promoted {prom}")
        print()
    if out:
        t = pd.concat(out, ignore_index=True)
        OUT.mkdir(parents=True, exist_ok=True)
        t.to_csv(OUT / "envfn.csv", index=False)
        piv = t.pivot_table(index="cadence", columns="mode", values="pinball", aggfunc="mean")
        print("=== mean pinball, lower is better ===")
        print(piv.round(5).to_string())
        base = piv.get("never")
        if base is not None and "gated" in piv:
            print("\nretraining against never retraining, as a share of the pinball:")
            for c in piv.index:
                print(f"  {c:>2}d  {100 * (base[c] - piv['gated'][c]) / base[c]:+.2f}%")
        print(f"\nwritten: {OUT / 'envfn.csv'}")


if __name__ == "__main__":
    main()
