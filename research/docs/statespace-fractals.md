# Fractals: the ladder belongs on the variance, and there it wins

Asked on 2026-10-12: research fractals and how to add them to the state-space
models.

Most of what "fractal" names in trading has already been measured here and is
null. The geometry papers' fractal decomposition claimed 3.2 sub-swings per
swing and it measures 1.92 to 2.35, set by the detector's reach rather than
any market clock. Counted pivots were null over 1,020 cells. A Hurst exponent
on the level has been in `inputs.py` for years and the level's `H` measures
0.489 to 0.506 here - a random walk, to three decimals, on every instrument.

And `fractional.py` already builds the standard long-memory device, a power
law as a sum of geometrically spaced Ornstein-Uhlenbeck modes, then says in
its own docstring where it stopped:

> **Long memory in the level is not long memory in the variance.** The modes
> here give the *mean* a kernel.

That is the gap. It is also where the live literature went, and all three
things measured there came back **positive** - which is rare enough in this
package to be worth stating plainly.

## 1. Log-volatility is rough, and the control is what makes that readable

Gatheral, Jaisson and Rosenbaum report log-volatility behaving like fractional
Brownian motion with `H` near 0.1, far rougher than a walk's 0.5. Cont and Das
answer that the small exponent is an artefact: log-volatility is never
observed, only estimated from a finite window, and independent estimation
noise between windows looks exactly like extreme roughness.

Both are testable at once by measuring a process whose log-volatility is **an
OU with `H` of 0.5 by construction** through the identical proxy:

| series | `H` of log-vol | log-vol swing |
| --- | --- | --- |
| EURUSD | 0.014 | 0.628 |
| GBPUSD | 0.015 | 0.624 |
| XAGUSD | 0.019 | 0.639 |
| XAUUSD | 0.022 | 0.635 |
| USDJPY | 0.039 | 0.649 |
| ETHUSD | 0.049 | 0.686 |
| BTCUSD | 0.057 | 0.702 |
| **traded median** | **0.022** | **0.639** |
| `Volatility_75_Index` | 0.000 | 0.315 |
| a constant-volatility walk | -0.005 | 0.314 |
| **OU log-vol, true `H` = 0.5** | **0.141** | 0.578 |
| GARCH(1,1) t(5) | 0.088 | 0.535 |

**Cont and Das are right about the bias and it does not rescue the null.** The
estimator returns 0.141 for a process whose true `H` is 0.5, so it is biased
down by a factor of three or four. The market reads 0.022 - **six times lower
still**, and at a *larger* log-volatility swing than the control. So the small
exponent is not the market's signal being weaker than the control's; the
market's log-volatility moves more and is measured as much rougher.

The `swing` column is why that sentence can be written at all. The estimator
cannot tell a rough log-volatility from a weak one - a constant-volatility
series reads `H = 0` exactly, as both the generated markets and the walk do -
so a reading between 0 and 0.141 is uninterpretable without the amplitude
beside it. The constant-volatility swing of 0.315 is the estimation-noise
floor, and it matches `1/sqrt(2 * window)` for a six-return window, so the
market's 0.639 is about 0.55 of genuine log-volatility variation on top of it.

## 2. The returns are multifractal

The multifractal random walk gives `zeta(q) = q H - lambda^2 q (q-1) / 2`, so
the curvature of the scaling exponent **is** the multifractality. Published
`lambda^2` for equity indices is 0.02 to 0.03.

| series | `lambda^2` | fitted `H` |
| --- | --- | --- |
| USDJPY | 0.1174 | 0.560 |
| GBPUSD | 0.0904 | 0.533 |
| EURUSD | 0.0878 | 0.533 |
| ETHUSD | 0.0731 | 0.537 |
| **traded median** | **0.0763** | 0.537 |
| generated markets | 0.0013 | 0.503 |
| a constant-volatility walk | 0.0051 | 0.510 |
| OU log-vol | 0.0104 | 0.504 |

Every traded instrument is an order of magnitude above every control. Measured
higher than the published range, which is most likely the scale: this is
hourly data over lags of six to three hundred hours, where the published
figures are daily over years.

**One correction to this arm's first version**, recorded because it would have
inverted the reading. `zeta(q)` is defined on **returns aggregated over the
lag** - the increments of the level - and the first version fitted it to
log-volatility increments instead, a different and much less standard
quantity. It returned `lambda^2` of 0.0002 for the market against 0.0335 for
a GARCH surrogate, which reads as "the market is less multifractal than
GARCH". On the correct quantity it is 0.076 against 0.005.

## 3. The state-space answer: the ladder goes on log-volatility

The claim that matters for this package. A ladder of five geometrically spaced
modes against a single OU, both with their process noise swept on the first
half of the series and scored on the second, on the **log-volatility** series:

