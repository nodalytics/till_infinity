# Findings: what this research program has established

A synthesis of every study in [`README.md`](README.md), as of 2026-09-30 (updated after the last study merged). Each claim links to the doc
that measured it. Read this first. The individual docs carry the numbers, methods and caveats.

## The one-paragraph answer

**This desk can forecast risk. It cannot, so far, forecast direction.** Everything that survived our
controls predicts *how much* price will move: shocks, volatility, band touches, the calendar's
volatility clock. It survived deflation for the number of trials too
([`lopez-de-prado.md`](lopez-de-prado.md)). Nothing that predicts *which way* has survived.

Across all the entry styles, confirmations, strategies and borrowed methods tested:
- no production strategy beats a random pick of its own signals ([`triage.md`](triage.md));
- the live record is −36.1R over 207 trades.

The infrastructure and the risk tooling are real assets. A return-generating strategy is not yet one
of them.

## How we test, and why it matters

Every result here passed or failed the same discipline. Most of the "discoveries" it killed would
have shipped without it.

- **Walk-forward by time,** with both halves reported, and thresholds pre-registered before the run.
- **Controls we generate ourselves:** iid Student-t walks, and GARCH walks where clustering matters.
  **Deriv synthetics are a real market, never a control** (a rule set on 2026-09-29): what we score is
  the feed as served, not the generator Deriv publishes.
- **Costs** are charged at every step, in the production volatility unit.
- **Multiple testing** is controlled with Benjamini-Hochberg within a study, and by deflation across
  the program ([`lopez-de-prado.md`](lopez-de-prado.md)). About 405 effective trials put the
  expected best null t near 3.0, so a single "t = 3.5" is not evidence.
- **The walk comparison caught harness biases more than once:**
  - a triggering path leaking into the "selection" and "timing" split (t 12-25 on memoryless walks,
    [`indicators.md`](indicators.md));
  - future-conditioned trade selection ([`bandrace.md`](bandrace.md));
  - resting limits walked at their level price ([`triage.md`](triage.md));
  - an hour-late confirmation window ([`confirm.md`](confirm.md)).

## What works: risk forecasting

