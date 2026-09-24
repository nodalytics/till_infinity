# The accumulator is the right instrument sold on the wrong processes

Run: `python research/harness/accumulators.py`

**Measured 2026-09-24**, against the live venue. The hypothesis was the desk's: an accumulator pays
for the market being quiet, this desk can forecast size but not direction, and
[`susceptibility.md`](susceptibility.md) already found a loud `chi` is followed by volatility
**falling** - +5 to +9 points on five of seven instruments, through a trailing-volatility decile
control. Pairing a volatility-down forecast with an instrument that pays for low volatility is a real
proposal, not an analogy, and it deserved a measurement.

| question | answer |
| --- | --- |
| is the accumulator fairly priced | **no.** 0 of 25 cells favourable, by two independent estimators |
| what does it cost | **-0.400% of stake per tick** at `g=0.03`; **-28.9%** held to the 85-tick cap |
| how is the edge set | a barrier at a **fixed 1.93 to 2.43 per-tick sigmas**, constant to 0.002 across five indices |
| how much would volatility have to fall to break even | **1.97% to 5.72%, median 2.51%** - a low bar |
| can `chi` deliver that here | **no, and not for want of signal strength** |
| why not | **accumulators are sold only on synthetics, and synthetics have no volatility to forecast** |

## The contract is not what its name suggests

    "After the entry spot tick, your stake will grow continuously by 3% for every tick that the
     spot price remains within the +- 0.05369% from the previous spot price."

**From the previous spot price, not from the entry.** So this is not a range bet over a window - it
is a bet that **no single tick jumps** more than a fixed fraction. The quantity to forecast is
per-tick volatility, not the width of an excursion.

That correction matters for the hypothesis rather than killing it: `chi` is computed from bar returns
over a window, and the two are linked through volatility clustering, but they are not the same
object. Deriv's own metadata labels the contract `sentiment: "low_vol"`, which agrees about the
direction of the bet.

## The break-even condition is exact, which is rare

Stake grows by `g` per surviving tick and a breach ends the contract at zero. Exiting after `n`
surviving ticks pays `stake * (1+g)^n`, so with per-tick survival probability `p`:

    E[payout] = p**n * stake * (1+g)**n        ->        break-even at   p * (1+g) = 1

    p_fair = 1 / (1+g)

**Independent of `n` and of the exit rule.** There is no optimal holding period and no take-profit
level to tune - either per-tick survival beats `1/(1+g)` or the contract loses, and no management
changes that. It is the cleanest fair-value condition any instrument in this folder has offered,
and it reduces the whole question to one number.

## Two independent estimators, and they agree

**Analytic**, using only the barrier Deriv quotes and the sigma the index's own name states - which
[`deriving.md`](deriving.md) and [`twins.md`](twins.md) confirm to within two standard errors:
`p = 2*Phi(b/s) - 1`, with `s` the per-tick standard deviation at two-second ticks on a continuous
calendar year.

**Empirical**, using only Deriv's published `ticks_stayed_in` survival history, as a censored MLE:
`p_hat = S/(S+B)` over `S` surviving ticks and `B` breaches. Censoring matters - contracts are capped
at `maximum_ticks`, and the naive `E[n] = p/(1-p)` understates `p`, which is a bias *toward* the
conclusion this study is looking for and therefore the one to remove.

| `g` | `p` analytic | `p` from survival | `p_fair` | edge | vol fall needed |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.01 | 0.98501 | 0.98650 | 0.99010 | **-0.00509** | 5.69% |
| 0.02 | 0.97699 | 0.97727 | 0.98039 | **-0.00340** | 2.59% |
| 0.03 | 0.96699 | 0.96982 | 0.97087 | **-0.00388** | 2.28% |
| 0.04 | 0.95751 | 0.96271 | 0.96154 | **-0.00402** | 1.99% |
| 0.05 | 0.94652 | 0.94238 | 0.95238 | **-0.00586** | 2.51% |

*(`R_100`; the other four indices are the same to three decimals - see below.)*

The two estimators differ by a mean of **0.00299** with 20 of 25 cells inside 0.005, and they share
no inputs. Where they agree the answer is not an artefact of either.

**0 of 25 cells is favourable.** At `g=0.03` on `R_100`, `p*(1+g) = 0.99600`, so the contract loses
**0.400% of stake per tick** and **28.9% held to its 85-tick cap**.

