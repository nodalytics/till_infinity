# Skill and breadth: the fundamental law of active management (2026-11-19)

Why a 50.5% win rate can be a great business, and what that means for our signals.

## The law

Grinold's fundamental law of active management (Grinold and Kahn):

$$\text{IR} \approx \text{IC} \times \sqrt{\text{breadth}}$$

- **IC** (information coefficient) is skill: how well forecasts line up with what happens. Winning 50.5% of even-money
  bets is an IC of about 2 × 0.505 − 1 = 0.01, almost no skill.
- **Breadth** is the number of independent bets per year.
- So 50.5% is enough with enough independent bets. 10,000 a year gives IR ≈ 0.01 × √10,000 = 1.0; a million
  (Jane Street-style market making) gives about 10. A tiny edge, repeated at massive scale, becomes a great business.

## What it means for our results

1. **The edge has to survive costs on every bet.** Jane Street's 50.5% is after costs: they earn the spread. Our
   1-15-minute signals pay the spread on every trade, about 0.05-0.15 R. Several of our signals do have a small
   positive IC before costs, for example the FX sweep reversal (+0.01 to +0.03 R gross) and "buy after weakness" (+5
   points of take-profit probability). After costs the IC goes to zero or below, and √breadth multiplies a negative
   number just as happily.
2. **Breadth means independent bets.** Our 1-minute scans make thousands of trades, but they overlap heavily:
   overlapping labels, the same move across correlated pairs, the same week. The effective breadth is far smaller
   than the trade count, which is why sample sizes are divided by the holding time in the Bayesian work.
3. **Where the best lead stands.** The FX buy-after-an-H4-down-move lead made +0.08 R per trade on 765 trades across
   20 pairs in 2 years: a positive edge after costs, with real breadth. It is exactly the "small edge, many bets" shape
   the law describes, if it holds; the QuantConnect replication and the forward watch will tell.
4. **Next measurement.** The information ratios of each combination (the scan now running) are the left side of
   the equation. From them, each combination's implied IC and effective breadth follow, to see whether anything has a
   positive after-cost IC worth scaling. Results to be added here when the scan finishes.

## Rules that change

The operator's position, 2026-11-19: *"we are not looking for the rules to carry from week to week or even from one
period to the other, we acknowledge the rules change and we are trying to adapt to the changing rules, this is part of
the reason we decided to use statespace."*

So the law is applied to the **adapting process**, not to any one rule:

- **The IC that matters is the adaptation's.** A rule whose edge lasts a week is not a failure; the question is whether
  the process that re-estimates the rules (the state-space filter, or any re-selection) forecasts the *next* period
  better than chance, after costs. That is measured strictly out of sample: estimate on data up to time t, forecast
  t + 1, score, move forward. A fixed rule's in-sample IC says nothing about it.
- **A null on one adaptation method is about that method.** "Last week's top combinations have no reliable edge over
  shuffled ones next week" refutes *picking last week's leaders* as an adaptation rule. It does not refute adapting:
  a filter that weighs recent evidence by its noise, as the state-space models do, is a different estimator and gets
  its own forward test.
- **Breadth is counted on the adaptive bets.** Each forward period's independent bets add to breadth only if the
  forecast was made before the period began; re-fitting and scoring on the same period adds trades but no breadth.
- **Speed of adaptation is the trade-off to measure.** Adapt too slowly and the estimate lags the rule; too fast and it
  chases noise, which lowers IC. The filter's process noise (Q) sets that speed, so the forward IC as a function of Q
  is the curve that says how fast the rules change and how fast to follow them.

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
4. **The decision.** Trade a scenario next period only if the simulated chance that its edge beats costs is high
   enough, sized by how tight the band is.

How it is judged, out of sample (estimate to t, act on t + 1, roll forward):

- **Calibration first:** realised results must land inside the 90% Monte Carlo band about 90% of the time. A band
  that is too narrow means the deviation is understated; that check comes before any P&L.
- **Against controls:** the same filter on shuffled scenario labels (does the scenario carry information?), a
  static rule fitted once, and picking last week's leaders (already null). The filter has to beat all three after
  costs, per instrument as well as pooled.
- **Power:** on synthetic data with a planted edge that switches scenario every few days, the filter must track it,
  and the Q sweep shows how fast a switch it can follow.
- **The Q curve:** forward IC and calibration against the memory, one day to one week; the best Q says how fast the
  rules change.

## Sources

- [The Fundamental Law of Active Portfolio Management](https://matthewcaseres.gitbook.io/scs/machine-learning-trading/fundamental-law-active-portfolio-management)
- [The Role of Skill & Breadth in Quant Investing (altaml)](https://altaml.com/insights/the-role-of-skill-and-breadth-in-quant-investing/)
- [The Role of Skill & Breadth in Quant Investing (Substack)](https://alphalayerai.substack.com/p/the-role-of-skill-and-breadth-in)
- [Don't bet the ranch: hit ratios, asymmetry and breadth (Fidante)](https://www.fidante.com/au/insights/dont-bet-ranch-hit-ratios-asymmetry-and-breadth)
- [Dispersion and alpha conversion (Morgan Stanley)](https://www.morganstanley.com/im/publication/insights/articles/dispersion-and-alpha-conversion.pdf)
