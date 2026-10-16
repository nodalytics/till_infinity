# The inside-bar residual is the trading day, plus a small unpredictable burst

**Measured 2026-10-16.** Code: [`inside_clock.py`](../ideas/inside_clock.py).
Eleven asset classes on 1h bars, four permutation arms and a block-length
sweep, then four mechanisms simulated on top of the family each class had
already picked.

[`family-fits.md`](family-fits.md) closed the gap between a market and a
process family with a mean-reverting sub-bar term, and left one residual
leading on every traded class: **`inside bar`** at `z` 4.9 to 13.7, markets
reading 0.149 to 0.194 where the fitted families gave 0.126 to 0.135. This is
that residual.

## An inside bar is a joint event, not a size

A bar is inside its predecessor when `high <= prior high` and
`low >= prior low`. The child opens at the parent's close, so it needs two
things at once: the parent must close away from its own extremes, and the child
must be small. The rate therefore couples the parent's **shape** to the child's
**size**, and three sources could produce it - the dispersion of bar sizes with
no dependence at all, a deterministic hour-of-day cycle, or genuine
bar-to-bar coupling.

## The arms, and the sign that was wrong first

Each bar is reduced to its own geometry in logs - the gap into it, the reach
above and below its open, its body - and the series is rebuilt from those
tuples in a new order, chaining each open onto the previous close. Every bar
keeps its exact shape, so the detector never sees a different kind of bar.

A planted smooth 24-bar cycle of span 10 was put through the arms before any
market was touched, and it read `real` 0.182, `by hour` 0.139, `shuffled`
0.242. **The clock lowered the inside rate**, and the full shuffle was the
highest of the three - because a smooth cycle makes neighbouring bars *similar
in size* and nesting needs a difference. Any positive dependence in bar size,
a cycle or volatility clustering alike, suppresses nesting relative to free
draws from the same marginal. So `shuffled` is an upper bound, not a baseline,
and the registered prediction that followed from the wrong sign - that markets
would look burst-like, with `real` close to `shuffled` - is refuted below.

## What the markets read

| class | pairs | real | by hour | shuffled | no gap | order | hour |
|---|---:|---:|---:|---:|---:|---:|---:|
| fx majors | 39,314 | 0.150 | 0.174 | 0.198 | 0.148 | **0.048** | 0.024 |
| fx crosses | 39,314 | 0.156 | 0.189 | 0.209 | 0.155 | **0.053** | 0.021 |
| metals | 36,478 | 0.168 | 0.198 | 0.218 | 0.166 | **0.049** | 0.020 |
| indices | 14,492 | 0.162 | 0.189 | 0.207 | 0.158 | **0.046** | 0.018 |
| energy | 14,687 | 0.155 | 0.198 | 0.226 | 0.152 | **0.072** | 0.028 |
| baskets | 34,372 | 0.140 | 0.174 | 0.199 | 0.141 | **0.058** | 0.025 |
| volatility (Deriv) | 36,332 | 0.101 | 0.101 | 0.100 | 0.101 | −0.000 | −0.000 |
| step | 30,696 | 0.106 | 0.101 | 0.101 | 0.102 | −0.005 | −0.000 |
| boom | 17,835 | 0.111 | 0.112 | 0.111 | 0.111 | −0.001 | −0.001 |
| jump | 39,998 | 0.106 | 0.107 | 0.107 | 0.105 | 0.001 | 0.000 |

`order` is `shuffled − real`, the suppression the ordering buys; `hour` is the
part the hour-of-day profile alone accounts for.

**The Deriv feeds control it exactly.** No session, no auction, a constant tick
rate - and `order` of −0.005 to +0.001 against 0.046 to 0.072 on everything
traded. The method reads zero where there is nothing to read.

Two other arms came out worth having:

- **the gap arm is null.** Zeroing every close-to-open move changes the rate by
  0.002 on every market, where it was worth 0.037 on the toy. Whatever the
  bid-ask bounce does to a bar's shape, it is not visible here.