## The edge is a designed constant, which validates the model

Express each barrier in per-tick sigmas and the table collapses:

| `g` | `R_10` | `R_25` | `R_50` | `R_75` | `R_100` | spread |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.01 | 2.434 | 2.432 | 2.433 | 2.432 | 2.433 | 0.0024 |
| 0.03 | 2.132 | 2.132 | 2.132 | 2.132 | 2.132 | **0.0008** |
| 0.05 | 1.930 | 1.931 | 1.931 | 1.931 | 1.931 | 0.0016 |

Deriv sets the barrier at a fixed number of standard deviations, identical across five indices
spanning a **tenfold** range of sigma. Two things follow. First, the house edge is deliberate and
uniform rather than an accident of one index's parameters. Second - and this is why the table is
here - **it validates the analytic model**: a wrong tick interval or a trading-year convention would
still produce a constant ratio but at the wrong level, and `p` would then disagree with the survival
history. It does not.

## The hypothesis fails, and not because the signal is weak

The bar was stated before the measurement: **volatility must fall by a median 2.51%** for the
contract to break even. That is a *low* bar. Realised volatility varies by far more than 2.51%, so
had this been an instrument on a real market, the hypothesis would be live and worth a tick-level
study.

It is not live, for a structural reason:

* **Accumulators are offered on 27 of 89 instruments, and every one is synthetic** - the eight
  `1HZ*`, the five `R_*`, and fourteen Boom/Crash. **No forex pair, no metal, no crypto.**
* **The synthetics are geometric Brownian motion at a published constant sigma.**
  [`deriving.md`](deriving.md) measures it and cannot distinguish the drift from zero; the volatility
  is a parameter, not a process. **There is no volatility variation on `R_100` to forecast.**
* **And `susceptibility.md` already recorded exactly this**, as a control it ran for a different
  reason: `chi`'s lift on the Volatility indices is **-1.1% to +0.3%** against +5 to +9 points on the
  real instruments. A harness reporting skill on a constant-sigma process would be broken. It
  reported none.

So the forecast exists on the instruments where the contract is not sold, and the contract is sold on
the instruments where the forecast cannot exist. The 2.51% bar is never approached because the
quantity it is a bar on does not move.

## The pattern, which is the transferable finding

This is the **second** time in one day that the same shape has closed a Deriv hypothesis:

* [`deriving.md`](deriving.md) derives a `Phi(-x)/Phi(-1.322x)` barrier mispricing - 1.71x at one
  sigma - for products priced off a **Jump** index's name. Deriv sells **no barrier product on the
  Jumps**: only `CALL`/`PUT` at 1d-365d, digits over ticks, and multipliers. The volatility indices
  carry the entire barrier family, and their pricing is correct at 1.007.
* Here, the accumulator is the one contract shape matching what this desk forecasts, and it is sold
  only where the process has nothing to forecast.

**Read together these are not two coincidences.** A venue can write exotic contracts on processes it
generates itself, because it knows sigma exactly and there is no information asymmetry to lose to.
On the real instruments - where a forecast is possible - it sells vanilla directional binaries at a
**12% to 15.6%** margin ([`deriv-payouts.md`](deriv-payouts.md)). The product range and this desk's
edge are close to disjoint, and the disjointness is rational product design rather than bad luck.

That is the thing to carry to the next venue: ask which instruments carry the exotic contracts
*before* pairing a signal to a payoff.

## What would reopen this

Narrow and concrete, so it can be checked rather than remembered:

* **Deriv listing `ACCU` on a real instrument.** The bar is a 2.51% fall in per-tick volatility, the
  signal exists on real markets at +5 to +9 points, and `accumulators.py` re-runs in a minute. This
  is the one trigger worth watching for.
* **The barrier widening.** The edge is a constant 1.93-2.43 sigmas today. If competition moved it
  past the break-even 2.18 sigmas at `g=0.03`, the arithmetic changes with no signal required.
* **A tick-level `chi` study**, but only after one of the above. Testing whether bar-window `chi`
  forecasts per-tick survival on a constant-sigma process is measuring a null on purpose.

**What is not established**: `ticks_stayed_in` may include contracts closed voluntarily by a trader
taking profit, which would understate survival by an unknown amount. That is why the analytic
estimate is primary and this one is corroboration - and why their agreement to 0.003, given they
share no inputs, is the load-bearing observation rather than either number alone.
