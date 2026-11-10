# The stop band over more than one bar: `sqrt(q)` understates it

`risk/forecast.band(f, bars=q)` is the one-bar Student-t band times `sqrt(q)`,
and its docstring said **`bars` above one is unmeasured**. This is the
measurement. 31 traded instruments and 4 Deriv indices at 15m from the lab's
`seqlab` store, the shipped `RangeForecast` fed bar by bar, horizons
q = 2, 5, 10, 20, 48, 96 - 48 and 96 being the holds the traded rules carry,
since `structure.HOLD_MINUTES // 15` is **96**.

## The answer

Taking `student_stop(0.90, 4) * sqrt(q) * f` as the band, the **multiplier it
would need** is the 0.90 quantile of the realised q-bar excursion in units of
the forecast, over that band. One means `sqrt(q)` is right.

| q | needed, median of 31 | min | max |
| ---: | ---: | ---: | ---: |
| 2 | **0.950** | 0.838 | **0.995** |
| 5 | 1.014 | 0.837 | 1.125 |
| 10 | 1.062 | 0.839 | 1.230 |
| 20 | 1.082 | 0.839 | 1.195 |
| 48 | **1.153** | 0.835 | 1.395 |
| 96 | 1.105 | 0.828 | 1.358 |

**At one to two bars the shipped band is right, and no instrument needs more**
- the maximum over 31 is 0.995. That is an independent reproduction of
`no-gaussian-band-is-calibrated`, which found the Student-t one-bar band
holding on 64 of 64 cells out of sample.

**From about five bars up it understates, and the shortfall grows with the
horizon**: about 6% at ten bars, 8% at twenty, **15% at forty-eight**.

## So `bars > 1` stays off, and that is now a measured decision

The band is a **floor**, so the two errors are not symmetric: too tight and a
rule trades at a distance it was never measured at, too wide and every rule's
stop moves, which changes every rule's expectancy -
`reproduce-the-baseline-before-an-increment` is the standing warning. The
per-instrument spread at q=48 is **0.835 to 1.395**, so one pooled factor of
1.153 would widen the tightest instrument's stop by 38% more than it needs.
`pooled-medians-invert-subgroups` is the reason that is not a detail.

A multi-bar floor is therefore shippable only with a **per-instrument** factor
measured from that instrument's own history. `sqrt(q)` with no factor is not,
and neither is `sqrt(q)` with one constant.

## The variance ratio is the wrong statistic for this, and says so

`VR(q) = Var(r(q)) / (q Var(r))` was the obvious test and it points the other
way. Real 15m closes, median over 31 instruments, with Lo-MacKinlay's
heteroskedasticity-robust `z*`:

| q | median VR | median `z*` |
| ---: | ---: | ---: |
| 2 | 0.975 | -2.51 |
| 5 | 0.942 | -2.80 |
| 10 | 0.911 | -2.95 |
| 20 | 0.881 | -3.01 |
| 48 | 0.868 | -2.30 |

Terminal variance grows **slower** than `q`. Read alone that licenses scaling
the band by *less* than `sqrt(q)` - the opposite of what a stop needs.

Both are true, and the reason is that **a stop is a barrier, not a terminal
distribution**: price ends up closer than `sqrt(q)` suggests and travels
further on the way, and only the second thing fills a stop. The 15% at q=48 is
the number that matters and the VR is the number that would have been quoted.

## Three control failures, all in this harness

Reported because each was caught by a control behaving impossibly, and the
third is the one worth copying.

1. **The robust `z*` read -0.00 on every row.** Lo-MacKinlay's `delta(j)` is
   already `O(1/n)`; multiplying by `n` made the null variance `O(1)` and the
   statistic could not reject anything.
2. **The iid arm's touch multiplier fell 0.99 to 0.86 across q**, and the arm
   must be flat. The synthetic arms re-hang the *real* bar ranges on a
   synthetic close path, so their highs and lows do not scale with their own
   steps. A close-only excursion column was added for the arm comparison and
   the touch column kept for the real series.
3. **The iid control was one realisation counted 31 times.**
   `default_rng(SEED)` sat inside the per-instrument loop, so every instrument
   drew the identical normal sequence - and `VR` is scale-invariant, so AUDCAD
   and GBPJPY printed byte-identical `0.999 0.981 0.955 0.924 0.903 0.888` and
   `-0.15 -1.19 -1.88 -2.17 -1.75 -1.41`. "23 of 31 cells at `z* < -2`" was one
   cell, 31 times. Fixed with a per-instrument seed and 5 replicates per arm.
   **Two identical rows in a control arm is the cheapest tell there is.**

## What is still not attributed

Even close-only, the iid arm reads 0.720 at q=2 rising to 0.821 at q=96 rather
than flat, because `f` is still the EWMA of **real** re-hung ranges while the
closes are its own - the same incoherence as (2), one level further in. So the
arms cannot yet say how much of the real growth is volatility clustering and
how much is the marginal's tails. The real-arm table above needs no surrogate
and is unaffected.

The replacement arm is the one `entry_timing.py` built for the same reason: each
bar a bridge of sub-steps pinned to a real step, so `open == previous close`
and the highs and lows are the path's own. Attribution is worth having and it
does not change the shipping decision.

## Re-running

    ./.secrets/lab.sh run research/ideas/variance_ratio.py
    ./.secrets/lab.sh log variance_ratio
