# statespace: the volatility ceiling, and two corrections to it

Extracted from `statespace/README.md` on 2026-10-11. Volatility is the one quantity measured as forecastable in this work, so it is where the effort belongs - and the first two attempts to size the opportunity were both wrong, in opposite directions. Both corrections are kept with the measurement that forced them.

## Correcting "87% of the volatility is on the table". It was about 36%, and it is now 21%

`research/ideas/volatility_ceiling.py`, 2026-10-11. **This corrects a claim made
twice in this file and once in a merged commit message**, and the error is the
same shape as the others here: the wrong denominator.

### What was wrong

The oracle harness ranked bars by the **realised** future move and found that a
twenty-bar mean absolute move captured 10.7% of that spread. I read the
remaining 89% as available. It is not.

A realised move is `sigma * z` where `z` is a fresh standard normal. **`z` is
unforecastable by construction**, so even perfect knowledge of `sigma` cannot
reproduce an ordering built from `sigma * z` - and the dispersion of `|z|`
dominates. Measured by simulation, taking a fitted `sigma` as if it were truth:

**a perfect `sigma` forecast captures 10.8% of the realised-move oracle on
eurusd 15m, and 9.5% at 1h.**

So the oracle's ceiling was almost entirely irreducible noise, and the baseline
was never at 11% of what is achievable - it was at **64%** of it.

### Against the honest denominator

Share of what a perfect `sigma` could capture, eurusd:

| estimator | 15m h=1 | 15m h=20 | 1h h=1 |
| --- | ---: | ---: | ---: |
| baseline, mean `\|r\|` over 20 bars | 64% | 44% | 24% |
| realised variance, same window | 65% | 41% | 23% |
| EWMA, `lambda = 0.94` | 61% | 39% | 38% |
| Parkinson, high-low | 67% | 43% | 28% |
| Garman-Klass, OHLC | 66% | 44% | 30% |
| HAR, 5/22/110 closes | 72% | 47% | 44% |
| **HAR-Parkinson** | **79%** | **53%** | **53%** |
| Amihud, `\|r\|/volume` | -1% | -1% | 8% |
| Roll implied spread | 36% | 23% | 16% |

### What actually improves it

**Multi-scale blending is the robust gain.** HAR - a short, a medium and a long
realised variance together - wins or ties on every series. That is Corsi's model
and it is the standard benchmark precisely because it is hard to beat.

**The high-low range helps intraday and hurts on daily.** Parkinson and
Garman-Klass add a few points at 15m and 1h, and on usdjpy 1d they are *worse*
than the close-only baseline - 4.6% against 6.0% of the oracle. A daily bar's
extremes include thin-liquidity spikes that are not representative of the path;
an intraday bar's range is mostly genuine travel. **The data has carried `high`
and `low` all along and nothing here had used them.**

**The best single change is HAR-Parkinson**, and the honest size of it is: from
64% to 79% of achievable at 15m, and from 24% to 53% at 1h. So roughly a fifth
of the remaining gap at the fast end and half of it at the slow end - a real
improvement, and not the sevenfold one advertised.

### The two liquidity measures, and why one fails

**Amihud illiquidity, `|return|/volume`, is worthless here: -1% to 8%.** The
reason is in `context/activity.py`, which sets out at length that these venues
do not report traded size - a CFD "volume" is a tick count. Amihud needs real
volume and there is none, so this is a data limitation rather than a finding
about the measure.

**Roll's implied spread reaches 16% to 36% of achievable**, which is real signal
from price changes alone and still well below the variance estimators. It
measures bid-ask bounce, so it is a liquidity proxy that happens to correlate
with volatility rather than a volatility estimator - and that it works at all is
the one thing the liquidity reading contributed to this.

### And the retail liquidity material, against what the desk already has

Four references on liquidity zones, voids and sweeps. Checked before proposing
anything, and the desk has implemented and **measured** most of it:

