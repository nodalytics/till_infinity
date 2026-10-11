# Seasonality: nothing in the level, a great deal in the spread

Asked on 2026-10-11: was seasonality ever added to the state-space package?

It was not, and the omission was real. `oscillator.py` cycles, but a
**stochastic cycle is not a seasonal**: its phase is a free state that drifts,
and fitted on real series it came back at `zeta = 67` - overdamped, with no
oscillation left at all. A seasonal has to be locked to the wall clock. Noon
UTC is noon UTC every day, whatever the market did in between.

So `seasonal.py` was written, and then measured, and the measurement moved the
answer: **a phase-locked seasonal on the level earns nothing, and the same
profile on the variance earns a great deal.**

| the component | median gain over its matched null | clock broken | generated markets |
| --- | --- | --- | --- |
| harmonics on the **level** | **-585** | -583 | -460 |
| the profile on **`R`**, the measurement spread | +43, signs mixed | - | - |
| the profile on **`Q`**, the level's own wander | **+197** | **-443** | -1.0 |

26 cells: ten traded instruments and four generated markets, at 1h and 4h, run
in the lab.

## Why the level has no seasonal, on reflection

The intraday regularity everyone knows about is in **volatility**, not in
price. A daily pattern in *how far* the market moves says nothing about *which
way* - and the level member observes the way. Put six states on the level and
they have a daily pattern in the wrong quantity to find, so they cost
likelihood and buy nothing: the component lost to its own matched null in all
26 cells, by 368 to 779 nats.

The generated markets lost by **less** than the traded ones, -460 against
-585, which is the opposite of what a market-structure finding looks like.

## What the profile finds

A 24-hour harmonic profile fitted to `log|step|`, on the first half of each
series, and used on the second:

| | peak-to-trough | peak hour, UTC | gain through `Q` |
| --- | --- | --- | --- |
| EURUSD 1h | 3.66 | 15 | +142.5 |
| GBPUSD 1h | 3.32 | 15 | +154.8 |
| USDJPY 1h | 2.81 | 14 | +199.6 |
| USDCHF 1h | 2.93 | 14 | +398.1 |
| AUDUSD 1h | 2.71 | 15 | +219.4 |
| XAUUSD 1h | 3.07 | 14 | +288.5 |
| XAGUSD 1h | 3.18 | 14 | +197.2 |
| BTCUSD 1h | 1.82 | 15 | +298.7 |
| ETHUSD 1h | 1.73 | 15 | +367.6 |
| `Volatility_75_Index` 1h | **1.05** | 12 | **+0.5** |
| `Step_Index` 1h | **1.04** | 9 | **-2.2** |

Three readings, and the third is the one that makes the first two worth
anything:

* **FX and metals move three to four times as far per hour at their peak as
  at their trough**, and the peak is at 14:00-15:00 UTC on every one of them -
  the London and New York overlap. Crypto is flatter at 1.7 to 1.8, which is
  what a market with no session close should look like.
* **Driving `Q` with it gains out of sample** on every FX and metal cell at
  both frames, +103 to +398. Crypto gains at 1h and *loses* at 4h, -17.9 and
  -26.0, consistent with its profile falling to 1.38 and 1.52 there.
* **The generated markets have no profile to find** - 1.04 to 1.17 - and gain
  nothing, -8.6 to +0.5. They are real markets the desk trades, with real
  spreads and fills; what they do not have is a session, because their price
  comes from a specified process. A gain there would have meant the harmonics
  were fitting noise.

## `R` is the wrong door, and it is worth saying why

The first version of this arm scaled the **measurement** spread with the
profile and made every cell worse, by 2 to 62 nats. Scaling `R` tells the
filter to *distrust* the readings during the busy hours, which is close to the
opposite of the truth: those readings carry the most information. Scaling `Q`
says price genuinely travels further then, which is what an intraday
volatility profile actually claims.

With the two doors side by side the difference is unambiguous - `Q` gains +197
at the median where `R` manages +43 with the signs mixed, and at 4h `R` is
negative in eleven of thirteen cells.

The profile enters `Q` **squared**, because it was fitted to a standard
deviation and `Q` is a variance. A threefold profile in size is a ninefold one
in variance, and getting that exponent wrong overshoots every busy hour by its
own square.