- **the hour profile carries between a third and a half** of the suppression -
  0.018 to 0.028 of 0.046 to 0.072 - which is a large share for a term that is
  deterministic and knowable in advance.

## The horizon: all of it lives inside six bars

Blocks of `n` bars kept intact and reordered, so reading left to right is
reading the dependence away:

| class | real | b2 | b6 | b24 | b120 | shuffled |
|---|---:|---:|---:|---:|---:|---:|
| fx majors | 0.150 | 0.175 | 0.158 | 0.151 | 0.149 | 0.198 |
| fx crosses | 0.156 | 0.183 | 0.165 | 0.158 | 0.155 | 0.209 |
| metals | 0.168 | 0.192 | 0.174 | 0.167 | 0.166 | 0.218 |
| energy | 0.155 | 0.191 | 0.166 | 0.156 | 0.154 | 0.226 |
| baskets | 0.140 | 0.170 | 0.148 | 0.141 | 0.140 | 0.199 |
| volatility (Deriv) | 0.101 | 0.100 | 0.101 | 0.101 | 0.101 | 0.100 |

**Reordering whole days or whole weeks changes nothing** - `b24` and `b120` sit
on the real value - and blocks of six are already within 0.008 of it. The
dependence that suppresses nesting is a two-to-six bar neighbourhood effect,
not a multi-day volatility regime. A slow regime story was available and the
data declines it.

## The marginal the fingerprint never measured

| class | reach 90/10 | span | hours traded |
|---|---:|---:|---:|
| energy | **6.66** | 4.42 | 24 |
| indices | 5.44 | 4.25 | 24 |
| metals | 5.38 | 3.71 | 24 |
| fx crosses | 5.04 | 2.42 | 24 |
| baskets | 4.77 | 3.02 | 24 |
| fx majors | 4.72 | 3.41 | 24 |
| softs | 4.18 | 3.20 | **11** |
| Deriv families | 2.14-2.35 | 1.04-1.06 | 24 |

The reach's 90th percentile over its 10th is **4.7 to 6.7** on traded classes
and 2.6 to 3.1 on every fitted family. The fingerprint carried the kurtosis of
the return and the autocorrelation of its size and nothing about how spread out
a bar's **reach** is, which is the quantity nesting actually depends on. A
market's bar sizes are twice as spread out as any fitted process's *and*
strongly dependent, and the two pull the inside rate in opposite directions -
which is why the level alone was the wrong thing to chase.

`span`, the busiest hour's median reach over the quietest's, is 2.4 to 5.0 on
traded classes and 1.04 to 1.06 on the Deriv feeds. **It is a measurement and
not a parameter**, so the mechanism below is calibrated from it rather than
fitted to it.

## Softs are session-limited, not a counterexample

Softs read `order` −0.016, the only traded class with the sign the other way,
and they trade **11 of the 24 hours**. A class with a session has no hour-of-day
cycle to speak of, its `quiet`/`busy` split compares two different market
states, and its 4,470 usable pairs are a tenth of fx majors'. The first pass
made this worse by reading `real` on contiguous pairs while the permutations
ran on every pair; both arms now use only bars whose incoming gap is a real
one, which moved softs from −0.033 to −0.016 and left every 24-hour class
within 0.002. Nothing here is read off softs.

## After a reversing bar, the market does not compress

Inside rate in terciles of the **parent's** body share, against the shuffled
arm in the same cells:

| class | low body | shuf | mid | shuf | high body | shuf |
|---|---:|---:|---:|---:|---:|---:|
| fx majors | 0.139 | 0.206 | 0.168 | 0.220 | 0.146 | 0.170 |
| metals | 0.154 | 0.219 | 0.194 | 0.239 | 0.159 | 0.187 |
| energy | 0.144 | 0.238 | 0.179 | 0.247 | 0.141 | 0.200 |
| volatility (Deriv) | 0.081 | 0.081 | 0.118 | 0.118 | 0.104 | 0.103 |

