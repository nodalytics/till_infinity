# Every published pivot formula is one object: a weighted centre plus a multiple of the prior range

Asked on 2026-10-14: *checkout the formulas for calculating supports and
resistance levels online as well as pivots too, so we can review them and see
how we can create statespace versions of them.*

`structures/drawing/pivots.py` publishes **Classic** pivots only, on daily and
weekly sessions. Woodie, Camarilla, DeMark and Fibonacci are absent. The
formulas are below as the sources give them, with the disagreements marked,
followed by the thing worth noticing about all of them.

## The formulas, as published

Prior session's high `H`, low `L`, close `C`, open `O`; `Range = H - L`.

| family | centre | levels |
| --- | --- | --- |
| **Classic** (in production) | `(H+L+C)/3` | `R1 = 2PP-L`, `R2 = PP+Range`, `R3 = H+2(PP-L)`; S mirrored |
| **Woodie** | `(H+L+2C)/4` | `R1 = 2PP-L`, `R2 = PP+Range`; S mirrored |
| **Fibonacci** | `(H+L+C)/3` | `PP ± 0.382·Range`, `± 0.618·Range`, `± 1.000·Range` |
| **Camarilla** | `C` | `C ± Range·1.1/12`, `·1.1/6`, `·1.1/4`, `·1.1/2` |
| **DeMark** | `X/4` | `R1 = X/2 - L`, `S1 = X/2 - H` |

DeMark's `X` is the only asymmetric one: `X = H + 2L + C` when `C < O`,
`2H + L + C` when `C > O`, and `H + L + 2C` when they are equal. The branch is
the point - it leans the level toward the side the session closed away from.

Camarilla's `1.1/n` notation causes trouble and is widely misread. It resolves
to multipliers of **0.0917, 0.1833, 0.2750 and 0.5500**.

**Where the sources disagree, and it matters:**

- **Woodie's input.** Most sources give `(H+L+2C)/4`; others give
  `(H+L+2·today's open)/4`. These are different objects - the second needs the
  session to have opened, so it is not knowable in advance, which breaks the
  one property `pivots.py` values pivots for.
- **Camarilla's fifth rung.** `H5 = H/L` in one source, `(H/L)·C` in another.
  The first is dimensionally wrong - a ratio is not a price.
- **DeMark.** One guide gives `(H+L+2C)/4`, which is Woodie's formula, not
  DeMark's. Treat it as unreliable.

## What they all are

Written out, every family is the same expression:

    level = w·[H, L, C, O] ± k·(H - L)

a weighted centre plus a multiple of the prior range. The families differ only
in `w` and `k`:

| | centre weights | spread multipliers |
| --- | --- | --- |
| Classic | `(1,1,1,0)/3` | `k` implied by `2PP-L`, then `1.0`, then `~2` |
| Woodie | `(1,1,2,0)/4` | `1.0` |
| Fibonacci | `(1,1,1,0)/3` | `0.382, 0.618, 1.000` |
| Camarilla | `(0,0,1,0)` | `0.0917, 0.1833, 0.2750, 0.5500` |
| DeMark | branch on `C` vs `O` | `0.5` on the branched sum |

That is **a point estimate of value plus a scaled uncertainty band**, which is
what `facade.Desk.read()` already publishes. So there is no new formula to
write - the families are special cases of something statespace emits natively,
with two parts worth separating.

## The spread they chose is the one this desk just measured as better

Every family uses `H - L` for its spread. That is the **Parkinson** estimator,
and `candle-screen.md` measured the range-based family against close-to-close
on the question of what volatility does next: AUC **0.6484** within strata of
current volatility on twenty FX feeds at 100% sign agreement, and **0.6671** on
equities with **371 of 392** instruments agreeing - rising as the window
shortens, which is the regime a filter's `Q(dt)` update lives in.

Statespace currently drives `Q` from close-to-close returns. The pivot
families have used the better proxy since the 1930s floor. That is one point
to them and a concrete change here, already written up in #226.

## The multipliers are the part to replace

