# Reading Medallion honestly: the lesson is the cost structure, not the strategy

**Written 2026-10-09**, prompted by the observation that Medallion's described
approach - "when it spots two related assets temporarily out of sync, it bets
they will snap back" - is the multi-peer deviation idea in
[`pca-residuals.md`](pca-residuals.md) and **I11**. It is. That is the least
useful thing about it.

## What is actually documented, and what is folklore

Renaissance has never published. Everything circulating about *how* Medallion
trades is inference, mostly downstream of Gregory Zuckerman's 2019 book, and
should be read as journalism rather than method.

What is documented, via Bradford Cornell's
[*Medallion Fund: The Ultimate Counterexample?*](https://www.institutionalinvestor.com/article/2bswymr8cih3jeaslxc00/portfolio/famed-medallion-fund-stretches-explanation-to-the-limit-professor-claims)
(2019), whose figures also come from Zuckerman:

| | |
| --- | --- |
| 1988-2018 average | **66.1% gross, 39.2% net** |
| $100 invested, gross | grows to about $398.7m |
| a perfect monthly stocks/T-bills timer, same period | $331,288 |
| Cornell's conclusion | no adequate rational-market explanation has been offered |

The gap between the fund and perfect monthly market timing is three orders of
magnitude, which is the real content of the number: it is not a better version
of a familiar thing.

## The fact that actually transfers, and it is discouraging

Cornell's same analysis covers Renaissance's **public** funds, REIF and RIDA.
They trail Medallion by **17 to 19 percentage points a year** and he calls them
"relatively mundane and in no way comparable".

Same firm. Same researchers. Same intellectual apparatus. Published funds,
uncapped, at institutional scale - and the result is unremarkable.

**So whatever Medallion has is not a transferable method.** If it were, it
would have transferred eighty feet down the corridor. What distinguishes the
fund is capacity-constrained and cost-sensitive: it is capped at roughly
$10-15bn precisely because its own trading moves the anomalies it feeds on.

That is the opposite of the usual reading, and it is the one worth carrying.

## Reasoning from Medallion is selecting on the dependent variable

It is the most studied fund in history *because* it is the extreme outlier of
a distribution containing thousands of quantitative funds, most of which
closed. Inferring "statistical arbitrage works" from it is the same error as
inferring a strategy is good from its best backtest - a mistake this repository
has a standing control for, and should not make in prose because the subject is
famous.

## We have already run the Medallion-shaped experiment, and we have the number

The idea - related assets out of sync, bet on the snap back - was executed here
properly: frozen rule, discovery and confirmation split, 131 coins never seen
in discovery, an OU control and two nulls.

| | |
| --- | ---: |
| **gross Sharpe** | **+0.27** |
| fees | 20.2% a year |
| funding | 4.3% a year |
| gross return | +5.3% a year |
| **net Sharpe** | **-0.97** [-1.59, -0.30] |

**The edge was there. The costs ate it, four times over.** That is not a
different outcome from Medallion's model - it is the same model with the
constraint binding the other way. A tiny edge compounds *only* when cost per
trade is smaller than edge per trade, and the Medallion reading that matters is
that they solved the cost side: scale, financing, and in effect being paid to
provide liquidity rather than paying to take it.

## The same constraint, three more times, from this desk's own record

It is not only the stat-arb book. The identical arithmetic decided every P&L
question measured here this week:

* **Timeframe.** 1m levels return -0.224R a trade and 5m returns +0.048R
  ([`losing-faster.md`](losing-faster.md)). The signal is not worse at 1m - the
  *same fixed cost* sits against a smaller stop.
* **Stops.** Realised stops fill at -1.082R rather than -1.000, every day for
  nine days. 5.43R of a 13.21R loss was slippage alone.
* **Win rate is not the question.** `level-scalp` wins **56% of its trades and
  still loses money**, because the average loss is 1.8x the average win.
  Medallion's quoted 50.75% is only a profitable number attached to their cost
  structure, and quoting it without that is quoting half an equation.

## What this means for I11

It does **not** mean the multi-peer deviation idea is dead. It means the
question to ask of it first is not "does the deviation revert" - the OU control
already says the machinery would find it - but **"is there a version of this
where our cost per trade is below the edge per trade".**

For a hedged crypto book the answer measured here is no, by a factor of four.
The two things that change that arithmetic are the ones I11 already names:
a different family with no funding leg, and **using the deviation as a reading
rather than a trade**, where the cost is zero because nothing is hedged.

The second is the only version of this idea that Medallion's own economics
suggest is available to a desk of this size.

## The method, where it is actually written down

Medallion is not a reference - nothing is published. The method is, and in one
place: Daniel Palomar, *Portfolio Optimization: Theory and Application*
(Cambridge University Press, 2025), whose
**[Chapter 15, Pairs Trading Portfolios](https://bookdown.org/palomar/portfoliooptimizationbook/15-pairs-trading.html)**
builds the strategy on a **Kalman filter**, from screening candidate pairs
through cointegration tests and threshold choice to execution.

That is I11's formulation arriving from the other direction, and it is worth
saying plainly that the state-space framing of peer deviation is the textbook
treatment rather than an invention here. Part I of the same book covers the
data modelling underneath it - time series and factor models - which is the
panel layer.

Two things to take from it beyond the method:

* **It is explicit that the strategy is market-neutral by construction**,
  targeting the mispricing between two legs rather than direction. That is the
  same separation the thesis makes between a valuation and a trade.
* **The Kalman formulation exists precisely because the hedge ratio moves.** A
  static regression beta is the thing it replaces - which is I11's "loadings
  can drift" with a published treatment behind it.

The free online draft is personal-use only and not redistributable, so it is
linked rather than quoted.

## Sources

* Bradford Cornell, *Medallion Fund: The Ultimate Counterexample?* (2019), as
  reported by [Institutional Investor](https://www.institutionalinvestor.com/article/2bswymr8cih3jeaslxc00/portfolio/famed-medallion-fund-stretches-explanation-to-the-limit-professor-claims)
* [The Famed Medallion Fund Is Crushing It, Other RenTech Funds Not So Much](https://www.institutionalinvestor.com/article/b1l98yt4p0bvr4/The-Famed-Medallion-Fund-Is-Crushing-It-Other-RenTech-Funds-Not-So-Much)
* Daniel P. Palomar, *Portfolio Optimization: Theory and Application*,
  Cambridge University Press, 2025 -
  [book site](https://portfoliooptimizationbook.com/book/),
  [online draft](https://bookdown.org/palomar/portfoliooptimizationbook/),
  [Ch. 15 Pairs Trading](https://bookdown.org/palomar/portfoliooptimizationbook/15-pairs-trading.html)

Medallion figures originate with Gregory Zuckerman, *The Man Who Solved the
Market* (2019); Renaissance has published nothing, and no number here about
that fund is primary.
