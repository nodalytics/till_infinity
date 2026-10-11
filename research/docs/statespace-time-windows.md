# Cumsum, slope and RSI over time rather than over bars

Asked on 2026-10-11: test cumulative sums over minutes and hours instead of
bars, then slopes over time, then their EMA and SMA variants, then RSI. The
harness is `research/ideas/cumsum_time.py`, and it measures two different
things. The first needs no outcome at all and is the one that settles the
package rule.

Eight features, each defined by a **duration**: `cumsum`, `slope`, `rsi`, and
the SMA and EMA of each. Every window, every moving-average span and every EMA
half-life is a length of time. The bar-count table is the same code with the
duration replaced by a bar count, which is how all three are normally written.

## 1. Does the statistic survive changing the feed?

Take one instrument on two feeds, compute the same feature from each, match on
**timestamps**, and correlate. If the window is a duration, both feeds summed
the same stretch of the same market and should agree. If it is a bar count, they
summed different stretches. No return, horizon or cost model is involved: the
feature is tested against itself.

eurusd, 15m against 3m, 8,013 paired bars:

| feature | 0.5h | 1h | 2h | 4h | 8h | 24h |
|---|---|---|---|---|---|---|
| cumsum | 0.544 | 0.756 | 0.868 | 0.931 | 0.964 | **0.982** |
| cumsum sma | 0.545 | 0.851 | 0.957 | 0.986 | 0.993 | 0.992 |
| cumsum ema | **0.800** | 0.940 | 0.980 | 0.991 | 0.994 | **0.996** |
| slope | 0.051 | 0.553 | 0.857 | 0.962 | 0.989 | **0.998** |
| slope sma | 0.100 | 0.572 | 0.907 | 0.978 | 0.992 | 0.992 |
| slope ema | 0.347 | 0.715 | 0.945 | 0.989 | 0.993 | 0.980 |
| rsi | 0.497 | 0.740 | 0.858 | 0.926 | 0.960 | **0.985** |
| rsi ema | 0.760 | 0.857 | 0.916 | 0.952 | 0.973 | 0.983 |

The same features written as bar counts, same two feeds:

| feature | 4 bars | 8 bars | 20 bars | 50 bars |
|---|---|---|---|---|
| cumsum | 0.392 | 0.391 | 0.379 | 0.336 |
| cumsum sma | 0.277 | 0.196 | 0.125 | **0.055** |
| cumsum ema | 0.422 | 0.338 | 0.244 | 0.170 |
| slope | 0.327 | 0.319 | 0.240 | 0.157 |
| slope sma | 0.178 | 0.127 | 0.066 | **-0.001** |
| slope ema | 0.305 | 0.272 | 0.153 | 0.075 |
| rsi | 0.370 | 0.389 | 0.381 | 0.338 |
| rsi ema | 0.495 | 0.574 | 0.636 | 0.646 |

**Stated as a duration, every family converges on the same number from either
feed - 0.93 to 1.00 once the window reaches four hours. Stated as a bar count,
nothing does, and most get worse as the count grows.** A 50-bar moving average
of a cumsum computed on 3m bars and on 15m bars are statistics with a rank
correlation of **0.055**; the 50-bar moving average of a slope reaches
**-0.001**, which is to say the two feeds' versions of "the same indicator" are
unrelated. "RSI 14" - the most common bar count on any desk - is 42 minutes on
one feed and 14 hours on another, and reads 0.34 to 0.39 between them against
0.985 for the same thing stated as a day.

Three further things fall out of the table, none of which was the question:

* **The EMA form is the most portable at short windows.** `cumsum ema` reads
  0.800 at half an hour where the raw cumsum reads 0.544, because an
  exponential weight by *time* is insensitive to how coarsely the coarse feed
  quantises the window. If a short window has to be computed on a coarse feed,
  this is the form to use.
* **A slope needs points, not just a duration.** `slope` reads **0.051** at half
  an hour on 15m bars, which is a two-point regression and therefore noise. A
  duration makes a window portable; it does not make it estimable. Below about
  eight bars in the window, a slope is not measuring a slope.
* **`rsi ema` is the one bar-count row that *improves* with `N`** - 0.495 to
  0.646 - and that is not portability. A long EMA of a bounded quantity
  converges on its own long-run average on any feed, so the two agree by both
  being flat. Agreement through over-smoothing looks like the thing wanted and
  is not it.

## 2. Does any of it predict?

1,197 cells: eight features, six windows, three horizons, five series, two
feeds. Direction against a rotated control; magnitude against a trailing
standard deviation over the same window, which has beaten every volatility
model tried here.

