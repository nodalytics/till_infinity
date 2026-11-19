# Skill and breadth: the fundamental law of active management (2026-11-19)

Why a 50.5% win rate can be a great business, and what that means for our signals.

## The law

Grinold's fundamental law of active management (Grinold and Kahn):

`IR ~= IC * sqrt(breadth)`

- **IC** (information coefficient) is skill: how well forecasts line up with what happens. Winning 50.5% of even-money
  bets is an IC of about 2 × 0.505 − 1 = 0.01, almost no skill.
- **Breadth** is the number of independent bets per year.
- So 50.5% is enough with enough independent bets. 10,000 a year gives IR ≈ 0.01 × √10,000 = 1.0; a million
  (Jane Street-style market making) gives about 10. A tiny edge, repeated at massive scale, becomes a great business.

## What it means for our results

1. **The edge has to survive costs on every bet.** Jane Street's 50.5% is after costs: they earn the spread; a
   1-15-minute signal here pays it. **Measured** in
   [`rsi-ma-momentum.md`](rsi-ma-momentum.md): **0.033 to 0.043 R at 15m and 0.067 to 0.091 R at 5m** on a 1 ATR
   stop, from the median recorded spread per feed. [`atr-ml.md`](atr-ml.md) puts the median 15m spread at **0.011 to
   0.041 ATR**. One minute is **not measured here** - the deep catalogue is 5-minute and the store holds under six
   days of 1m - so the ~0.15 R sometimes quoted for it is an extrapolation and labelled as one.

   At those costs the break-even win rate at 1:1 is **51.7-52.2% at 15m and 53.4-54.6% at 5m**, so 50.5% is three to
   nine times too small to clear the spread, and `sqrt(breadth)` multiplies a negative number just as happily.
   *(The earlier draft of this section claimed "0.05-0.15 R", an "FX sweep reversal at +0.01 to +0.03 R gross" and a
   "buy after weakness" worth "+5 points of take-profit probability". None of the three is in this repository.
   [`sweeps.md`](sweeps.md) measured ten sweep forms and found **-0.021R [-0.030, -0.012]**, "identified exactly,
   predicting nothing"; the +0.01 to +0.03 figure belongs to [`cascading.md`](cascading.md) and is a **rank
   correlation** for volatility cascading, not an R a trade; no rule called "buy after weakness" exists.)*
