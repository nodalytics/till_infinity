# How late is the momentum reading?

The concern is concrete. Confirm halfway through a swing and the entry is
halfway worse while the stop, anchored on structure, has not moved - the same
idea taken at worse reward for identical risk.

Harness: [`harness/lateness.py`](harness/lateness.py). Replays
`structures.cusum.Ensemble` over stored 1m bars, finds every move of 1.5v or
more, and records how far into it each reading first speaks.

## The first attempt was wrong, and wrong in a way worth recording

It invented its own volatility unit - the median absolute 1m step - and
produced a "typical push" of **17.27v** for gold, which pinned that feed's
threshold to the ceiling and made the filter look hopelessly late. The unit was
wrong, so everything denominated in it was wrong.

The corrected harness uses `structures.volatility.Volatility`, warmed on the
same series, and takes the typical push from the journal's realised `push_vol`.
The pushes then land at 1.66-2.50v, matching what production measures.

## What it says

Thresholds 0.58-0.87v, from `adaptive_threshold`.

| feed | agreement ≥ 0.5 | still ahead | first event | still ahead | events spoke |
| --- | --- | --- | --- | --- | --- |
| audjpy | 44% | **56%** | 41% | **59%** | 100% |
| btc | 32% | **68%** | 54% | 46% | 100% |
| us100 | 69% | 31% | 100% | 0% | 100% |
| eurusd | 5% | 95% | 100% | 0% | 100% |

On the slower feeds the filter speaks with **half the move still ahead**, which
is not late. On the faster ones the first event lands at the very end.

## The lever is cadence, not the threshold

The failures above are not magnitude failures. A 1.5v move on eurusd completes
in a handful of minutes, and the ensemble samples members at 1m, 3m, 5m and
15m - so the slower members never see two prices inside the move and cannot
form an opinion at all. Lowering the threshold does not help a member that has
no samples.

`agreement` spoke in only 6.9% of eurusd moves for the same reason. Where it
does speak it is early: 5% into the move, 95% still ahead.

So the honest reading is that the adaptive threshold fixed the magnitude
problem it was aimed at - the old fixed 2.0v was silent through 47.5% of moves
and confirmed as they ended - and exposed a second, separate one: **on fast
instruments the ensemble cannot warm inside the move it is meant to time.**
Faster members are the fix, and that is unbuilt and unmeasured.

## A data bug found on the way

The harness's per-venue scan turned up `FOREXCOM` quoting oil in **cents**:
`USOIL` at 8047-8397 against 80-85 everywhere else, `UKOIL` at 8516-8891
against 85-92. A clean factor of 100, in 70,402 stored wti quotes and 61,924
brent ones, on two instruments that were being traded.

Both tickers are dropped, and `structures.service.SCALE_LIMIT` now removes any
venue more than 2x from the group median before taking it - a real
disagreement between venues is basis points, so there is no band where that
has to guess.