| feature | hit | control | \|z\|>2 | \|f\| -> \|move\| | net of sd |
|---|---|---|---|---|---|
| cumsum | 49.37% | 50.13% | 29/150 | +0.103 | +0.044 |
| cumsum ema | 49.54% | 50.25% | 29/150 | +0.093 | +0.044 |
| cumsum sma | 49.69% | 50.12% | 19/150 | +0.096 | +0.040 |
| slope | 49.32% | 50.18% | 28/147 | +0.097 | +0.032 |
| slope ema | 49.34% | 50.24% | 29/150 | +0.082 | +0.033 |
| slope sma | 49.70% | 50.25% | 21/150 | +0.084 | +0.030 |
| rsi | 49.28% | 50.16% | 37/150 | +0.010 | +0.032 |
| rsi ema | 49.07% | 50.33% | 42/150 | +0.032 | +0.019 |

**Every family's hit rate is below its control**, and 234 of 1,197 cells clear
`|z| > 2` against the ~54 chance would give. That is a real anti-momentum
effect, and the breakdown says what it is rather than leaving it as one:

| | edge against control |
|---|---|
| eurusd 15m | **-2.14pt** |
| gbpusd 15m | **-2.08pt** |
| usdjpy 15m | -0.99pt |
| eurusd 1h | -1.34pt |
| xauusd 15m | +0.54pt |
| v75 15m | -0.15pt |
| v75 1h | +0.10pt |

It is concentrated on the FX majors at the shortest windows - 0.5h reads
-1.48pt and 4h reads -0.36pt - **and it is absent on v75**, which is generated
and has no microstructure to reverse, with 10 of 144 cells clearing `|z| > 2`
against the 7 chance would give. That is the signature of short-horizon
microstructure reversal, not of a forecast.

**And it is economically dead.** A 2.1-point hit-rate edge on a symmetric
payoff is worth about 4% of the average move, which on eurusd 15m is some 0.1
pip, against a round trip measured on this desk at 4bp - more than four pips.
Dead by a factor of forty, before slippage. It joins the rest: statistically
present, not tradeable, and the reason it is written down is that it would look
like an edge to anyone who stopped before the cost line.

The magnitude arm repeats the lag panel's verdict. `|cumsum|` and `|slope|` are
volatility proxies worth +0.03 to +0.04 beyond a trailing standard deviation,
which is where a partial correlation's own curvature lives. And **RSI carries no
magnitude information at all** (+0.010), which is the right answer for a bounded
scale-free indicator and a small piece of evidence that the measurement is
behaving.

## The bug in this harness, which nearly became the headline

The first run reported `z = -7.32` at `n = 39,998`, and that was **overlapping
windows**, which is how `slope_fade.py` once produced a `t` of -10.8.

The cause was two conversions of one quantity. `families()` turned hours into a
bar span by dividing by the bar size, and the evaluation stride turned the same
hours into bars by dividing by the bar size **and multiplying by trading
coverage**. A window of `H` calendar hours holds `H * coverage / bar` bars,
because a market that trades half the clock puts half as many bars in a given
stretch of it - so the feature spans were about twice the stride on FX and
consecutive rows shared almost their whole window.

One conversion now, used in both places, and the stride steps by the longer of
the feature's own window and the horizon. The effect survived at a third of the
`z`, which is the useful part: the direction of the finding did not change, and
its significance was inflated nearly threefold by an inconsistency that each
half of looked correct on its own.

## Inside the bar: a parent read on a finer feed

Asked for once windows were being measured in time: look at a 1h bar, then drop
to 5m and see what was *inside* it. The harness is
`research/ideas/inside_the_bar.py`, over `(15m, 3m)`, `(1h, 15m)` and
`(4h, 1h)` on five series - 360 cells.

A parent bar is four numbers; its children are the path that produced them, and
the path says three things OHLC cannot:

* **which extreme came first.** `open, high, low, close` is famously ambiguous
  about this - "up then down" and "down then up" give the same four numbers -
  and it is the one piece of information a finer feed adds for free.
* **how much travelling the net move cost**, as net displacement over path
  length. A bar that went a long way to get nowhere is a different object from
  one that went straight there.
* **how far it went against itself** before closing where it did.

The question is **not** whether the path predicts - a path contains its bar, so
anything the bar predicts the path predicts too and a correlation would prove
nothing. It is whether the path adds anything to what the parent already says,
so every reading is reported net of the parent's own close-in-range and range,
and net of a trailing standard deviation over twenty parents.

