"""What would a different target have made, on the path the trade actually took?

The supervisor's first object. `docs/plans/2026-10-08-opportunity-as-supervisor.md`
argues that `opportunity` should correct the other strategies rather than
compete with them, and that **the only correction worth starting with is
geometry**, because of an asymmetry nobody had named:

* "your reward should be 1.5, not 1.25" has a **recoverable counterfactual** -
  same entry, same stop, did price get there first
* "do not take this trade" destroys its own evidence - the trade is never
  taken and nothing can ever score the advice

So this does not model which strategy is best. It models **the value of a
correction**, which has a label.

## The counterfactual is already in the journal

No bars are needed. Each outcome entry records `best_r`, the furthest the trade
ever ran in its own favour, so any target at or below it **was reached before
the exit** - the exit is what ended the recording. That gives, for a proposed
reward `rr`:

    rr <= best_r             -> +rr        reached, before whatever ended it
    rr >  best_r, stopped    -> -1.0       a further target changes nothing
    rr >  best_r, held out   -> r_multiple never reached, same clock, same exit
    rr >  best_r, took target-> censored   the trade would have run on, unseen

**Lowering a target is exactly computable. Raising one is only computable when
the trade did not reach its own.** The censored share is reported rather than
dropped quietly, because it is the one place this cannot see.

## Why the path stays valid when the target moves

The obvious objection is that changing the target changes the trade. Here it
does not change the *stop* path: `break_even_at` and `trail_vol` both trigger
on **R reached**, not on where the target sits, so the stop behaves identically
under a different target and the recorded excursion still applies.

What it cannot model is a strategy whose entry would differ - and none here
choose entries by target - or any interaction through position sizing, which
is set from the stop.

## The decision interval is a bootstrap, not a conformal one

Worth stating because the plan this came from got it wrong. Conformal gives a
**per-trade** prediction interval: how much regret the *next* trade might see.
The question being asked is different - "is the mean regret of this correction
above zero" - and that is a confidence interval on a mean, so it gets the
day-block bootstrap this repository uses everywhere else.

Conformal still has a job here, and it is the second one: reporting the spread
a desk would actually live through. It is not the thing that decides.

## What would make this wrong

A mean regret above zero says the correction would have paid **on the trades
that were taken**. It says nothing about trades that a different target would
have caused to be taken or skipped, and nothing about whether the strategy's
edge survives the change. Those are different questions and this answers
neither.

  python research/ideas/regret.py outcomes.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Proposed rewards to test, in R. Spans well below and above the desk's
#: floors (1.10 to 1.50 after the per-strategy work) so the answer is not
#: constrained to the neighbourhood of what is already shipped.
GRID = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)
DRAWS = 4000
#: Trades a (strategy, rr) cell needs before it is reported at all.
MIN_N = 60


def counterfactual(row: pd.Series, rr: float) -> float | None:
    """R this trade would have made with its reward at `rr`, or None if unseen."""
    if rr <= row.best_r:
        return rr
    kind = str(row.exit_kind or "").lower()
    if "stop" in kind:
        return -1.0
    if "target" in kind:
        return None  # it would have run past its own exit; nothing recorded there
    return float(row.r_multiple)


def block_ci(v, days, draws=DRAWS, seed=47):
    """Mean and a 90% day-block bootstrap interval - trades cluster by day."""
    v = np.asarray(v, float)
    if len(v) < 20:
        return (float(v.mean()) if len(v) else np.nan), np.nan, np.nan
    rng = np.random.default_rng(seed)
    u, inv = np.unique(np.asarray(days), return_inverse=True)
    total = np.bincount(inv, weights=v, minlength=len(u))
    count = np.bincount(inv, minlength=len(u)).astype(float)
    pick = rng.integers(0, len(u), size=(draws, len(u)))
    got = total[pick].sum(1) / np.maximum(count[pick].sum(1), 1)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


#: An |R| past this is a record defect rather than a trade. One `cycle-scalp`
#: close carries **r_multiple = 2390**, which alone drags that strategy's mean
#: to +3.35 against a median of -0.27 - and the desk loses money. The broker is
#: authoritative for P&L and the journal is not.
MAX_ABS_R = 10.0

#: The most of a window's trades that may carry an unrecorded excursion before
#: the answer is refused. Not a tuning knob - see `telemetry`.
MAX_UNRECORDED = 0.10


def load(path: str) -> pd.DataFrame:
    """Outcomes, with only the rows that are defects on their face removed."""
    d = pd.read_csv(path)
    for col in ("r_multiple", "best_r", "reward_to_risk", "time", "seconds"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["r_multiple", "best_r", "time"])
    wild = d.r_multiple.abs() > MAX_ABS_R
    d = d[~wild].copy()
    d["day"] = (d.time // 86400).astype(int)
    d["date"] = pd.to_datetime(d.time, unit="s").dt.date
    d["won"] = d.r_multiple > 0
    #: A record that finishes above its own best is impossible, and it is the
    #: only unambiguous signature of a lost excursion.
    d["lost_record"] = d.best_r < d.r_multiple.clip(lower=0.0) - 1e-9
    if wild.sum():
        print(f"dropped {int(wild.sum())} rows past |R| {MAX_ABS_R:g}\n")
    return d


def telemetry(d: pd.DataFrame) -> float:
    """Report how trustworthy `best_r` is, and return the unrecorded share.

    **This decides whether the rest of the output means anything**, so it runs
    first and prints either way.

    `best_r` is an in-process dict keyed by ticket (`service._best`), not
    restored on start, and `_reach` returns 0.0 for a ticket it cannot find -
    which its own docstring says "is how every close in the book's history once
    recorded `best_r` of exactly 0.000".

    The trap is that the damage is **correlated with the outcome**, so neither
    keeping nor dropping the bad rows is neutral:

    * dropping rows whose `best_r` is below their own result can only ever drop
      a **winner** - for a loser, `max(0, r_multiple)` is zero and `best_r` is
      never below zero - so that filter selects on winning and inflates every
      regret it then measures
    * keeping them leaves losers carrying a fabricated zero, which says the
      trade was never in front and suppresses the value of any earlier target

    There is no third option on this data. The model is correct and the
    question is unanswerable until the record is.
    """
    unrecorded = float((d.best_r == 0).mean())
    drop_by_outcome = d.groupby("won").lost_record.mean()
    print("=== is `best_r` trustworthy? ===")
    print(f"best_r == 0 on {unrecorded:.1%} of trades")
    print(f"finishes above its own best (impossible) on {d.lost_record.mean():.1%}")
    print(f"  of winners: {drop_by_outcome.get(True, 0.0):.1%}"
          f"   of losers: {drop_by_outcome.get(False, 0.0):.1%}"
          "   <- a filter on this selects on the outcome")
    worst = d.groupby("date").best_r.apply(lambda s: (s == 0).mean())
    recent = worst.tail(5)
    print("\nunrecorded share, last five days:")
    print("  " + "  ".join(f"{k} {v:.0%}" for k, v in recent.items()))
    print()
    return unrecorded


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "outcomes.csv"
    d = load(path)
    print(f"{len(d)} outcomes, {d.strategy.nunique()} strategies, "
          f"{d.day.nunique()} days\n")
    unrecorded = telemetry(d)

    rows = []
    for strategy, g in d.groupby("strategy"):
        actual = g.r_multiple.to_numpy(float)
        for rr in GRID:
            got = g.apply(counterfactual, axis=1, rr=rr)
            seen = got.notna().to_numpy()
            if seen.sum() < MIN_N:
                continue
            regret = got[seen].to_numpy(float) - actual[seen]
            mean, lo, hi = block_ci(regret, g.day.to_numpy()[seen])
            rows.append({
                "strategy": strategy,
                "rr": rr,
                "n": int(seen.sum()),
                "censored": 1.0 - seen.mean(),
                "actual_rr": float(g.reward_to_risk.median()),
                "actual_R": float(actual.mean()),
                "would_R": float(got[seen].mean()),
                "regret": mean,
                "lo": lo,
                "hi": hi,
            })
    t = pd.DataFrame(rows)
    if t.empty:
        print("nothing with enough trades")
        return
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 400)

    print("=== every cell, by strategy ===")
    print("`regret` is mean R under the proposed reward minus mean R actually taken.")
    print("`censored` is the share whose counterfactual the journal cannot see.\n")
    for strategy, g in t.groupby("strategy"):
        print(f"--- {strategy}")
        print(g.drop(columns="strategy").round(4).to_string(index=False))
        print()

    acts = t[(t.lo > 0)].sort_values("regret", ascending=False)
    if unrecorded > MAX_UNRECORDED:
        print("=== no corrections reported ===")
        print(f"`best_r` is unrecorded on {unrecorded:.1%} of trades, past the "
              f"{MAX_UNRECORDED:.0%} this will answer on, and the damage is")
        print("correlated with the outcome - see `telemetry`. Every cell above is")
        print("biased by that and none of it is a finding. Fix the record first.")
        print(f"\n({len(acts)} of {len(t)} cells would have been acted on, which is")
        print("printed only so the size of the mistake is visible.)")
    else:
        print("=== corrections whose whole interval is above zero ===")
        print(acts.round(4).to_string(index=False) if len(acts) else "none")
        print(f"\n{len(acts)} of {len(t)} cells would be acted on")

    # Written beside the other research output rather than at the repo
    # root, which is where it landed when this was first run.
    out = Path(__file__).resolve().parent.parent / "regret.csv"
    t.to_csv(out, index=False)
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