| the concept | here |
| --- | --- |
| liquidity zone | a level. `drawing/` draws them seven ways |
| liquidity void, imbalance, fair-value gap | **`drawing/gaps.py`** - three bars where the first's high sits below the third's low |
| price returns to fill the void | **already measured and it is a coin**: `research/docs/imbalance.md` has gap *edges* at first touch at **50.2%** against a 49.6% placebo and a **51.5% breakeven** |
| liquidity sweep or grab | `Outcome.TRAP`, and `sweep_rate` is its decayed share |
| stops resting beyond a level | `liquidity_beyond_vol`, the next level out |
| wick rejection | `wick_above_vol`, `wick_below_vol`, `wick_n` per level |

None of the four references gives a quantitative criterion for any of it - the
fxopen piece offers volume profile peaks, consolidation and prior
support/resistance, with no threshold for any of the three.

**The one open question is specific and already written down**: `gaps.py` emits
the **midpoint** of the untraded range while the 50.2% study measured the
**edges**, and `config.py` records that "what production draws is not the price
that study measured". So the testable residue of the void literature is whether
the midpoint behaves differently from the edge, on a pass that is attributed 204
times in 32,603 level calls.

## Converting the harnesses to time reversed the volatility headline

Done 2026-10-11, after the package rule was written: `research/ideas/` counted
bars everywhere, so the harnesses were the one place still breaking it.
`volatility_ceiling.py` is converted and **its headline result changed**, which
is the clearest demonstration of why the rule exists.

### What the confound was

`har (5/22/110)` meant 5, 22 and 110 **bars**: 1.25h, 5.5h and 27h at 15m, and
5, 22 and 110 **days** at 1d. So "HAR-Parkinson wins intraday and loses on
daily" was partly a statement about the spans being different lengths of time on
the two series - the estimators being compared were not the same estimators.

Stated in time - `1d/5d/22d`, the literature's own spans - the ranking inverts.
Share of what a perfect sigma could capture, eurusd:

| estimator | 15m, 1h ahead | 1h, 1h ahead | 1h, 24h ahead |
| --- | ---: | ---: | ---: |
| baseline mean `\|r\|` | 98% | 63% | 8% |
| **parkinson (high-low)** | **107%** | **90%** | 12% |
| **garman-klass (ohlc)** | **106%** | **90%** | 13% |
| har 1d/5d/22d | 66% | 40% | 52% |
| har-parkinson | 62% | 43% | **58%** |
| ewma, 11d half-life | 47% | 42% | 51% |

**HAR-Parkinson is no longer the best single change**, and the earlier claim that
it was - 64% to 79% - is withdrawn. With the spans in time it is *worse* than
the baseline at short horizons and better only at 24h.

### The finding underneath, which the bar counts were hiding

**Match the estimator's span to the forecast horizon.** A short horizon wants a
short-span range estimator - Parkinson or Garman-Klass, 90-107% - and a long
horizon wants a long-span multi-scale or time-decayed one - HAR or EWMA, 51-58%
at 24h where the short estimators collapse to 8-13%.

Obvious in hindsight, and the bar-counted version could not see it because a bar
count accidentally couples the span to the timeframe: HAR's 5/22/110 bars *was*
a short-span estimator at 15m, which is why it looked good there.

**And the range beats the close at every short horizon**, 90% against 63% at 1h
and 107% against 98% at 15m. That part survives the conversion and is the
durable result: the high and the low carry information the close does not, and
this package had the data for it from the start.

### The denominator is estimator-dependent, which the >100% cells expose

Parkinson reading **107% of achievable** is not a forecast beating perfection.
`achievable` simulates `sigma * z` taking **`har-parkinson` as the true sigma**,
so any estimator that is a *better* sigma than that one exceeds the ceiling
built from it - which is informative, since it says Parkinson is the better
sigma, and means the percentage is not a true fraction.

Fixing it properly needs a sigma that is not one of the candidates - a
simulation with a known generating process, which `paths.simulate` provides and
this harness does not use. Recorded rather than fixed, and the cells above 100%
should be read as "better than the estimator the ceiling was built from" rather
than as a share.