2. **Breadth means independent bets, and this is where the law bites hardest here.** A scan makes thousands of
   trades that overlap heavily: overlapping labels, the same move across correlated pairs, the same week. Measured
   directly - the RSI-and-average grid in [`rsi-ma-momentum.md`](rsi-ma-momentum.md) produced **1.3M trades on one
   instrument over two years** from 414 cells reading the same bars, which is nothing like 1.3M independent bets,
   and its Benjamini-Hochberg count was labelled anti-conservative for exactly that reason.
   [`overlapping-outcome-windows-leak`](persistence.md) is the sharpest instance: a short skip rule with a long
   forward window read direction AUC **0.79** and collapsed to **0.51** once the windows stopped sharing outcomes.

   *(The earlier draft said sample sizes are "divided by the holding time in the Bayesian work". What this repository
   actually records about holding time is a statement about **cost**, not sample size: "costs are linear in holding
   time while any edge is at best its square root"
   ([`a-theory-from-ohlc.md`](a-theory-from-ohlc.md), [`stop-free.md`](stop-free.md)). The nearest effective-sample-size
   work is Kish's n in [`streaming.md`](streaming.md), used to set a weighting temperature.)*
3. **What a qualifying lead would have to look like, since this repository does not currently hold one.** The shape
   the law wants is a small after-cost edge over many weakly-correlated bets. *(The earlier draft credited an "FX
   buy-after-an-H4-down-move lead" with **+0.08 R a trade on 765 trades across 20 pairs in 2 years** and a
   a replication on a third-party platform and a "forward watch". **No such result exists here** - no 765-trade
   or 20-pair figure appears in any document, and the only forward paper log on record belongs to `DISPLACE_C` in
   [`turn-follow-ups.md`](turn-follow-ups.md). Replication here runs on `nautilus_trader`, which is the only
   backtest engine this repository depends on.)*

   The closest live positives, both after their own controls, are **not** direction edges: contiguous activity over
   the next sixteen bars at AUC **0.8886** within volatility strata and **0.6588** inside the hour of day
   ([`persistence.md`](persistence.md)), and volatility expansion from compression at AUC **0.781** held out
   ([`expansion.md`](expansion.md)). Both forecast risk, not side, so neither enters the law as an IC on a bet.
4. **Next measurement.** The information ratio of each combination is the left side of the equation, and it is now a
   reported metric in the harnesses ([`rsi_momentum.py`](../ideas/rsi_momentum.py)). From an IR and a trade count the
   implied IC and the **effective** breadth follow, and the gap between effective breadth and the trade count is the
   number worth reading - point 2 is why.

## Measured: the breadth this desk actually has, and what IR = 1 needs

`information()` in [`rsi_momentum.py`](../ideas/rsi_momentum.py) now reports the
annualised IR beside the trade count, the **effective** bets a year and the IC
the pair implies. Breadth is deflated by the clustering present: whole days are
the block, so `var(mean)` from the day means is `v / d`, and against an
independent `s^2 / n` that gives an effective `n = s^2 * d / v`.

Two markets, 15m, the RSI-and-average grid's leading cells over 37 days:

| combination | IR | trades a year | **effective bets a year** | implied IC |
|---|---:|---:|---:|---:|
| `ma_pullback` ma50 mom5 R2 | +4.74 | 4,370 | **1,485** | +0.1230 |
| `trend_confirmed` rsi21 mom20 35 R2 | +1.64 | 6,297 | **2,135** | +0.0354 |
| `ma_pullback` ma20 mom5 R2 | +2.11 | 3,795 | **1,880** | +0.0486 |
| `trend_confirmed` rsi21 mom5 35 R2 | **-0.19** | 5,921 | **2,175** | -0.0040 |
| `trend_confirmed` rsi21 mom20 25 R2 | +0.49 | 7,238 | **2,611** | +0.0095 |

**Effective breadth is about a third of the trade count** - 1,485 to 2,611
against 3,795 to 7,238. That is the measured version of point 2, and it is the
number that decides whether "50.5% is enough" means anything here.

**It does not, at this clock.** At 2,000 effective bets a year, an IR of 1
needs an after-cost IC of `1 / sqrt(2000) = 0.0224`. The 15m spread costs
0.033 to 0.043 R a trade, which on an even-money bet is an IC of the same size,
so the **gross** IC required is about 0.056 to 0.065 - a gross win rate near
**52.8% to 53.3%**, not 50.5%. Jane Street's 50.5% works because it is already
net and because their breadth is a million, not two thousand: `0.01 *
sqrt(1,000,000) = 10` against `0.01 * sqrt(2,000) = 0.45`.

So the two levers are not symmetric for us. Raising breadth to a million is not
available on five instruments at 15m; lowering the cost per bet, or raising the
per-bet edge well past the spread, are the only directions that reach an IR
worth having.

Note also what the IR column does to the leaderboard: the top cell by seven-day
net R reads IR **-0.19** over the fuller sample, and the five cells' IRs run
from -0.19 to +4.74 in an order unrelated to their ranking. The IR is the better
metric precisely because it is harder to win by luck on a short window.

## Rules that change

The operator's position, 2026-11-19: *"we are not looking for the rules to carry from week to week or even from one
period to the other, we acknowledge the rules change and we are trying to adapt to the changing rules, this is part of
the reason we decided to use statespace."*

So the law is applied to the **adapting process**, not to any one rule:

- **The IC that matters is the adaptation's.** A rule whose edge lasts a week is not a failure; the question is whether
  the process that re-estimates the rules (the state-space filter, or any re-selection) forecasts the *next* period
  better than chance, after costs. That is measured strictly out of sample: estimate on data up to time t, forecast
  t + 1, score, move forward. A fixed rule's in-sample IC says nothing about it.
- **A null on one adaptation method is about that method - but it is a null on an *adapting process*, not on a fixed
  rule.** This needs stating precisely, because the loose version flatters the next idea. The walk-forward in
  [`rsi-ma-momentum.md`](rsi-ma-momentum.md) **re-selects from scratch every window**, so its result already is an
  adapting process's forward return: at a 7-day cadence **-0.0207 to -0.0464 R** a trade, at 3 days **+0.0330 R**, and
  on verification the 3-day cell did not survive - no market held across both four-year halves, gold showed the same
  statistic on **shuffled** days with the interval clear of zero, and AUDUSD showed it reversed with the interval clear
  of zero.

  So what those nulls close is **adapting by recent realised performance**, which is broader than "top-k". What they
  leave open is a *different estimator*: one with a memory model and an uncertainty attached, rather than a sample mean
  over a window. That is a real distinction and it is also a narrow one.
- **Breadth is counted on the adaptive bets.** Each forward period's independent bets add to breadth only if the
  forecast was made before the period began; re-fitting and scoring on the same period adds trades but no breadth.
- **Speed of adaptation is the trade-off to measure.** Adapt too slowly and the estimate lags the rule; too fast and it
  chases noise, which lowers IC. The filter's process noise (Q) sets that speed, so the forward IC as a function of Q
  is the curve that says how fast the rules change and how fast to follow them.

## Does this repeat a killed idea? No, and here is the boundary

[CLAUDE.md](../../CLAUDE.md) kills two Kalman designs, and the design below sits
on the right side of both - but the boundary is narrow enough to be worth
writing down.

- *"You cannot estimate more latent states than the observations identify."* An
  eight-dimensional state over a level's handful of touches tracked the prior
  and **reported confident numbers for quantities the data never constrained,
  silently**. What survived was `(price, slope)`, minimal and gated.
- *"Zone width as a Kalman dimension... width is not observed."* What was
  observed was a hit or a miss.

The design below estimates **one scalar per scenario, and it is directly
observed**: each trade's realised R *is* a noisy reading of that scenario's
edge. That is the surviving shape, not the killed one.

**Two caveats that follow from the same arithmetic, though.** First, the kill's
logic applies to any scenario that fires rarely - a cell with a handful of
trades in its life gets a confident posterior that is all prior, which is what
the minimum-trade floor and the deliberately coarse bands are for, and the
posterior width has to be reported alongside every estimate rather than only
the mean. Second, [`turns-fast.md`](turns-fast.md) found `vol` **alone** carried
a turn result that a richer model did not improve, so a scenario keyed on a
volatility band inherits that: the comparison that matters is within the band,
not across the bands, exactly as [`persistence.md`](persistence.md) measures
everything within volatility strata.

## Proposed: what worked lately, per scenario, with Monte Carlo deviation (2026-11-19)

The operator's idea: *"if statespace can look for what worked in the last 1 day to 1 week and applies it to the exact
same scenario using monte carlo to gauge the deviation rate, that would also help a lot."* A design that makes it
measurable:

1. **A scenario** is the state at the decision, known at the bar's close: the setup that fired and its context
   (instrument, session, volatility band, trend state, distance to the nearest level, ...), coarse enough that each
   scenario sees trades every day or two. "The exact same scenario" is the same cell.
2. **A state-space estimate per scenario.** Each scenario's edge μ (expected R a trade, gross first) is a random walk,
   μ_t = μ_{t−1} + η with variance Q, observed through its trades, r = μ + ε with variance R. A Kalman filter gives,
   at every bar, the estimate m and its uncertainty P. Q sets the memory: a half-life of one day to one week
   corresponds to a Q range, swept rather than chosen.
3. **Monte Carlo for the deviation.** From the posterior (μ ~ N(m, P)) and the scenario's recent residuals (resampled in
   day-blocks, so their clustering is kept), simulate the next period's trades many times. That gives the predicted
   distribution of the next period's result: its mean, its spread, and the chance it comes out below zero or below
   costs. The **deviation rate** is how often the realised result falls outside that predicted band.
