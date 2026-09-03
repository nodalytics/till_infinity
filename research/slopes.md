# What a rolling regression slope predicts

Asked 2026-09-03: take an online linear regression of price on time, and study
the slope itself — how its properties change, what follows a steep one, and in
particular what a slope of about zero means.

Measured over **2.99 million 1m bars across 53 feeds**, window 20 bars,
forward horizons of 5, 15 and 60 minutes.

## The design, and the control that makes it trustworthy

Everything is in volatility units so instruments pool: slope is expressed as
**sigma of a one-bar move, per bar**, and forward return as **sigma over the
horizon**, `sqrt(h)`-scaled so horizons compare. The regression window is
strictly past — slope over `[t-20, t)`, return over `(t, t+h]` — so no bar is
on both sides.

**Deriv's volatility indices are the control.** They are generated processes at
a stated volatility: a driftless random walk with no structure to find. Any
directional effect that appears there is a fault in the measurement rather than
a fact about markets. Every number below is reported for real instruments and
for the synthetic control side by side, and only the *difference* counts.

That control is what makes the rest of this document worth reading, and it is
the discipline [null.md](null.md) was written after failing to apply.

## 1. Direction: price leans *against* the recent slope

"Signed with slope" is the forward return multiplied by the sign of the slope,
so positive means continuation and negative means reversion.

| \|slope\| band | real market, 5m | 15m | 60m | control, 60m |
| --- | ---: | ---: | ---: | ---: |
| flattest fifth | +0.0075 | −0.0025 | −0.0058 | −0.0006 |
| second | −0.0279 | −0.0187 | −0.0110 | −0.0072 |
| **middle** | **−0.0563** | **−0.0333** | −0.0184 | +0.0097 |
| fourth | −0.0289 | −0.0204 | −0.0128 | +0.0062 |
| steepest fifth | −0.0182 | −0.0089 | −0.0149 | −0.0153 |

**Reversion, not continuation**, at every horizon and in almost every band. At
191,727 samples a band the standard error is about 0.0009, so −0.0563 is
roughly sixty standard errors — this is not sampling noise.

**And it is absent from the control.** There the same cells run ±0.015 with
mixed signs on 5,546 samples, where the standard error is about 0.013 — one
standard error, which is what a null should look like. The measurement is not
manufacturing the effect.

**But read the size before getting excited.** −0.056 sigma of a *one-bar* move,
at the horizon where it is strongest. That is a fraction of the cost to cross,
so this is a description of how price behaves rather than a trade. It is mildly
encouraging for a mean-reversion book — which is what a level model is — and it
is not an edge on its own.

Note also the shape: reversion is **strongest in the middle** and weakest at
both ends. A very flat slope reverts nothing because there is nothing to revert,
and the steepest fifth reverts least — which is where a trend, if there is one,
would be.

## 2. Magnitude: the slope is a volatility forecast

This is where the slope earns its keep, and the effect is large.

| \|slope\| band | \|return\| 5m | 15m | 60m |
| --- | ---: | ---: | ---: |
| flattest fifth | 0.2494 | 0.1867 | **0.1218** |
| second | 0.2567 | 0.1948 | 0.1373 |
| middle | 0.2883 | 0.2215 | 0.1687 |
| fourth | 0.3162 | 0.2629 | 0.2206 |
| steepest fifth | 0.4274 | 0.3890 | **0.3514** |

**Nearly three to one across the range at 60 minutes**, monotone at every
horizon. The steepest fifth is followed by 0.3514 sigma of movement against the
flattest fifth's 0.1218.

The control shows the same ordering far more weakly — 0.7345 to 0.8267 at 60m,
about 13% against the real market's 189% — so most, though not all, of this is
real. See the caveat in section 4.

## 3. Slope ≈ 0: a quiet state, unless it follows a steep one

The question that prompted this.

| state | \|return\| 5m | 15m | 60m |
| --- | ---: | ---: | ---: |
| unconditional | 0.3076 | 0.2510 | 0.1999 |
| **flat now** | 0.2494 | 0.1867 | **0.1218** |
| **flat now, steep one window ago** | 0.3003 | 0.2531 | **0.2094** |

**Flat usually means flat.** A slope in the flattest fifth is followed by 39%
less movement than average over the next hour. Quiet persists; that is
volatility clustering and it is the strong, boring answer.

**Unless it just stopped being steep.** The same flat reading, when the
previous window was in the top two-fifths, is followed by **72% more movement**
than an ordinary flat one — 0.2094 against 0.1218 — and slightly *more* than
the unconditional average. The coil is real: a slope that has gone flat after
being steep is a pause inside a move, not a resting state, and the two are
indistinguishable from the current slope alone.

That is the practical finding. **The slope's own history separates two states
that look identical**, and the separation is worth about 1.7x in expected
movement over the next hour.

The control shows the same direction at a tenth of the size (0.7345 → 0.7847,
about 7%), so this is mostly real and partly artifact.

## 4. What is not established

* **Part of "flat predicts quiet" is mechanical.** The control should show none
  of it and shows 7–13%. The likely cause is stale or repeated bars: a window
  with no movement produces both a zero slope and a small forward return
  without anything having been predicted. That sets the floor for how much of
  the real-market effect to discount, and it has not been separated out.
* **No cost is modelled.** Section 1's reversion is smaller than a spread, and
  section 2 and 3 are volatility forecasts rather than direction, so nothing
  here is a strategy as it stands.
* **One window length, one bar size.** W=20 on 1m bars. Whether the effect
  strengthens or vanishes at other scales is unmeasured, and a result that only
  exists at one arbitrary window is a result to distrust.
* **Pooled across instruments.** "Real market" mixes FX, indices, metals and
  crypto, which [failing.md](failing.md) shows behave differently.

## Where this would matter to the desk

The book already estimates volatility (`vol_bps`, GARCH, `forecast_bps`). The
question this raises is not "is the slope predictive" — it is — but **whether
the slope adds anything to the volatility estimate already in every signal**.
That is a one-column test against `vol_bps` and it has not been run.

The state in section 3 is the more interesting one, because it is not a
volatility level: *flat, having just been steep* is a condition no current
feature expresses, and it predicts a move without predicting its direction.
Two obvious uses, neither measured:

1. **Sizing and stop width.** A trade opened in that state should expect 1.7x
   the ordinary excursion, which is exactly what
   [planned/excursion.md](planned/excursion.md) wants to size stops from.
2. **The break gate.** `structures/breaking.py` asks whether a level breaks
   from arrival speed and depth. "Flat after steep" at the touch is a different
   question from either and is cheap to add.

The natural next measurement is the one this stopped short of: **the slope at a
level touch, against whether the level held** — which joins this to the thing
the desk actually trades.