`0.382`, `0.618`, `0.55`, `1.1/12` are constants standing in for quantiles of a
predictive distribution. They cannot adapt to an instrument, a session, or a
volatility regime, and nothing in their provenance is a measurement.

A state space has the distribution. `no-gaussian-band-is-calibrated` says
nothing beats the walk on CRPS, so its quantiles are the best-calibrated band
available here - which makes the statespace version of this whole family:

    centre  = the filtered state, as `Readout.mean`
    level_q = centre ± quantile(q) of the predictive distribution

with `q` chosen to match what each published multiplier was reaching for -
0.382 of a range is roughly a 30th-to-70th percentile band, 1.1/2 is roughly
the 90th. The result is calibrated by construction, adapts per instrument, and
unlike a constant it can be **wrong in a measurable way**.

## The test, which decides whether any of it earns its place

The question is not whether a statespace pivot is prettier. It is whether a
calibrated quantile beats a hand-chosen constant at the only thing a level has
to do. The harness exists:

1. **Nominate** both - the published families and the quantile versions - as
   prices, from the same prior session.
2. **Race each against a distance-matched placebo** through the identical
   detector, which is what `level_signatures.py` does, with anchors spaced a
   full horizon apart so no two decisions share a bar of outcome.
3. **Gate on `Range_Break_100/200`**, whose generator has a boundary by
   construction. A nomination that cannot find the boundary of a process built
   to have one does not get read on FX.
4. **Report the trap and backcheck rates per nomination**, which
   `outcome-prediction.md` found are the two outcomes that are predictable at
   all - `strength` and `experience` for a break, `confluence_n` for a
   backcheck at 0.6140.

The expected answer is that none of them beats a placebo, because seventeen
level constructions already have not and neither did topological prominence.
**Pivots are the interesting exception to try anyway**, for the reason
`pivots.py` already states in its docstring: their power is partly
self-fulfilling. Enough people watch `R1` that it does not need the formula to
mean anything - and that is a hypothesis about **which** nominations are
watched, not about which arithmetic is right, so Classic and Camarilla being
popular is the prediction, not Fibonacci being principled.

## Measured: no family beats a matched placebo

Every variant above, including the disputed ones, nominated from the prior
session and raced over the next - one decision a session, so no two share a bar
- against a placebo at the same distance from the session open:

| family | touched | hold rate | placebo | diff |
| --- | ---: | ---: | ---: | ---: |
| camarilla | 104,897 | 0.5109 | 0.5108 | +0.0001 |
| demark | 33,819 | 0.5123 | 0.5119 | +0.0004 |
| woodie_close | 39,428 | 0.5079 | 0.5070 | +0.0009 |
| classic | 41,187 | 0.5070 | 0.5082 | -0.0012 |
| woodie_open | 39,479 | 0.5073 | 0.5081 | -0.0008 |
| fibonacci | 58,066 | 0.5073 | 0.5096 | -0.0023 |
| demark_mistranscribed | 32,941 | 0.5092 | 0.5118 | -0.0026 |
| camarilla_h5_scaled | 6,355 | 0.5057 | 0.5158 | -0.0100 |

Nothing clears its placebo by more than a tenth of a percentage point, in
either direction. The self-fulfilling argument - that `R1` works because people
watch it - predicts Classic and Camarilla outperforming, and they do not.

`camarilla_h5_ratio` is **absent from the table**, which is the result for it:
`H5 = H/L` is about 1.0013 on EURUSD while price is near 1.09, so it is never
reached. A dimensionally wrong level shows up as never touched.

**And the control did not work as built.** `demark_mistranscribed` is Woodie's
formula and should have scored identically to `woodie_close`. It did not -
0.5092 against 0.5079 - because the first nominates three levels and the second
five, so the aggregates cover different level sets. The shared levels agree; the
check has to be per-level-name to mean anything. Worth fixing before the next
run leans on it.

## Wyckoff and Elliott, as the one falsifiable piece each

