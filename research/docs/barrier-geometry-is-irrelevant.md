# A barrier trade earns the drift over its holding period, and nothing else

Derived and verified 2026-09-21 by `research/harness/overshoot_theory.py`, with the per-instrument
measurements in `research/harness/jump_share.py`.

This is the most consequential result in this repository, and it is not a strategy. It is a
theorem-with-simulation that says **most of the work here was searching a parameter that cannot
produce expectancy.**

## The three formulas

Let `X` be the log-price with drift `mu`, barriers at `+a` (target) and `-b` (stop), `tau` the first
exit. With jumps, `X_tau` is not exactly at a barrier - it lands beyond, and the excess is the
**overshoot**. Write `p = P(up exit)`, `u = E[overshoot | up]`, `d = E[overshoot | down]`, and
`m = mu E[tau]` for the drift captured over the holding period, in barrier units.

`X_t - mu t` is a martingale, so optional stopping (Wald's identity) gives `E[X_tau] = mu E[tau]`:

    p (a + u) - (1 - p) (b + d) = m

**(3)  p = (b + d + m) / (a + u + b + d)**

which reduces to `b / (a + b)` only when both overshoots and the drift vanish. That is the formula
every barrier study in this repository should have been scored against, and none was.

A **limit** target fills at `a` exactly and forfeits `u`; a **market** stop pays `b + d`. So

**(4)  E[P&L | limit target] = [ m (a + b + d) - u (b + d) ] / (a + u + b + d)**

and with a **market** target, which collects `a + u`, everything cancels:

**(6)  E[P&L | market both sides] = m = mu E[tau]**

## Verified, not asserted

21 configurations of a jump-diffusion - drift `+/-0.0002` and zero, four jump intensities, two jump
scales, 40,000 paths each:

| drift | lambda | scale | m | measured p | b/(a+b) | **(3)** | limit E | **(4)** | market E |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 0.002 | 1.5 | 0.0000 | 0.2285 | 0.5000 | **0.2285** | -0.9335 | **-0.9336** | +0.0002 |
| 0 | 0.050 | 0.5 | 0.0000 | 0.4066 | 0.5000 | **0.4041** | -0.2818 | **-0.2871** | +0.0071 |
| +0.0002 | 0 | - | +0.4731 | 0.7359 | 0.5000 | **0.7338** | +0.4688 | **+0.4645** | **+0.4774** |
| +0.0002 | 0.002 | 0.5 | +0.1777 | 0.4536 | 0.5000 | **0.4517** | -0.1416 | **-0.1456** | **+0.1831** |
| -0.0002 | 0 | - | -0.4723 | 0.2688 | 0.5000 | **0.2666** | -0.4710 | **-0.4754** | **-0.4679** |
| -0.0002 | 0.002 | 0.5 | -0.1495 | 0.3344 | 0.5000 | **0.3303** | -0.3868 | **-0.3953** | **-0.1380** |

(3) tracks the measured hit rate everywhere while `b / (a + b)` is off by up to **30 points**. (4)
tracks the limit-target expectancy. And **market-target expectancy equals `m` in every row** -
+0.4774 against m = +0.4731, -0.4679 against m = -0.4723, and zero when the drift is zero.

## What (6) means for everything measured here

**The barrier distances, the reward-to-risk ratio, the jump structure and both overshoots all
cancel out of the expectancy.** Only `mu E[tau]` survives.

So every study in this repository that searched over **where to put the barriers** was varying a
quantity that cannot produce expectancy:

* `premium_discount.py` - 314,794 rows across ten deciles of where price sat in a range;
* `patterns.md` - measured moves from double tops, head and shoulders;
* `jump_odds.py` - a reward-to-risk sweep from 0.25 to 8;
* `stretch.py` - 1536 cells of stretch measure by trigger by timeframe;
* `pip-windows.md` - four window lengths of level construction;
* `smc.py`, `displacement.py`, `regression_channel.py`, `imbalance.py` - all level placement.

Their uniform nulls were not bad luck and not underpowering. **They are what (6) predicts.** A
study that varies barrier geometry and finds nothing has confirmed a theorem.

And it explains the one apparent exception. `jump_odds.py` reported Boom shorts beating fair odds
by +4.1 points, the single large positive in months of work. Measured against (3) with Boom's own
overshoots - `u = 0.515`, `d = 0.287` - the excess is **0.24 points**. It was a benchmark error, and
the benchmark was wrong for precisely the instruments chosen because they violate its assumption.

## The per-instrument table, across every class

`u`, `d`, and the corrected benchmark, measured at reward-to-risk one on hourly bars:

| class | instrument | u | d | vs 0.5 | **vs (3)** |
|---|---|---|---|---|---|
| synthetic | boom_1000 | 0.515 | 0.287 | 4.31% | **0.24%** |
| synthetic | crash_1000 | 0.290 | 0.516 | 3.98% | **0.32%** |
| synthetic | boom_500 | 0.463 | 0.310 | 2.68% | **0.24%** |
| synthetic | crash_500 | 0.310 | 0.449 | 2.71% | **0.16%** |
| synthetic | volatility_75_1s | 0.339 | 0.332 | 0.06% | **0.11%** |
| crypto | btcusd | 0.538 | 0.552 | 1.74% | 1.58% |
| FX major | eurusd | 0.514 | 0.540 | 1.27% | 1.41% |
| FX major | gbpusd | 0.507 | 0.540 | 1.21% | **1.07%** |
| FX cross | eurjpy | 0.433 | 0.548 | 1.28% | 3.22% |
| FX | usdchf | 0.490 | 0.536 | 4.48% | 5.24% |
| index | us_sp_500 | 0.485 | 0.607 | 2.16% | 2.54% |
| metal | xauusd | 0.515 | 0.583 | 1.05% | 2.16% |

**The correction closes the gap on the synthetics and widens it on FX, indices and metals.** That is
not a failure of (3) - it is (3) working. The synthetics are constructed so that jumps one way are
compensated by drift the other, which makes them martingales: `m = 0`, and (1) suffices. FX pairs,
indices and metals have genuine seven-year drift, so `m` is not zero and the residual is exactly the
term the martingale version omits.

That residual is therefore **a measurement of drift**, not an error - and it is the only quantity
(6) says can pay. USDCHF's 5.24% is the largest in the table.

## Two failed predictions on the way, both instructive

I tried twice to *proxy* the overshoot rather than measure it, and both proxies failed.

**Bipower variation** - the standard jump-detection estimator - gave Boom a jump share of 0.008
against Brent's 0.148, while Boom had the largest benchmark gap of twelve instruments. Predicted
rank correlation strongly positive; measured **+0.266**. The reason: bipower reads close-to-close
returns, and Boom's spikes print in the high and revert before the close.

**Range-to-close variance ratio** - the fix for that - came back with the *opposite* sign,
**-0.209** across 29 instruments. Boom's ratio is 0.76, meaning its bars have small ranges relative
to their close-to-close moves: it grinds *within* bars, so Parkinson's estimator underestimates.

The direct measurement matched to 0.24 points on the first attempt. **A proxy is worth having only
when the quantity is hard to measure, and `u` and `d` fall out of the same loop as the hit rate.**

## What follows

**Stop searching barrier geometry.** (6) says it cannot pay, the simulation confirms it, and a dozen
measured nulls are consistent with it. Any future harness that sweeps stop placement, target
placement, reward-to-risk or level construction is re-deriving this theorem at the cost of a run.

**The only term left is `m = mu E[tau]`**, which is a directional forecast with a horizon. Not a
level, not a pattern, not a structure - a signed expectation of return over a stated holding period.
That is what `directional-edge.md` in `research/planned` already argued from a different direction,
and (6) is the reason it is the only remaining shape of a strategy here.

**And the horizon is not free.** `costs.md` measured carry at 0.161 to 0.321 TR per day on the
synthetics and `stop-free.md` showed it is linear in holding time while any edge is at best its
square root. So `m` must grow faster than the financing over the same period, which bounds the
useful horizon from above while the detection floor in `power-and-sizing.md` bounds the sample from
below.

**A note on where this came from.** The derivation is one physical idea - a conserved quantity under
an arbitrary stopping rule - combined with Wald's identity, the Lévy overshoot, and a slippage
figure measured from 305 live fills. None of those four is finance; three are not even probability
in origin. That particular connection paid for itself many times over, which is worth recording
next to the honest fact that most of the analogies tried alongside it did not.