4. **By horizon.** The operator, 2026-11-19: *"the monte carlo can also be period based saying how the deviation rate
   will be in the next 1 day to 1 week."* So the simulation runs for each horizon H from one day to one week, and the
   further ahead it looks, the more the edge itself can drift: the uncertainty grows as P_H = P + H·Q before the trades
   are drawn, and the number of trades in H follows the scenario's recent firing rate. Each horizon gets its own
   predicted band, its own chance of finishing below costs, and its own deviation rate. Short horizons are mostly the
   luck of a few trades; long ones mostly the edge moving, and where the two cross says how far ahead a forecast is
   still worth acting on.
5. **The decision.** Trade a scenario over the horizon the forecast still supports, only if the simulated chance that
   its edge beats costs is high enough, sized by how tight that horizon's band is.

How it is judged, out of sample (estimate to t, act on t + 1, roll forward):

- **Calibration first, per horizon:** realised results must land inside the 90% Monte Carlo band about 90% of the time,
  separately at 1 day, 2-3 days and 1 week. A band that is too narrow means the deviation is understated; that check
  comes before any P&L. Horizons overlap from one day to the next, so their calibration is scored on non-overlapping
  windows (or with the overlap accounted for), or the 1-week numbers count the same week several times.
- **Against controls:** the same filter on shuffled scenario labels (does the scenario carry information?), a
  static rule fitted once, and picking last week's leaders (already null). The filter has to beat all three after
  costs, per instrument as well as pooled.