### And v75 cannot be scored this way at all

Its perfect-sigma ceiling is **0.5%**, because the generator's volatility varies
without autocorrelating. Dividing by that turned noise into cells reading
**-176% of achievable**, which is not a number anyone should read, so the
harness now guards the denominator and prints the raw share with a mark where
the ceiling is below 2%.

That is the synthetic control doing its third useful thing today: it is a
control for direction, **not** for volatility work, and it says so loudly enough
to break a table.

## The synthetics are a market, not a control - and the desk is losing on the other one

Corrected 2026-10-11. This file has repeatedly called v75, v25 and v100 "the
synthetic control", on the grounds that their volatility is generated so an
effect found there is an effect found in the method. That is a fair *use* of
them and it caught two artefacts - the 15m slope fade and the cross-resolution
lookahead - but it is the wrong *description*. **The desk trades these feeds.**
The journal has `fade-to-value` decisions on `volatility_50_index`, and
`STRUCTURES_FORMATION` draws levels on them like anything else.

So the measurements about them are statements about a live venue, and they
should be read that way:

* **"a perfect sigma captures 0.5% of the realised-move oracle on v75"** is not
  a control behaving as expected. It says **volatility is not forecastable on
  the synthetics** - the one quantity that *is* forecastable on FX, where the
  same ceiling is 6.6% to 12.8%.
* **"v75 produced no slope-fade survivors"** says the same about direction.
* So on these feeds neither of the two things measured here is available. That
  is a fact about an instrument class the desk has positions in.

### What the journal says, which is the opposite of what that predicts

Closed trades, from the desk's own record:

| family | n | mean R | +/- | t | total R |
| --- | ---: | ---: | ---: | ---: | ---: |
| synthetic | 847 | +0.039 | 0.081 | +0.5 | **+33.37** |
| fx / metal / index | 674 | **-0.055** | 0.019 | **-2.9** | **-37.32** |

The forecastable-volatility side is the **losing** side, significantly, and the
unforecastable side is where the money is. That wants explaining before it is
believed.

**The standard errors explain most of it: 0.081 against 0.019.**
`volatility_75_index` reads **+2.828 mean R over 24 trades** - roughly +68 R
from one feed, more than the entire synthetic total - at `t = +1.0`. A handful
of large winners, not an edge. Strip it and the synthetics are negative too.

The FX side is the part that is real: **-0.055 at `t = -2.9` over 674 trades**,
with `gold` at **-0.465** (`t = -3.4`) and `us30` at -0.389 the worst of it. And
among the synthetics, `crash_500_index` (-0.142, `t = -3.0`) and
`volatility_10_1s_index` (-0.127, `t = -2.5`) are significantly negative in
their own right.

### What follows

**The desk is losing on the instruments where volatility is forecastable.** That
is the finding, and it is not an argument for preferring the synthetics - it is
an argument that the forecastable thing is not being used. Every strategy here
sizes on `risk_vol` and a stop multiple; none of them reads a volatility
forecast, and `README.md`'s improvement 1 - a time-varying `R` - is the first
place one would enter.

Three things to measure, in order, and all of them from data already held:

1. **Per-feed sizing against per-feed volatility predictability.** If `gold` at
   -0.465 R a trade is being sized as though its volatility were as
   forecastable as eurusd's, that is a sizing error rather than a strategy
   error.
2. **Whether the synthetic profit survives dropping the top feed.** One feed
   at +2.83 over 24 trades is a concentration, and the honest version of
   "+33.37 R" quotes it with that feed removed.
3. **Whether `crash_*` and `*_1s_*` belong in the book at all.** Two of them
   are significantly negative on their own records, which is a cheaper decision
   than any modelling.

And the earlier use of these feeds stands even though the description was
wrong: a generated series that shows the same effect as a market is still the
fastest way to catch a method artefact. The correction is that it is **also** a
market, so "no effect on v75" is a finding about v75 and not only a clean bill
of health for the method.
