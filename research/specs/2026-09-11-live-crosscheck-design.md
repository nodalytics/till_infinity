# The live cross-check

**Status:** design, 2026-09-11. Not yet approved. The last of the four
measurement pieces, and the one the exit work waits on.

## The problem

A replay and the live record disagreed, and the replay won by default.

`research/harness/sweepstops.py` replayed `sweep-aware`'s own entries under its
own exit policy and reported that **98.8% of trades ended on the stop**. The
live desk, running that policy on that strategy, ends **13%** of them on the
stop and **66% on the hold timeout**.

That is not a small gap in a performance number. It is a different machine. The
mean R figures were close - +0.032 replayed against +0.134 live - which is
exactly why nobody noticed: **the number everyone looks at agreed while the
mechanics did not.**

The consequence is already in production. `exits.py` chose `sweep-aware`'s
shipping exit on a comparison whose advantage collapsed from +0.432R to +0.046R
once two look-aheads were removed, and the corrected replay *still* exits 98% by
stop where the desk exits 13%. The kernel fixed the arithmetic. It did not make
the simulation resemble the desk.

## The insight: compare structure, not performance

The obvious check - does the replay's mean R match the live mean R - is wrong,
and would fire constantly on healthy replays. They are **different populations
by construction**: a replay walks every published call, and `risk.py` refuses
the expensive ones before they become trades. Live pays a median spread of
0.081R where the replayed population averages 0.363R. Those means *should*
differ.

What should not differ is **how trades end**. Same entries, same policy, same
instrument: the exit-kind mix, the hold duration and the distribution of
high-water marks are fingerprints of the *mechanics*, and they do not depend on
whether the strategy has an edge.

So the check compares structure. A divergence there says the simulation is not
reproducing the desk, whatever its R column says.

## What is compared

Three quantities, all of which the journal already carries per close:

| | live source | why it is structural |
| --- | --- | --- |
| **exit-kind mix** | `exit_kind` | how a trade ends is the policy's fingerprint |
| **hold duration** | `seconds` | a replay that holds 48x too long is a different trade |
| **high-water mark** | `best_r` | how far trades get before ending, independent of where they end |

The live fingerprints today, for reference and as test fixtures:

| strategy | n | exit mix | median secs | median `best_r` |
| --- | --- | --- | --- | --- |
| thesis-only | 190 | hold 38% target 34% stop 16% stale 12% | 640 | +0.000 |
| sweep-aware | 83 | hold 66% stop 13% ? 8% target 7% | 381 | +0.391 |
| runner | 33 | hold 61% stop 27% stale 9% target 3% | 1536 | +0.000 |
| snap | 29 | hold 48% stop 38% target 14% | 114 | +0.000 |
| confluence-scalp | 11 | hold 55% stop 36% target 9% | 1035 | +0.207 |

Two things that table exposes before any replay is compared to it:

* **`stale` is an exit kind the replay cannot produce at all.** It is 12% of
  `thesis-only` and 9% of `runner`. A simulation with three possible endings
  being compared to a desk with four is a structural mismatch that exists before
  any bar is walked.
* **`?` is 8% of `sweep-aware` and 20% of `fade-to-value`** - closes whose
  `exit_kind` was never recorded. That is a liveness problem in the field the
  check depends on, and the check has to report it rather than silently treat
  unknown as a fourth category.

## The verdict, and what a harness does with it

**Label the result, loudly.** The replay still runs and still reports; every
conclusion carries a verdict line at the top of its output:

    CROSS-CHECK: this replay does NOT reproduce the live mechanics.
      exit mix   stop 98.8% vs 13%, hold 0.1% vs 66%   (max gap 86 points)
      hold secs  median 1800 vs 381                     (4.7x)
      live n=83 sweep-aware closes
    Conclusions below describe a desk that does not exist.

Not a refusal. Sometimes a population the desk does not take is exactly what is
being studied - `spikeside.py` deliberately replayed every level call on six
feeds - and a check that blocked that would be worked around rather than read.

What it removes is the case where nobody compared.

## Thresholds

**Exit mix: 25 points** on any single kind. Justified by the observed case,
which was 86 points and 66 points on two kinds - a threshold at 25 catches it
three times over while leaving room for the ordinary difference between a
replay's population and the desk's.

**Hold duration: 2x** on the median. The observed case was 4.7x, and the
underlying error was a harness holding 1,440 bars where the desk holds 30.

**High-water mark: reported, not thresholded.** `best_r` reads 0.000 as a median
on four of the six strategies above, so the field is not yet reliable enough to
gate on. It is printed because it is the quantity the exit work turns on, and
because printing it is how anybody finds out when it becomes reliable.

**Below 30 live closes: no verdict.** It reports the counts and says
`too few live closes to compare`. `confluence-scalp` at n=11 and `opportunity`
at n=5 are exactly the cases where a threshold would fire on noise - the same
argument `strata.min_n` makes, and the same resolution: report, do not judge.

## Design

`till_infinity/shared/crosscheck.py`, in the package for the reason the replay
kernel and `strata` are: `research/` has no lint gate and no test gate.

```python
def fingerprint(rows: Iterable[Mapping[str, Any]]) -> Fingerprint:
    """Exit mix, hold duration and high-water mark from closes."""

def agree(replayed: Fingerprint, live: Fingerprint) -> Verdict:
    """Whether the replay reproduces the desk, and where it does not."""
```

`Fingerprint` is built from either source - replayed `(r, kind)` pairs or
journal outcome contexts - so the two sides are constructed by the same code and
cannot drift in how they count. `Verdict` renders to the block above and carries
`reproduces: bool`, the per-quantity gaps, and `judged: bool` for the small
sample case.

A loader reads live closes from the journal by strategy, which the harnesses
already do by hand in four places.

## Testing

1. The observed case as a fixture: 98.8% stop replayed against 13% live returns
   `reproduces=False` and names the exit mix as the largest divergence.
2. A replay whose mix matches within tolerance returns `reproduces=True`.
3. Fewer than 30 live closes returns `judged=False` and no verdict - and the
   counts are still in the output.
4. An exit kind present live and impossible in the replay (`stale`) is reported
   as a structural mismatch rather than as a percentage gap, because the replay
   cannot produce it at any rate.
5. Closes with no `exit_kind` are counted and reported separately, not folded
   into a category.
6. Mean R deliberately differing while the structure matches returns
   `reproduces=True` - the check must not fire on the thing it exists to ignore.

## What it does not fix

It says a replay does not resemble the desk. It does not say **which** is right,
and it cannot: a replay may diverge because it is broken, or because it is
deliberately studying a different population, and only the person who wrote it
knows which.

Nor does it validate a replay that passes. Matching the exit mix is necessary
and not sufficient - the two look-aheads found on 2026-09-11 would both have
produced a plausible mix while paying prices the market never offered. **This is
a check on resemblance, not on honesty**, and the kernel remains the answer to
the second.

## Why this unblocks the exit work

`research/giveback.md` records that `sweep-aware` keeps **27%** of its
high-water mark, that its break-even sits at 1.0R against a median peak of
0.445R, and that its trail is uncapped at a measured maximum of 2,239v. Two
changes follow from that arithmetic and neither has been made, because the only
harness that could verify them is the one that exits 98% by stop where the desk
exits 13%.

With the cross-check, that harness is labelled rather than trusted, and the
verification moves to where the effect is visible: the live `best_r`
distribution before and after. That is the next spec, and it is short once this
one exists.