- **Power:** on synthetic data with a planted edge that switches scenario every few days, the filter must track it,
  and the Q sweep shows how fast a switch it can follow.
- **The Q curve:** forward IC and calibration against the memory, one day to one week; the best Q says how fast the
  rules change.

## First result from the filter, and it fails the first test

[`scenario_filter.py`](../ideas/scenario_filter.py) implements the design below.
A first run - one instrument, two years, 15m, 144 scenarios, 1.3M trades,
7-day horizon - **fails calibration at both settings tried**, which is the
check the design puts before any P&L:

| memory | coverage of the 90% band | band width | deviation rate |
|---|---:|---:|---:|
| half-life 3 days | **0.978** | 3.168 R | 0.022 |
| static, `Q = 0` | **0.431** | 0.719 R | 0.569 |

One band is three times too wide and the other is half as wide as it needs to
be, so neither posterior is usable yet and the decision arm built on it returns
`-0.0463 R` against `-0.0476 R` for taking everything and `-0.0464 R` for a
same-rate coin - no separation, as expected from an uncalibrated band. The
useful part is that the failure is **two-sided**: a `Q` between those two
settings is where the coverage can be right, which is what the sweep is for and
is a stronger starting point than a single arm that merely looks wrong.

## Sources

- [The Fundamental Law of Active Portfolio Management](https://matthewcaseres.gitbook.io/scs/machine-learning-trading/fundamental-law-active-portfolio-management)
- [The Role of Skill & Breadth in Quant Investing (altaml)](https://altaml.com/insights/the-role-of-skill-and-breadth-in-quant-investing/)
- [The Role of Skill & Breadth in Quant Investing (Substack)](https://alphalayerai.substack.com/p/the-role-of-skill-and-breadth-in)
- [Don't bet the ranch: hit ratios, asymmetry and breadth (Fidante)](https://www.fidante.com/au/insights/dont-bet-ranch-hit-ratios-asymmetry-and-breadth)
- [Dispersion and alpha conversion (Morgan Stanley)](https://www.morganstanley.com/im/publication/insights/articles/dispersion-and-alpha-conversion.pdf)