| Finding | Evidence | In production |
|---|---|---|
| Shocks are visible before they happen, on real markets | AUC 0.73-0.76 held out; Deriv and walks about 0.5 ([`anomalies.md`](anomalies.md)). Bar range and tick volume add +0.014 more (year-long hold-out, both halves, every real family; walks' volume adds nothing) ([`shockvolume.md`](shockvolume.md)) | Frozen boosted model, retrained fortnightly, on the cards |
| Adaptive conformal percentiles hold their coverage | AgACI keeps P90 at 89.1-89.6% at 50 bars where one-step ACI slips to about 88% ([`conformal.md`](conformal.md)) | The envelope's corrector, taught from stored history |
| A boosted quantile envelope beats the history one on FX | Pinball −3.8/−4.2/−5.9% (5/20/50 bars), regime-flat coverage; most of the gain corrects a noisy volatility unit ([`gbm-envelope.md`](gbm-envelope.md)) | FX 15m, retrained fortnightly |
| Deriv's Volatility, Jump and Step follow their published laws | Realise 0.99-1.01 of the named sigma; the law beats the empirical envelope ([`deriv-variants.md`](deriv-variants.md)) | Envelope quoted from the law |
| Volatility has a weekday × hour clock | FX out-of-sample profile corr +0.96; cuts next-hour error 5-6% ([`calendar-returns.md`](calendar-returns.md)) | Vol clock (FX, crypto) and a card line |
| Whether a band is touched is forecastable; which band comes first is not | FX touch skill +0.056 to +0.087 over geometry ([`bandrace.md`](bandrace.md)) | Superseded by the boosted bands: a stated 20% touch rate |

## What does not work: direction

| Idea | Verdict | Doc |
|---|---|---|
| Lagging indicators (RSI, stochastics, Bollinger, MAs, MACD, Fibonacci) as entry timing | 0 of ~170 cells; waiting for a reclaim *costs* 0.07-0.13 vol on FX 15m | [`indicators.md`](indicators.md) |
| Entries that avoid "stopped, then it went our way" | Real (about 40% of stops) and identical on walks: stop geometry, not stop-hunting | [`stophunt.md`](stophunt.md) |
| A TA confirmation layer (45 gates, 9 timeframe pairs) | 17 of 8,366 cells, and 4 of the 5 survivors fail deflation | [`confirm.md`](confirm.md), [`lopez-de-prado.md`](lopez-de-prado.md) |
| Meta-labeling under purged CPCV | AUC 0.541 on markets and 0.541 on walks | [`lopez-de-prado.md`](lopez-de-prado.md) |
| Wider stops at constant risk | A smaller trade, nothing more | [`widestop.md`](widestop.md) |
| Limit or pullback entries | The winner's curse is exactly the size of the better price | [`limitfills.md`](limitfills.md) |
| Weekend gaps | Big gaps are predictable (AUC 0.60) but two-sided; the Friday reversal is real (+2 bps) and the Sunday spread eats it | [`fridayflag.md`](fridayflag.md), [`gaptrade.md`](gaptrade.md) |
| FX time of day, carry, safe havens | Ranaldo fails; the broker keeps the carry; havens move with the shock, not after it | [`fxtod.md`](fxtod.md), [`carry.md`](carry.md) |
| Calendar drift | None beyond the rollover's quote artefact | [`calendar-returns.md`](calendar-returns.md) |
| Chan: stationarity filter, FX cointegration, time-series momentum | All null; the EURGBP triangle is quote arbitrage that nets −18.5 Sharpe | [`chan.md`](chan.md) |
| Game-theoretic edges (focal points, crowding, stop-runs) | Real traces, already priced | [`game-theory.md`](game-theory.md) |
| LLM specialist agents forecasting direction | AUC 0.48-0.50; they behave like fixed priors | [`agents.md`](agents.md) |
| An LLM deciding trades from the card | A fade rule with a thin skip; +0.035R over random at best (t 0.8) | [`agent-trading.md`](agent-trading.md) |
| VPIN (order-flow toxicity) | Null on real Binance taker flow and on tick volume: it adds nothing plain volume does not | [`vpin.md`](vpin.md), [`lopez-de-prado.md`](lopez-de-prado.md) |
| The production strategies themselves | Gross −0.10 to +0.03R, none beats random selection | [`triage.md`](triage.md) |

## Could we build a mutual fund from this?

Not as an active trading fund. And our risk forecasts do not make a better volatility-managed fund
than the standard recipe ([`fund.md`](fund.md)).

**The empirical test:** 8 ETFs (stocks, bonds, gold, commodities, real estate), 2006-2026.

- **Our forecasts add nothing here.** Volatility targeting, risk parity and HRP driven by our
  volatility and envelope forecasts tie the textbook EWMA version in all 20 comparisons. Our tools are
  built for intraday bars and do not carry over to daily portfolio risk.
- **The shock overlay made it worse** (Sharpe 1.25 -> 0.95). Shocks go both ways, so de-risking on
  them cuts exposure to good moves too.
- **Standard volatility management does work:**
  - SPY's worst drawdown falls from -55% to -26%, and 2008 from -46% to -15%;
  - HRP at 10% volatility draws down -19.5% against 60/40's -29.9%, and was roughly flat through
    2008.

  But 60/40 still has the best Sharpe (+0.77 against HRP's +0.66). The benefit is smaller drawdowns,
  not better risk-adjusted returns.

**What a fund would need** (sourced in [`fund.md`](fund.md), not legal advice; Nigeria is assumed
from the desk's time zone):

- investable assets on an exchange. CFDs and Deriv synthetics do not qualify;
- a licensed fund manager: Nigeria SEC Circular 26-1 (January 2026) requires N5bn of capital
  full-scope, or N2bn limited-scope, by June 2027;
- a custodian, trustee and auditor;
- typically 2-3 years of audited track record.

**The honest recommendation:**

- **The infrastructure is the asset,** as a research and risk platform or a risk-signal service.
- **If a fund is the goal:** run a transparent HRP or risk-parity ETF portfolio on paper, then with
  small proprietary capital, for 12-24 months with an audited record. Only then look at a private or
  regulated vehicle.

## What we found wrong, and fixed

- **The FX rollover spread spike was teaching the levels** ([`rollover.md`](rollover.md)).
  - 14.7% of FX outcomes resolved at 21:00 UTC, and 41-46% of FX 15m/30m outcomes fell in two hours.
  - Now masked: New York-anchored, with the wick trimmed and old records discounted.
  - FX entries are vetoed in the close-and-rollover hours and at the Sunday open
    ([`vetoes.md`](vetoes.md)).
- **"Earned it" gates acted on noise** ([`zeroskill.md`](zeroskill.md), [`zma-conformal.md`](zma-conformal.md)).
  - **ZMA gate:** a coin passed on one feed in five. It now uses an anytime-valid e-process, with 0-2%
    false passes under continuous checking.
  - **Policy:** it left its default in 100% of contexts on noise. It now needs a significant margin
    over a scored default.
  - **Cycles:** it scored +0.29 on walks. It is now judged against the walk baseline.
- **Configuration that disagreed with itself** ([`../../docs/environment.md`](../../docs/environment.md)).
  - Production dropped the fast bands' size brake. Fixed.
  - `TRADING_STRATEGIES` still resolves differently in the dataclass and `from_env`. Documented, and
    pending the strategy decision.
- **Research bugs:**
  - a late-binding generator that labelled every bar with the last series;
  - crypto spreads read 1,000× too wide in the research layer. Production was unaffected.

## Open decisions and follow-ups

1. **Strategies** ([`triage.md`](triage.md)): whether to stop live trading on the 9 strategies with no
   edge, and judge the `cycle-*` strategies on a fresh journal. Left as is for now, by decision.
2. **Mondrian envelope:** built and off by default. Switching it on is one setting once memory
   headroom is confirmed ([`../../docs/deployment.md`](../../docs/deployment.md)).
3. **Shadowed confirmation gates:** recording live. Judge each at about 200 signals with
   `shadowreport.py`. Expect four of the five to be noise ([`lopez-de-prado.md`](lopez-de-prado.md)).
4. **Rollover re-check:** re-run `rollover.py` on a fresh journal a week or two after the mask
   deployed. The 21:00 share should fall from 14.7% to about 3-4%.
5. **Retraining workflow:** needs the `TRADING_MT5_API_KEY` secret and the `MODELS_SYMBOLS` variable.
6. **Stop-side gate** ([`verification.md`](verification.md)): no gate refuses a stop on the wrong
   side of the entry; it holds today only because every stop comes from `stop_for`. A one-line gate
   would make it a guarantee. Not yet decided.
7. **Deriv pivot shadow gate:** pivot signals publish (about 262 actionable a day), so this gate
   should reach 200 trades in about 8 days, the first of the five.

## The cross-disciplinary programs

Every program on the [agenda](agenda.md) has now run. Each borrowed lens (topology, grammar,
information flow, ecology, causal inference, rituals, Chan, López de Prado, VPIN, stocks, LLM
agents) either rediscovered volatility clustering, which the shock forecaster already reads, or
found nothing. One did better: three independent studies ([`vpin.md`](vpin.md),
[`causal.md`](causal.md), [`infoflow.md`](infoflow.md)) converged on **volume** as information the
desk lacked. It is now in the shock forecaster ([`shockvolume.md`](shockvolume.md)). New
*information*, not a new transform of the same bars, is what moved the needle.

## What this means for the desk

- **Keep building on risk.** The forecasts that work support position sizing, stop placement,
  exposure limits and honest cards. That is also the only defensible basis for managing outside
  money: a volatility-managed portfolio, not a return-forecasting one. Even there, our forecasts tie
  the textbook EWMA recipe on daily ETFs ([`fund.md`](fund.md)).
- **Stop searching the same space.** Indicators, confirmations, entry timing and borrowed textbook
  strategies on these markets, bars and costs have been tested broadly and deflated. A new
  directional idea needs either new information (data the market does not already price) or
  cheaper execution. It should be registered, counted as a trial and deflated like the rest.
- **Trade less until something earns it.** Every strategy's loss is its spread. Fewer trades lose less.
  A strategy should go live only with a deflated, both-halves, beats-random record.
