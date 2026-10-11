# statespace: what the members measure against each other

Extracted from `statespace/README.md` on 2026-10-11, which had grown to 2,586 lines by holding the package's design and its entire measurement record in one file. The design stayed there; the measurements are here, which is where this repository keeps studies - `pca-residuals.md` and `imbalance.md` are the precedents.

**The rule these were taken under**, from `statespace/__init__.py`: nothing in that package publishes until it has beaten a **named** null on held-out data. The null has to include the random walk, the synthetic feeds, the overlap correction, the cell count and the spread - and the first version of nearly every measurement below failed at least one of those. See `statespace-method.md` for the six times an effect appeared and was not there.

## Measured on eurusd, 3m to 1d: selection loses, and the LTI basis wins the fast end

`research/ideas/statespace_eurusd_timeframes.py`, run on the lab 2026-10-10.
Fitted by grid on the first half of each series, scored on the **second half**,
held-out one-step predictive log-likelihood **a point** so the timeframes are
comparable. 6,000 bars each. There is no eurusd 5m on the lab - `data/fine`
carries 5m only for the boom/crash indices - so 3m and 15m bracket it.

| timeframe | `linear` I3 jerk | `reverting` I2 OU | **S4D-Real LTI** | **S6 selection on** |
| --- | ---: | ---: | ---: | ---: |
| 3m | -24.07 | -8.49 | **-4.60** | -10.47 |
| 15m | -6.56 | -3.06 | **-2.36** | -19.00 |
| 30m | -3.99 | -2.36 | **-2.20** | -2.73 |
| 1h | -2.81 | **-1.98** | -2.21 | -2.33 |
| 4h | -3.61 | **-2.49** | -4.56 | -4.59 |
| 1d | -3.32 | **-2.10** | -2.15 | -2.15 |

Three findings, and the first was predicted, the second was not.

**1. Selection loses, on five of six timeframes.** The sixth is 1d, where the
grid picked `scale = 0.1` and it changed the score by 0.0000 - a tie reported as
a win by a harness comparing floats, not a result. This is the clean experiment
the harness was built for: `S4D-Real LTI` is `selective` with `scale = 0`, so
the last two columns are **the same model one parameter apart**. Gu and Dao said
selection "can impede their performance on data that LTI SSMs excel on" and that
layers near a raw continuous signal "should be LTI". On eurusd closes they are
right, and at 15m they are right by 16.6 nats a point.

**2. The four-state LTI basis is the best model at 3m, 15m and 30m** - better
than the integrated jerk and better than the integrated OU, by 0.16 to 3.9 nats
a point. That is new. It arrived as a by-product: `selective`'s own nested null
*is* S4D-Real, so writing the neural member handed this package a multi-timescale
LTI member it did not have and would not have thought to write. **It deserves to
be a class of its own rather than a special case of the member it beats.**

**3. There is a crossover between 30m and 1h**, and it reads as a real structural
claim rather than noise: the fast end wants **several decay rates at once** - a
basis - and the slow end wants **mean reversion** in one. `reverting` wins 1h,
4h and 1d; the basis wins everything faster. If that survives a second series it
says the right model is timeframe-dependent, which is not what either camp
assumes.

### What is wrong with this measurement

* **Bars are not touches.** A close moves because price moved; a level is not
  supposed to. Sets the direction, none of the constants - the same caveat every
  harness here carries. The version on touches uses the episode record's `entry`
  and is not written.
* **`drift = 1.5` was the top of the grid in every single `selective` fit.** The
  member wanted a larger step multiplier than it was offered, so **both
  selective columns are lower bounds** and the LTI win at the fast end may be
  understated. Widen it before quoting these numbers again. `theta = 2.0` at 1d
  is the same problem on `reverting`, and `theta = 0.1` at 15m and 30m is the
  *bottom* edge.
* **Unequal search.** 5 candidates for `linear`, 20 for `reverting`, 20 for the
  LTI arm, 80 for S6. More search for S6 and it still lost, which only
  strengthens that conclusion - but `linear` is undersearched and its last place
  is not established.
