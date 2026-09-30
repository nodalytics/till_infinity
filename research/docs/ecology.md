# Adaptive market ecology: do strategies die of overcrowding, and does alpha come back?

Harness: [`research/harness/ecology.py`](../harness/ecology.py). Lab runs 2026-09-30:
`logs/ecology_{species,ga,contagion}.log`.

## The question

The user asked: does a strategy's profitability decline because it stops working, or because its
population grows too large? And can the evolution of strategy populations explain why alpha decays
and reappears? Three sciences make testable claims about this:

- **Population ecology** says returns fall as a strategy gets crowded (density dependence), and
  profitability mean-reverts: success attracts capital, capital crowds the trade, and the leavers
  let it recover. Strategies also interact like predator and prey.
- **Evolutionary biology** says selected strategies are adapted to the past environment and lose
  fitness when it moves on. Selection under costs should favour slower strategies.
- **Epidemiology** says shocks spread like infections. A reproduction number above 1 should precede
  cascades, and the susceptible pool (crowded, levered positioning) should feed them.

Everything was pre-registered in the harness docstring. The control is walks we generate: GARCH(1,1)
with t(5) innovations, which cluster volatility like markets but contain no participants, so no
ecology. Deriv is scored as a market, but it has no participant ecology by construction.

## Method

**Species.** Each is a daily gross return, volatility-scaled so a position of 1 is one daily
standard deviation, and equal-weighted across a family's instruments:

- `tsmom21`, `tsmom63` and `tsmom252`: time-series momentum;
- `rev5`: short-term reversal;
- `donchian`: 55-day breakout with a 20-day exit;
- `rsi2`: Connors RSI(2);
- `carry`: the policy-rate differential, FX only, from [`carry.md`](carry.md)'s rates;
- `volsell`: a short-straddle proxy, `1 - (r / sigma)^2`, using the VIX-implied sigma on the S&P
  and the trailing EWMA elsewhere;
- `zone`: the production zone fade, from [`indicators.md`](indicators.md)'s touch trades.

**Families:** FX (14 pairs, from 1990), metals (XAU and XAG), crypto (BTC, ETH and SOL), the S&P 500
(the only index history on the lab), and six Deriv indices.

**The tests:**

- **1a, decay and recovery:** future 6-month species return regressed on the past 12 months,
  monthly, with Newey-West errors. Ecology predicts a negative slope.
- **1b, density dependence:** the next 21 days' return regressed on a population proxy. The proxies
  are:
  - *consensus*, |mean position| across instruments;
  - *CFTC*, speculators' net positioning on the species' side (FX);
  - *funding*, perpetual funding on the species' side (crypto, 2022 onward only).

  Each is checked against a circular-shift null of the proxy and against the walks.
- **1c, predator and prey:** a monthly VAR(1) among momentum, reversal and breakout.
- **2, evolution:** a genetic algorithm with 80 genomes × 30 generations over the rule families and
  their parameters, plus a holding-smoothing gene. Fitness is net Sharpe on the first 60%. The
  fittest rule is judged out of sample against 500 random rules, with probabilistic and deflated
  Sharpe (2,480 evaluations, about 496 effective). The GA is also rerun without costs, to see
  whether costs select slower strategies.
- **3, contagion:** 10 Binance perpetuals, hourly. A shock is |r| > 4× the trailing 500-hour mean
  (the rule in `shocks.py`), and the target is a shock in the next 4 hours. The baseline is the shock
  forecaster's features. Added on top:
  - a Cori-style reproduction ratio R(t) of market-wide shock incidence;
  - a stationary Hawkes intensity fitted on the training block;
  - other coins' shocks in the last 6 hours;
  - the susceptible pool: funding and open-interest crowding.

## Results

**1a. Profitability does not mean-revert beyond what arithmetic produces.** 0 of 39 species-families
pass: negative slope, t ≤ −3, both halves, BH, outside the walks. Overall, 15 of 39 slopes are
negative (5 at t ≤ −2, 1 at t ≥ 2). The walks are the reason a negative slope proves nothing here:
regressing future returns on overlapping past returns is biased negative, and memoryless walks alone
put t as low as −3 to −6.

| species | family | slope t (halves) | walks' 95% band |
|---|---|---|---|
| rsi2 | FX | −2.99 (−1.76 / −3.16) | [−2.93, +1.88] |
| tsmom63 | metals | −2.46 (−1.60 / −2.13) | [−3.05, +1.45] |
| volsell | Deriv | −3.29 (−2.92 / −6.03) | [−5.55, +1.22] |
| tsmom63 | FX | +1.79 | [−3.55, +1.81] |

**1b. No density dependence survives.** 0 of 44 (species × proxy) pass, and the signs split:
17 negative, 27 positive, 2 at t ≤ −2 and 2 at t ≥ 2.