## How many harmonics a timeframe can carry

`Profile.fit` refused outright on 4h data at first, and it was right to.
**Bars four hours apart visit only six hours of the day**, so the design
matrix has rank at most six and three harmonics need seven coefficients. At
the Nyquist point the top harmonic is degenerate as well: with six samples a
day its sine term is identically zero at every sample.

So `fit` now counts the phases the data actually visits and caps the harmonics
at `(distinct - 1) // 2` - three at 1h, two at 4h - and reports what it used.
Counting from the data rather than from the nominal spacing matters because a
series with gaps visits fewer phases than its timeframe suggests.

This is **the one place in this package where a bar count is the right unit**.
Everywhere else a window in bars is a portability defect; here the question is
how many times a day the series is sampled, and that is a count of samples
rather than a duration.

## A null that was vacuous, and the identical columns that showed it

The first phase null shifted every timestamp by twelve hours and produced a
likelihood **identical to the real one in all 26 cells, to one decimal**.

That was not a finding, it was a broken test. A *uniform* shift only relabels
time: the relative spacing is untouched, and the phase offset is a free
parameter the filter absorbs into each harmonic's `(a, b)` pair, so the member
simply refits the same shape shifted. Sliding the **observations** against the
stamps is the version that changes which value arrives at which hour, and with
that fix the clock-broken column went to -443 - far worse than no profile at
all, which is exactly what a real alignment should look like when you destroy
it.

Two columns agreeing to the last decimal is a strong signal that a null is
measuring nothing. It is worth looking for.

## What this is for

The live desk's filters set `Q` from a constant. The measurement says that on
FX and metals the right `Q` at 15:00 UTC is around nine times the right `Q` at
03:00, and that using the constant costs 100 to 400 nats per instrument over a
couple of years of hourly bars.

What it does **not** say is that anything directional follows. The profile is
about how far, not which way, and `jpy-silver-pair.md` is the cautionary
example from the same day: an hour-of-day pattern there was the largest effect
in the study and nothing tradeable followed from it at any horizon above cost.

## Wired into `driven.py`

`driven.py` was already the door that takes an outside signal into `Q`. It
took one signal - `control`, a number the caller computes per reading from
`inputs.py` - and it now takes a second: `clock`, a function of the time
alone, which needs no caller at all because the time is already `predict`'s
first argument.

`Profile.factor` is that function. It returns the **variance** multiplier -
the profile squared - so the squaring lives in one place rather than in every
caller, and a caller who passed a standard-deviation profile instead would
under-drive every busy hour by its own square with nothing in the output to
show it.

The two channels **multiply**, because both are ratios on a variance: a busy
hour and a busy exogenous reading should reinforce rather than one silently
overwriting the other. The floor applies once to the product, since "a state
that cannot move at all" is a statement about the member and not about either
signal. `clock=None` leaves the old behaviour exactly as it was, which keeps
every measurement already taken through the wrapper valid.

**The wiring reproduces the hand-rolled arm exactly** - all 26 cells agree to
one decimal, from EURUSD's +142.5 to ETH's +367.6 and the generated markets'
-8.6 to +0.5. That equality is the only thing that makes the measurement above
a statement about the member rather than about a harness, so the harness now
runs both arms side by side and prints them in adjacent columns.

Using it on a live member is two lines:

```python
profile = Profile.fit(times, logs)          # on history, once
member = Driven(build=..., lever="level_wander", clock=profile.factor)
```

## What is still open

* **A weekly profile**, at `period=168`. The weekend gap makes the phase
  coverage uneven, which is precisely what the harmonic cap now counts.
* **Re-fit the profile periodically.** It is fitted once here, on half a
  series. Whether the session shape drifts over years is a separate
  measurement, and `wander` on the member is the mechanism if it does.
* **Which lever on which member.** The profile drove `level_wander` on a
  level-only `Seasonal` here. `kalman` carries integrated jerk and `reverting`
  a reversion rate, and whether the clock belongs on those levers or only on
  the level's is untested.

The harness is `research/ideas/seasonal_members.py`. The member and the
profile are `till_infinity/structures/statespace/seasonal.py`.