Neither is arithmetic on a session, so neither reviews the way pivots do. Both
are models, and each maps onto a module that already exists.

**Wyckoff is a hidden Markov model.** Four phases with transitions, observed
through price and volume jointly, which is `hmm.py` and `switching.py`. Its
mechanic - effort against result - is a two-channel observation model, and the
activity clock here already absorbs 76% of the Q clock into volume time.

Tested as a conditional: at the end of a zigzag leg, does effort-to-result
predict whether the next leg is **bigger**? AUC **0.5693** on twelve traded
feeds at 100% sign agreement - and **0.5791 on the same bars block-shuffled**,
also at 100%. Unanimity in both arms is the tell. The cause is in the
construction: `effort` divides volume by distance travelled, so a small leg
inflates effort **and** makes "next leg bigger" more likely. Leg-size mean
reversion, built in.

**Elliott is a constrained changepoint segmentation**, which is
`changepoint.py` with rules attached. Its real problem is identifiability - the
rule set can label almost any path - so "does the count work" has no answer.
One component is falsifiable without any counter: **the Fibonacci ratios
between consecutive legs**.

68,796 legs across twelve feeds, three zigzag thresholds, density within 5% of
each named ratio against the same bars shuffled:

| ratio | real | shuffled | lift | feeds agreeing |
| ---: | ---: | ---: | ---: | --- |
| 0.382 | 0.0245 | 0.0242 | +0.0003 | 58% |
| 0.618 | 0.0391 | 0.0372 | +0.0019 | 75% |
| 1.000 | 0.0489 | 0.0479 | +0.0010 | 67% |
| 1.618 | 0.0388 | 0.0377 | +0.0010 | 67% |
| 2.618 | 0.0252 | 0.0264 | -0.0012 | 17% |

No clustering. A 5% window around 0.618 covers about 6% of the plausible ratio
range and catches 3.9% of ratios, which is roughly uniform. The largest lift
anywhere is at ratio **1.000** (+0.0045 at the widest threshold), and that is a
property of the detector: a fixed-threshold zigzag bounds leg size from below,
so equal legs are over-represented by construction.

The zigzag itself is worth a note. Its first version initialised direction to
zero, which left both tracking branches live, set the running extreme to the
current price on every bar, and made the turn condition unreachable - zero legs
from forty thousand bars at every threshold. A silent zero is the good kind of
failure.

## Benner, and why it is not testable here

Samuel Benner's 1875 chart is a **fixed-period calendar cycle** - 7, 9 and 11
years - with no data input at all. In these terms it is the degenerate case of
`spectrum.py`: a periodogram with the period pinned instead of estimated.

The longest history in the cache is daily EURUSD and USDJPY, **1971 to 2026**.
Fifty-five years is about **six repetitions** of a nine-year cycle, so a "was
this a turning year" test has roughly six events, and a spectral estimate at
that frequency carries a standard error about equal to its own value. To reject
at the five percent level on six events the cycle would have to be very nearly
deterministic.

So the honest answer is that this desk cannot test Benner, and the number that
says so is six. Reporting a null from six events would be reporting the sample
size. What *is* available is the periodogram of 55 years of daily data with its
confidence band attached - informative about where power is not, and not a test
of the claim.

## Sources

- [Pivot points, CrossTrade](https://crosstrade.io/learn/technical-indicators/pivot-points) - Classic and Woodie
- [The Camarilla Equation Explained, PivotBoss](https://pivotboss.com/2010/05/31/the-camarilla-equation-explained/) - the `1.1/n` rungs
- [Camarilla, LuxAlgo](https://www.luxalgo.com/library/concept/camarilla/)
- [DeMark Pivots, LuxAlgo](https://www.luxalgo.com/library/concept/demark-pivots/) - the `C` against `O` branch
- [Standard Pivot Point formulas, ActionForex](https://www.actionforex.com/?p=629083)
- [Pivot Points: Definition, Formula & Calculation, Strike](https://www.strike.money/technical-analysis/pivot-points) - Fibonacci ratios