| feature | direction, net | mag, net | sign consistency |
|---|---|---|---|
| efficiency | -0.003 | **-0.020** | 33/45 negative |
| turns | +0.002 | **+0.016** | 35/45 positive |
| rv_over_range | +0.008 | **+0.013** | 35/45 positive |
| adverse | +0.004 | +0.010 | 29/45 |
| low_at | +0.008 | +0.007 | 27/45 |
| high_first | -0.003 | -0.006 | 16/45 |
| close_vs_path | -0.006 | +0.004 | 24/45 |
| high_at | +0.005 | +0.003 | 25/45 |

**Direction is dead: 19 of 360 cells clear `|t| > 2` against the 16 chance
gives.** And `high_first` - the one thing OHLC cannot express, which is the
reason to look inside at all - carries nothing at all: -0.003, `t = 0.2`.

**Magnitude is real, consistent and negligible.** 67 of 360 cells clear
`|t| > 2`, concentrated entirely at the next parent bar (45 of 120, falling to
11 of 120 by four parents ahead). The sign is consistent across cells - a
**choppy** bar, with many direction changes, low efficiency and high realised
variance relative to the range it produced, precedes a bigger next bar - and the
effect is a rank correlation of about **0.02**, against **+0.158** for the
trailing standard deviation it is measured on top of. One part in eight of the
simplest estimator, for a feed you have to join two resolutions to compute.

### The bug, which was the whole first answer

The first run found `high_first` at `t = 4.9` and called it the strongest cell
in the table. It was **overlapping outcomes**. Parent bars do not overlap, which
is what the docstring said and why no stride was applied - but their *outcomes*
do: at twenty-four parents ahead, consecutive rows share twenty-three
twenty-fourths of their outcome window.

It announced itself twice and I nearly missed both. Every strong cell was at the
longest horizon, which is where overlap is worst rather than where an effect
would be. And `high_first` took **opposite signs on two resolutions of the same
instrument** - v75 read -0.055 on `15m/3m` and +0.052 on `1h/15m` - which is not
something an effect does.

Stepping the rows by the horizon removed it entirely: -0.003 at `t = 0.2`. Third
time overlapping windows have manufactured a finding in this project, after
`slope_fade.py`'s `t = -10.8` and `cumsum_time.py`'s `z = -7.3`. The lesson is
not "remember the stride" - it is that **"the rows don't overlap" and "the
outcomes don't overlap" are different claims**, and only the second one matters.

### And the features that carried the signal are properties of the feed

The portability logic turned on this harness asks: is a path feature a property
of the **market**, or of the **child feed**? Path length grows without bound as
sampling gets finer - that is what a fractal dimension above one means - so
`efficiency` and `turns` cannot be invariant the way a close is.

Same 1h parents, decomposed on 15m children and on 3m children, the two readings
correlated (eurusd, 2,002 parents; the other three series agree to within 0.03):

| feature | rho between child feeds | mean shift |
|---|---|---|
| adverse | **+1.000** | -0.000 |
| close_vs_path | +0.979 | -0.002 |
| high_first | +0.967 | +0.043 |
| low_at | +0.934 | -0.001 |
| high_at | +0.933 | -0.001 |
| efficiency | +0.844 | **-0.522** |
| rv_over_range | **+0.207** | +0.159 |
| turns | **+0.021** | -0.041 |

**This inverts the result above.** The features that are properties of the
market - where and in what order the extremes were made, how far the bar went
against itself, where the close sat on its own path - are invariant to the child
feed at 0.93 to 1.00, and they carry **nothing**: `high_first` at `t = 0.2`.

The three that carried the small magnitude signal are the three that are *not*
invariant. `turns` correlates with itself at **0.021** across child feeds, which
is to say the number of direction changes inside a bar is a property of how
often you looked, with no market content whatever. `rv_over_range` manages 0.15
to 0.23, which is the volatility signature plot: realised variance rises as
sampling gets finer, which is microstructure noise and is why the signature plot
exists. And `efficiency` orders bars consistently (0.84) but its **level shifts
by -0.52** between feeds, so a threshold on it means nothing without naming the
child resolution.

So the honest summary of looking inside the bar is:

> The intra-bar readings that mean the same thing on any feed carry no signal.
> The ones that carry a trace of signal do not mean the same thing on any feed,
> and the trace is a rank correlation of 0.02 against the trailing standard
> deviation's 0.158.

That is a better answer than either arm alone, and it is only available because
the same question - *does this survive changing the feed?* - was asked of the
features and not just of the windows. It is the cheapest test in this file: no
outcome, no horizon, no cost model, and it disqualified three features that had
already passed a significance screen.
