# A market's displacement does not visit every direction, and the reason is not its tails

A random walk in three or more dimensions is **transient** - it escapes to
infinity and never returns to the origin - and yet the *angle* of its
displacement keeps turning and visits every direction infinitely often.
Transience is a statement about the radius; recurrence still holds for the
direction.

A one-dimensional price series cannot be asked that. It has no angle. The
question has teeth only in an embedding, and the natural one here is **across
instruments**: the vector of `N` instruments' log-price changes from a common
start is a direction in `R^N`, which is the case the theorem is actually about.

The harness is `research/ideas/directional_recurrence.py`.

## What makes it a test rather than a restatement

A walk's displacement direction is **asymptotically uniform on the sphere**,
because its increments are isotropic. A market's increments are not, and this
desk has measured why: three principal components carry **63.2%** of return
variance across 20 instruments and the residuals after them still correlate up
to **0.9422** along currency lines. So a market's displacement should be
**confined to a low-dimensional cone**.

**This is not the Mandelbrot critique.** The fat-tailed-marginal half of that
argument is already settled here - traded return kurtosis reads **20.07**
against the Deriv synthetics' **3.19**, where Gaussian is 3.0 - and it says
nothing about direction. A fat-tailed walk is still isotropic.

## The planted arm recovers the factor count

| planted | cells | **effective dimension** | revisited | gap | discovery |
| --- | ---: | ---: | ---: | ---: | ---: |
| isotropic walk, 8 instruments | 819 | **7.53** | 0.006 | 1.0 | 1.002 |
| one factor plus noise | 644 | **1.86** | 0.135 | 2.0 | 0.867 |
| three factors | 381 | **2.51** | 0.486 | 82.0 | 0.574 |

The effective dimension is the participation ratio of the displacement
covariance's spectrum, which is `d` for isotropic and 1 for a single direction.
It reads back the number of factors it was given, so the bins can see
confinement and the real rows are readable.

## The answer

| | cells | **effective dimension** | revisited | gap |
| --- | ---: | ---: | ---: | ---: |
| **traded** | 754 | **3.24** | **0.078** | 2 |
| walk null, traded | 817 | 7.11 | 0.007 | 1 |
| **rotation null, traded** | 818 | **7.21** | 0.007 | 1 |
| generated | 764 | 3.45 | 0.067 | 2 |
| walk null, generated | 764 | 3.23 | 0.067 | 1 |
| rotation null, generated | 772 | 3.38 | 0.058 | 1 |

**The theorem holds for a walk and fails for a market.** An eight-instrument
walk fills **7.1** effective dimensions and revisits a direction 0.7% of the
time. The traded universe fills **3.24** and revisits **7.8%** - eleven times
more often.

### And the rotation null says it is the factor structure, not the tails

The rotation null reads **7.21**, which is the walk's 7.11 within noise. A
rotation preserves each instrument's marginal *exactly* - every fat tail, all
the volatility clustering, because it is the same data - and destroys only the
cross-instrument alignment. So the confinement cannot be the tails or the
clustering. It is the factor structure.

That is the whole value of carrying both nulls: a gap to the walk null alone
would have been consistent with the tails, and the Mandelbrot reading would
have been available. The gap to the *rotation* is not.

## What the generated arm does and does not control for

The synthetics show **no gap**: 3.45 against their own nulls' 3.23 and 3.38. No
factor structure, which is right for independent generators.

But their absolute level is not comparable to the traded arm's, and the reason
is worth recording. **Effective dimension is compressed by unequal scales as
well as by correlation.** The `Volatility_*` family spans a fifteen-fold
volatility range, so the displacement is dominated by its largest members and
even an *independent* walk over that universe reads 3.23 rather than 7.1.

So every arm is judged only against its own null, never across arms. Read that
way the table is unambiguous; read across arms it would say the synthetics are
as confined as the market, which is an artefact of their scale spread.

## What to use

* **A market's direction is confined to about three of eight dimensions**, and
  it recurs eleven times more often than a walk's. Anything that assumes
  isotropy across instruments - an equal-risk allocation, a direction treated
  as free - is assuming a sphere the market does not visit.
* **Carry the rotation null beside the walk null.** They answer different
  questions, and here the difference between them *is* the finding.
* **Judge each universe against its own null.** Unequal volatilities compress
  the effective dimension on their own, so absolute levels do not travel.

## Related

* [Volatility relationships](statespace-volatility-relationships.md) - the
  factor structure this confinement is made of
* [Synthetics are a poor tail control](statespace-relationship-screen.md) - why
  the rotation null, rather than a shuffle, separates tails from structure