The suppression is **largest after a low-body-share parent** - a wide reversing
bar - at −0.067 to −0.094, and smallest after a decisive one at −0.024 to
−0.059. A bar that reverses within itself is followed by a bar that breaks its
range, not by compression. On the Deriv feeds the two arms agree in every cell
to 0.001. The consolidation reading of an inside bar survives as a description
and not as a mechanism.

## The mechanism: the measured cycle, plus a mild burst

Each class's cycle amplitude is **calibrated** from its own span, `a = ln(S)/2`
in an `exp(a cos)` factor over 24 bars, and only what sits on top of it is
swept. A mechanism has to land on four numbers at once:

| fx majors | inside | order | 90/10 | span | distance |
|---|---:|---:|---:|---:|---:|
| **the class reads** | **0.150** | **+0.048** | **4.72** | **3.41** | - |
| family as fitted | 0.127 | −0.006 | 2.64 | 1.09 | 12.2 |
| cycle alone | 0.131 | +0.043 | 4.52 | 3.43 | 11.0 |
| cycle + burst(8) | 0.146 | +0.032 | 4.87 | 3.49 | **4.6** |
| cycle + burst(3) | 0.168 | +0.020 | 5.54 | 3.55 | 13.4 |
| cycle + slow(0.6) | 0.132 | +0.053 | 5.46 | 3.48 | 22.9 |
| burst(8) alone | 0.143 | −0.011 | 2.95 | 1.10 | 4.9 |

**The calibrated cycle alone reproduces the suppression and the dispersion.**
One amplitude, read off the data rather than fitted, lands `order` at +0.043
against +0.048 and 90/10 at 4.52 against 4.72. It leaves the level short by
0.019, and a mild i.i.d. activity burst - a gamma multiplier of shape 8, a 35%
coefficient of variation in a bar's activity - closes that: 0.146 against
0.150.

`cycle + burst(8)` is the best of the four on **six of seven** traded classes:
fx majors 12.2 → 4.6, fx crosses 18.3 → 4.2, baskets 6.7 → 4.5, metals
7.9 → 3.4, indices 10.2 → 4.7, energy 10.3 → 5.9. Softs, session-limited,
decline to be fitted by anything.

Neither term is sufficient and they are not interchangeable: a burst alone
reaches the level with `order` at **−0.011**, the opposite sign to every
market; the cycle alone reaches `order` and leaves the level short. The two
cannot both be exact at these parameters - adding the burst costs 0.011 to
0.016 of the suppression - which is a trade a joint fit would have to make.

## Three cautions on the numbers above

- **The distance column is unstable.** `none` reads 12.2 here where
  `family-fits.md` had 4.8 for the same family at the same parameters, on
  different draws. It is a ratio of noisy quantities at four replicates, so it
  ranks mechanisms within one table and does not compare across runs.
- **Kurtosis is barely penalised by it.** The `joint`-based classes read 240 to
  1,025 against a market's 47 to 74, because kurtosis's own replicate spread is
  enormous and the distance divides by it. Those readings are not credible and
  the metals/indices/energy rankings inherit that.
- **A block of 24 is not exactly a day** on a series with weekend seams, so the
  horizon sweep separates scales rather than naming them precisely.

## What this says beyond the residual

The suppression is 0.046 to 0.072 of inside-bar rate and between a third and a
half of it is the **hour of the day**, which is the one term here that is known
before the bar opens. `seasonality-belongs-on-q` already put the intraday
pattern in volatility and drove `Q` squared with it; this says the same cycle
is also what makes consecutive bars nest or not, which is a shape consequence
of a volatility fact.

For nulls, the consequence is sharper than `family-fits.md`'s. A synthetic null
built by generating returns and assembling bars has `order` ≈ 0 by
construction: it cannot suppress nesting because nothing in it makes
neighbouring bars similar. Any study whose statistic reads a **pair** of bars -
inside bars, engulfings, two-bar reversals, three-bar imbalances - is therefore
compared against a null that nests 0.05 too often on an absolute rate of 0.15,
which is a third of the quantity. The fix is cheap and is now measured: carry
the instrument's own hour-of-day reach profile into the generator.