| species | family | proxy | slope t (halves) | shift-null P | verdict |
|---|---|---|---|---|---|
| rsi2 | crypto | funding | **−3.49** (one half only) | 0.00 | fails both-halves: funding data start in 2022 |
| rev5 | crypto | funding | −2.97 (one half only) | 0.00 | the same |
| rsi2 | FX | consensus | **+3.37** (+3.38 / +1.30) | 1.00 | the wrong sign: more consensus, *better* |
| rsi2 | S&P | consensus | +3.35 (+2.81 / +1.86) | 1.00 | the wrong sign |
| tsmom21 | FX | CFTC | +1.84 (+4.06 / −0.97) | 0.90 | unstable |

The one hint of ecology is crypto's mean-reversion species. When funding sits on the same side, the
species does worse (t −3.5 and −3.0, far outside the shift null). Crowded perpetual positioning is
the only place a population effect shows, and it's the same effect [`crowding.md`](crowding.md)
found as a weak reversal (−0.03). With funding data covering only one half, it can't pass.

**1c. No predator and prey.** No cross-species lag reaches |t| 3, apart from the S&P, where breakout
predicts reversal (t +3.0) and momentum predicts reversal (t +2.1). Those are single cells among
45 with no counterpart in other families.

**2. Evolution overfits, exactly as it does on walks.**

| family | fittest out-of-sample Sharpe (train) | beats random rules | DSR |
|---|---|---|---|
| FX | −0.06 (+0.69) | 52% | 0.000 |
| metals | +0.25 (+0.80) | 59% | 0.031 |
| crypto | +0.58 (+1.94) | 91% | 0.003 |
| S&P | −0.01 (+0.72) | 28% | 0.004 |
| Deriv | +0.24 (+1.16) | 56% | 0.056 |
| walks, FX-shaped | −0.09 (+0.46) | 58% | 0.002 |
| walks, crypto-shaped | +0.55 (+1.02) | 74% | 0.087 |

- **Fitness decays out of sample by 0.55-1.36 Sharpe in every family, and by 0.47-0.56 on walks.**
  The "alpha decay" of evolved rules is selection bias.
- **Costs push selection toward slower rules only where there was room.** On the S&P, the fittest 20
  turn over 0.063/day with costs against 0.206 without, as reversal gives way to momentum. On walks
  (crypto-shaped) it's 0.001 against 0.012. Elsewhere the populations had already converged on slow
  rules. So cost-driven selection is visible, but it produces no out-of-sample edge.

**3. Contagion is real as description and adds nothing as a forecast.**

| added to the shock forecaster (AUC 0.752) | AUC gain [95% CI] | halves | walks' gain |
|---|---|---|---|
| R(t) | −0.0002 [−0.0042, +0.0032] | −0.0007 / +0.0003 | up to +0.0015 |
| Hawkes intensity | −0.0010 [−0.0027, +0.0008] | −0.0016 / −0.0005 | up to +0.0001 |
| other coins' shocks, 6h | +0.0008 [−0.0007, +0.0027] | +0.0004 / +0.0011 | up to +0.0004 |
| susceptible (funding, OI) | −0.0002 [−0.0022, +0.0019] | −0.0006 / +0.0002 | walks have none |
| all | +0.0014 [−0.0021, +0.0044] | +0.0014 / +0.0014 | up to +0.0014 |

- **Crypto shocks self-excite more than a common-volatility walk:** Hawkes branching n = 0.61,
  against 0.38-0.41 on walks with a common GARCH factor.
- **R(t) > 1 precedes cascades** (≥ 3 coin-shocks in 4 hours) at 18.3% against 8.8%, a 2.07× lift.
  The walks show 1.41-1.59×.
- The shock forecaster's own inputs (volatility state and its own recent shocks) already carry this.
  Nothing epidemiological passes the bar of +0.01 AUC.

**Also seen, not a question asked:** the S&P short-straddle proxy with VIX-implied variance has a
gross Sharpe of +5.6. That is the well-known variance risk premium (implied above realised). It's
measured without option costs, margin or crash sizing, and the desk has no options.

## What this means

- **Profitability here doesn't behave like a population.** The desk's markets show no reliable
  decay-and-recovery cycle, no density dependence and no predator-prey interaction beyond what
  arithmetic produces on memoryless walks. The pattern that looks like "alpha decays" in evolved
  rules is selection bias, and it's the same on walks. So the answer to the user's question, for
  these instruments and horizons, is neither: the strategies tested rarely had a lasting edge to
  lose.
- **The one ecological trace is crowding in crypto perpetuals.** Mean-reversion does worse when
  funding sits on its side, but the data span only half the sample. It's worth re-testing when a
  longer funding history exists, and it agrees with [`crowding.md`](crowding.md).
- **Contagion is a description, not a new forecast.** Crypto shocks cluster more than volatility
  alone explains (branching 0.61), and R(t) marks cascade-prone hours. The production shock
  forecaster already carries that information, so nothing goes to production.
- **Limits:**
  - daily bars and a handful of instruments per family (one index, three coins);
  - population proxies that are indirect, since the market's real strategy populations are
    unobserved;
  - no data on the desk's competitors.

  An agent-based market would test the mechanism directly, but it would test a model of a market,
  not these markets.