* **One split, chronological.** No rolling origin, so this is one sample of the
  answer, not its distribution.

### The 15m pathology is worth naming

S6 scored **-19.00** at 15m against the LTI arm's -2.36 - an order of magnitude
worse, where elsewhere the gap is fractions of a nat. The mechanism is a feedback
loop and it is visible in the code: a large innovation opens `delta`, a large
`delta` resets the state onto that reading, and a state sitting on an outlier
makes the next innovation large too. Selection on an unrobustified residual is
positive feedback.

**Which is also the fix, and it is already in the family.** `robust` exists to
bound the influence of a surprising reading. Composing them - selection reading a
Huber-gated `z` rather than a raw one - is the one version of S6 this data might
not reject, and it costs no new parameter.

## What the four quantities showed on real data

285,688 held-out points, 24 series of four symbols, 3m to 1d. Coverage
recomputed on a **predictive** band - `sqrt(sd^2 + R)` - because the harness's own
column compared a state band on three members against a fitted predictive spread
on the fourth, which is the same comparability trap again.

| model | cover +/-2 | RMSE | lag-1 autocorrelation of `z` |
| --- | ---: | ---: | ---: |
| `linear` | 68.6% | 50.25 | **+0.323** |
| `reverting` | 79.4% | 2.84 | +0.092 |
| **S4D-Real LTI** | **94.2%** | **2.53** | **+0.031** |
| S6 selective | 91.4% | 14.44 | +0.071 |

**Three independent criteria agree, which is the finding.** S4D-Real fits best,
is the only member whose two-sigma band is honest - 94.2% against a nominal 95%,
where `linear` claims far more than it knows - and has the whitest residuals.
Autocorrelation is scale-free, so that last column is comparable even where the
`|z|` column was not, and `linear`'s **+0.32** is the diagnostic saying its state
equation is wrong rather than merely imprecise.

**Every member is still misspecified**, which is what `__init__.py`'s fourth
principle says to expect: no residual series is white and none is normal. The
honest reading is a ranking of wrongness, not a model that works.

**`existence` was identical across all four at 0.958** - as it must be, since it
decays on elapsed time alone and they were fed one timeline. That is a check
passed rather than a result, and it is the cheap confirmation that the harness
drove every member on the same clock.

## Seven symbols, 3m to 1d, scored properly: S4D-Real wins and the anchor needs the particles

`research/ideas/statespace_symbols_timeframes.py`, 2026-10-10, after the
log-sum-exp fix. Four FX pairs and three Deriv synthetics - **the synthetics are
the control that matters**, because their volatility is generated and stationary
by construction, so a member winning only there is describing a simulator.

39 series. Wins by member:

| member | series won |
| --- | ---: |
| **S4D-Real LTI** | **21** |
| `reverting` | 8 |
| S6 selective | 6, every one of them a tie or within 0.002 |
| `swarm` | 2 - v25 15m and v75 15m |
| `anchored`, `count = 1` | **0, and catastrophically** |

### The anchor cannot be had without the particles, and that is structural

`count = 1` was written to answer "fix the extrapolation without the particle
part". It scores between **-71 and -101,256** a point. That is not a close loss
or a tuning failure, and the reason is worth more than the member:

**a zero eigenvalue cannot be driven by the recurrence** - the entry weight
`1 - exp(delta * A)` is exactly zero there - so the anchor is a random walk, and
with one particle there is nothing to reweight and nothing to resample. **The
anchor is therefore never corrected toward the data.** The deviations track, the
anchor drifts off, and `value = anchor + deviations` drifts with it.

So the ensemble is not an optional extra that buys uncertainty on top of a
working point estimate. **It is the anchor's only correction mechanism.** The
alternative - a gain that pulls a persistent component toward each reading - is
precisely a Kalman update on that state, which is what `linear` and `reverting`
already are. Asked to separate the two fixes, the measurement says they do not
separate.

### What `swarm` is actually good at, which is not the likelihood