| series | ladder | one OU | gain |
| --- | --- | --- | --- |
| EURUSD | -3511.1 | -4058.1 | **+547.0** |
| GBPUSD | -3506.9 | -4036.3 | **+529.3** |
| XAGUSD | -3212.2 | -3596.0 | **+383.8** |
| XAUUSD | -3194.9 | -3543.5 | **+348.6** |
| USDJPY | -3212.1 | -3537.4 | **+325.3** |
| ETHUSD | -3128.4 | -3386.7 | **+258.3** |
| BTCUSD | -3096.7 | -3287.6 | **+190.9** |
| `Volatility_75_Index` | -1478.7 | -963.2 | **-515.5** |
| `Step_Index` | -1809.1 | -997.1 | **-812.0** |
| a constant-volatility walk | -1672.6 | -858.8 | **-813.8** |
| **OU log-vol, true single OU** | -2003.3 | -1550.3 | **-453.1** |

**Seven of seven traded instruments favour the ladder; five of five controls
favour the single OU.** The last row is the one that makes this a finding
rather than a flexibility contest: on a series whose log-volatility genuinely
*is* one OU, the single OU wins by 453 nats. The ladder is not winning because
it has more parameters - it loses whenever the extra modes have nothing to
describe.

Both members also chose the **same base** on every traded instrument, so the
gain is not a rescaling. On the controls the chosen bases differ by four to
seven orders of magnitude, which is the ladder being the wrong model and
saying so.

## The gate, run: the ladder does not earn its complexity

A likelihood gain on log-volatility is a statement about log-volatility, not
about the interval a stop sits in. `statespace-backtest.md` measured the
random walk's two-sigma band at 0.953 against a nominal 0.954 - already
honest - so the question is whether a volatility model produces a band that is
**narrower at the same coverage**.

Four forecasters of the next bar's spread, all fitted on the first half and
scored on the second:

| | cover 1 sigma | cover 2 sigma | width at 2 sigma | **width at 0.954 coverage** |
| --- | --- | --- | --- | --- |
| constant, i.e. the walk | 0.819 | **0.951** | 1.000 | 2.059 |
| **trailing standard deviation** | 0.742 | 0.925 | 0.769 | **1.933** |
| ladder on log-volatility | 0.716 | 0.909 | 0.719 | 1.999 |
| one OU on log-volatility | 0.672 | 0.878 | 0.649 | 2.097 |

**Reading the nominal two-sigma column alone would get this wrong.** Every
volatility-scaled band is narrower there - the ladder at 0.719 of the
constant's width - and every one of them **under-covers**, at 0.878 to 0.925
against 0.954. Narrower and under-covering is not sharper, it is wrong.

The reason is the conditional distribution rather than the volatility model.
Conditioning on volatility removes the *clustering* part of the fat tail and
leaves a `t`-like core, so a Gaussian multiplier of two is too small for it -
and the constant band's own two-sigma honesty is the mirror of the same fact,
which is why it over-covers at one sigma while being right at two.

So the last column is the only honest comparison: the multiplier searched
until coverage actually reaches 0.954, and the widths compared there.

* **A volatility model does beat the walk**, but by 3 to 6 percent, not by
  the 28 percent the nominal column suggests.
* **The winner is the trailing standard deviation at 1.933**, not the ladder.
  A plain window of twenty-four bars is 3.3 percent narrower than five fitted
  geometric modes.
* **The single OU is worse than the constant** at 2.097, so the ladder's win
  over it is real - the modes help *within* the log-volatility model - and
  that win does not survive contact with the simplest possible alternative.

**So the wiring is not justified.** The +191 to +547 nat likelihood gain on
log-volatility does not translate into a better band than `trailing`, which
is the null `nulls.py` describes as "the one nothing here has beaten" and
which remains unbeaten. Running the gate cost one afternoon; wiring a ladder
into `Q` first and discovering this afterwards would have cost considerably
more.

Two caveats on what is above:

* **The GARCH surrogate was broken when this was first run and is now
  fixed.** An unstandardised t(5) innovation has variance `nu/(nu-2)`, five
  thirds, so a recursion written with `shock = 0.10` and `memory = 0.88` has
  an effective persistence of **1.046**: explosive. Measured, its variance
  reached `1e110` and **98.8% of returns sat on the clamp**, making it a
  clamped square wave whose log-volatility swing of 0.116 was *below* the
  estimation-noise floor. A control that is accidentally a near-constant
  series is worse than no control, because it still produces a number.
  It now lives in `nulls.garch`, which standardises the innovation and
  refuses a persistence at or above one - and three harnesses that each had
  their own copy of the same defect now share it.
* Everything is at 1h with a six-bar volatility window. The roughness
  estimator is known to be window-sensitive, and the window was not swept.

The harness is `research/ideas/rough_volatility.py`.
