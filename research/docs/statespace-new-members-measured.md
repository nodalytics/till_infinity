# The new members on real instruments, with volume

`fractional`, `switching`, `panel` and `driven` were built against synthetic
fixtures that each isolated the thing the member was for. That is the right
way to build them and no evidence at all about markets. Harness:
`research/ideas/new_members.py`. 1h bars, six instruments including BTC, held
out by time - the back 40% scored, likelihood zeroed at the boundary.

## 1. Held-out likelihood: the walk wins, and `switching` is the only member near it

| | walk | linear | reverting | fractional | switching |
|---|---|---|---|---|---|
| eurusd | **-34007** | -67280 | -188210 | -304708 | -34271 |
| xauusd | -23133 | -43929 | -121537 | -390393 | **-22789** |
| gbpusd | **-34347** | -66529 | -191447 | -231471 | -35290 |
| usdjpy | **-12260** | -23784 | -68188 | -100341 | -14034 |
| btcusd | **-27129** | -57882 | -156874 | -222759 | -29578 |
| v75 | **-13078** | -26677 | -74989 | -151096 | -14863 |

**`switching` beats the random walk on gold** (-22789 against -23133) and is
within a few percent on four of the other five. Nothing else is close:
`linear` is roughly twice as bad, `reverting` five times, and `fractional`
worst of all.

**This is a comparison of defaults, not of model classes**, and the caveat is
load-bearing. None of these was fitted here. `fractional`'s five modes carry a
`wander` of 1e-3 chosen to make a synthetic fixture behave, and a member with
five states and an unfitted noise is not being given a fair hearing - it is
being shown to be unusable *as shipped*, which is a different and smaller
claim. `diagnostics.fit_both` exists and this does not use it.

What does survive the caveat is the ordering's shape: the members that lose
worst are the ones carrying the most unfitted parameters, and the one that
competes is the one whose extra structure is a *discrete* regime rather than
another continuous rate.

## 2. Volume through `Q` helps, and most where the volume is real

`driven.Driven` scales a member's process noise by log volume against its own
trailing mean. `gain = 0` reproduces the member exactly, so the row measures
the input rather than the wrapper.

| | gain=0 | gain=0.5 | gain=2 | best gain |
|---|---|---|---|---|
| **btcusd** | -57882 | -57090 | **-54881** | **+3001** |
| gbpusd | -66529 | -67407 | **-64825** | +1704 |
| eurusd | -67280 | -68348 | **-66064** | +1216 |
| v75 | -26677 | -26701 | **-26062** | +615 |
| usdjpy | -23784 | -24208 | **-23230** | +554 |
| xauusd | **-43929** | -44547 | -44127 | -198 |

**This is the first positive result for the exogenous input channel**, and it
arrives through the door the evidence pointed at. `inputs.py` built the
channel; `B u` was the obvious wiring and is a *mean* term; the quantities the
channel actually carries - activity, session share, volume - are variance
effects, so `Q` was the prediction and `Q` is what works.

**BTC gains the most by a factor of two**, and BTC is the only instrument here
whose volume is traded size rather than a tick count. That is the ordering a
real effect should have, and it is the second time today the same pattern has
appeared: real volume beats a tick count.

Gold is the exception and loses slightly at every gain. Five of six is a
pattern, not a law.

## 3. The panel fails on these instruments, for a reason worth keeping

| | held-out likelihood |
|---|---|
| panel, one factor | **-25,607,817** |
| six independent `linear` | -86,025 |

Three hundred times worse. That is not "the factor is decoration" - it is the
model being used where its assumption does not hold.

`Panel` says the instruments share a factor and that each one's deviation from
it **reverts to an anchor**. Six instruments spanning two FX majors, gold,
crypto and a synthetic index do not have a stable relationship, so the
idiosyncratics are pinned near offsets fixed at the first reading while the
real relative values wander for four thousand hours. The filter is then
confidently wrong, continuously, which is exactly what a likelihood of that
size means.

**The member is not refuted; its application is.** The synthetic test that
built it - a genuine common factor with reverting deviations - it passes, and
the separation scales with width as the theory says. What this measures is
that *these six instruments are not a basket*, which is a fact about the
instruments. A panel wants cointegrated legs, and finding them is
`basket_choice.py`'s job.

## 4. `switching`'s balance reading is a reading of the model

| instrument | share of time in balance |
|---|---|
| eurusd | 0.154 |
| xauusd | 0.124 |
| gbpusd | 0.151 |
| usdjpy | 0.151 |
| btcusd | 0.125 |
| **v75** | **0.176** |

**v75 is generated and has no auction, and it reads the highest of the six.**

That settles the question the member was built to ask. Auction market theory
claims price is in balance about 70% of the time; this reads 12-18%, and -
decisively - it does not distinguish six real markets from a synthetic one
with no participants. A reading that is the same on a market and on a
random-number generator is a reading of the model.

Two honest qualifications. The regime durations are **asserted** (24h and 4h),
and a different prior would move the level - though it would have to move the
*ordering* to rescue the claim, and v75 being highest is an ordering. And the
member's discrimination is known to be asymmetric: it is sharp about
imbalance and weak about balance, so the balance share is the half it
measures worst.

## What this changes

* **Keep `driven`**, and fit its gain. The first thing the input channel has
  done.
* **Keep `switching`**, which is the only member competitive with the walk,
  and fit its durations before quoting any balance share.
* **Do not use `panel` on an arbitrary set of instruments.** It needs a basket
  that is actually a basket.
* **`fractional` needs fitting before it is judged.** Five states at a default
  noise is not a model class being tested.