It wins two series of 39, and it is **the best-calibrated member where it runs**:
96.8% coverage at v75 15m against S4D-Real's 94.3%, on a nominal 95%. That is
what it was built for and it delivers it - an inferred spread that widens in a
gap, where `selective`'s is a fitted constant.

The honest summary is that `swarm` buys **honest uncertainty at a small cost in
fit**, and on this data S4D-Real's fit is better. Which of those a caller wants
depends on whether it sizes on the band or only reads the point, and this desk
sizes on the band.

**Its first score is withdrawn.** The run before the log-sum-exp fix had it
winning 18 of 24; that number was inflated by the missing shift and should not be
quoted.

### Selection, over 39 series rather than six

Still essentially never: six nominal wins, all ties or within 0.002 a point, and
the failures remain catastrophic - **-128.86** at xauusd 4h and **-570.31** at
usdjpy 3m against LTI arms at -6.74 and -2.69. The feedback loop is unchanged: a
large innovation opens `delta`, the state resets onto the outlier, the next
innovation is larger. The paper's own limitation holds on seven symbols.

### The synthetics behave differently, and in a readable way

On v25, v75 and v100, `reverting` wins 1h and 4h where it loses those on FX, and
the whole field is closer together - v75 4h has S4D-Real at **-0.145** against
`linear`'s -0.883, the widest relative gap anywhere. A generated volatility
process is more nearly the thing these models assume, which is the expected
result and is the reason to keep them in the table: a member that cannot win on
a stationary generator has no business being trusted on a market.

### Still at the grid edge

`drift = 4.0` and `wander = 2.0` pin at the top for nearly every fit, and
`noise = 2.0` often. **Every selective and swarm number here is a lower bound**
and the grids want another widening before these are quoted as final.

## One-step scoring is the wrong objective, and it favours the wrong member

Noted 2026-10-10: the desk trades many bars ahead, and **every comparison in
this file was scored on one-step predictive likelihood.** That is the objective a
random walk is best at, and it is the objective `at_time` is irrelevant to.

It matters most for the member it was supposed to favour. `swarm`'s anchor exists
precisely so that extrapolation far ahead returns the level rather than decaying
to zero, and one-step scoring cannot see that: at `h = 1` the anchor has barely
moved. So `swarm` was measured on the one horizon where its distinguishing
feature does nothing.

The signals do survive longer horizons, which is the encouraging half - ratio of
the next move's size, highest signal quintile against lowest:

| signal | h=1 | h=5 | h=20 | h=50 |
| --- | ---: | ---: | ---: | ---: |
| speed | 3.13 | 2.89 | 2.39 | **2.03** |
| `\|z\|` | 2.02 | 1.85 | 1.59 | 1.47 |
| `sd` | 1.25 | 1.23 | 1.16 | 1.08 |
| squeeze | 1.53 | 1.45 | 1.25 | 1.17 |

**Speed still gives 2.03x at fifty bars.** And the series itself diffuses at
1.00, 1.04, 1.06 and 1.07 times a `sqrt(h)` random walk over those horizons - so
very nearly pure diffusion, with a hint of trending that grows with the horizon.

**What this requires:** an `h`-step scoring arm in the harness, comparing
`at_time(t + h)` against the realised close `h` bars later and the coverage of
`band(t + h)`. Until that exists, every ranking in this file is a ranking at one
bar and should be read as such.

## What the three-state measurement also said

Worth separating, because it changes where effort goes. Held out on eurusd 4h:

| model | per point vs best |
| --- | ---: |
| two states, reverting rate | best |
| three states, two-factor drift | -0.138 |
| three states, white jerk | -0.831 |

**Almost all of the gap was the instability, not the state count.** Stability is
worth about 0.7 nats a point here; the third state is worth -0.14. So I3 was the
large win and I5 is a small loss, which is the opposite of how the spec's
suggested order ranks them — it puts I5 second and I3 outside the list on the
grounds that it is conditional on I5's answer. I5's answer turned out not to
gate it.
