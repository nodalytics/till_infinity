# Can what we have built run a fund?

Harness: [`research/harness/fund.py`](../harness/fund.py). Lab run 2026-09-30. Part 2 is general
information, not legal advice.

## The question, and the honest premise

A fund needs a return it can defend. This desk has none of its own:

- [`triage.md`](triage.md): every production strategy grosses about 0, none beats a random pick of
  the same signals, and the live record is -36.1R over 207 trades.
- Every return-predicting idea tested since has failed its controls: [`indicators.md`](indicators.md),
  [`stophunt.md`](stophunt.md), [`confirm.md`](confirm.md), [`chan.md`](chan.md),
  [`calendar-returns.md`](calendar-returns.md) (drift) and [`agents.md`](agents.md).

What *has* survived is **risk forecasting**:

- the shock forecaster (AUC 0.73-0.76 on real markets, [`anomalies.md`](anomalies.md));
- the calibrated envelope ([`conformal.md`](conformal.md), [`gbm-envelope.md`](gbm-envelope.md));
- the volatility clock ([`calendar-returns.md`](calendar-returns.md)).

A fund does not strictly need an edge of its own. It can deliver a known asset class's premium
with better risk control: the **volatility-managed portfolio** (Moreira & Muir 2017, "Volatility-Managed
Portfolios", *J. Finance*; Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert 2018, "The
Impact of Volatility Targeting", *J. Portfolio Management*; and the out-of-sample critique, Cederburg,
O'Doherty, Wang & Yan 2020, *J. Financial Economics*). So the empirical question is narrow:

> Do our forecasts, run through production code, manage a portfolio of fund-investable assets
> better than the standard EWMA recipe?

## Part 1: method

- **Assets:** eight ETFs from 2006-03 to 2026-09: SPY, EFA and EEM (equities), TLT and IEF (bonds),
  GLD (gold), DBC (commodities) and VNQ (property). Adjusted daily OHLC, 5,178 days.
- **Not CFDs, and not Deriv synthetics.** A regulated fund holds investable assets, and a broker's
  synthetic carries a house edge by construction ([`deriv-payouts.md`](deriv-payouts.md)).
- **Forecasts,** each known at day t's close and used for t+1:
  - `ewma`: RiskMetrics λ 0.94, the standard recipe;
  - `tr`: the production `Ranges` EWMA of true range, the desk's measured best near-term forecast;
  - `env`: the production `Envelope`'s 5-day AgACI width, as a daily sd.

  Each is calibrated onto the return scale causally, by an expanding median of |r| / σ, so no
  forecast wins by being biased.
- **Portfolios:**
  - buy and hold (each asset, 60/40 SPY/TLT and equal weight, monthly rebalance);
  - single-asset volatility targeting to 10%;
  - inverse-vol risk parity;
  - hierarchical risk parity (López de Prado 2016). Both parity portfolios are monthly and
    vol-targeted to 10%;
  - a shock overlay that halves the S&P sleeve the day after the production shock forecaster
    reads a lift ≥ 3 at the US close. It runs on the broker's hourly US_SP_500 bars, so 2024-2026
    only.
- **Costs and financing:** 2 bp per unit turnover; cash earns the 3-month T-bill (FRED DTB3);
  leverage above 1 pays the bill plus 0.5%; gross exposure capped at 2x.
- **Pre-registered pass bar:** with our forecasts, a strategy beats the same strategy on `ewma` by
  Sharpe ≥ 0.1, or by max drawdown ≥ 20% relative, in both halves (split 2016-06), with a
  Deflated Sharpe Ratio (Bailey & López de Prado 2014) above 0.95 over the 40 variants tried.
- **Controls:** GARCH(1,1) walks with t(5) shocks, where volatility targeting should help Sharpe
  mechanically, and iid t(5) walks, where it should not. 20 walks of 5,000 days each.

## Part 1: results

**The harness finds the effect where it exists.** On GARCH walks, volatility targeting beats buy and
hold by Sharpe +0.120 (se 0.025) and cuts max drawdown from -39.0% to -26.3%. On iid walks it
doesn't help (-0.027). That is the published result, reproduced mechanically.

**On real assets, our forecasts tie the standard recipe everywhere. 0 of 20 comparisons pass:**

| strategy | Sharpe, ewma | Sharpe, ours (tr / env) | dSharpe, tr / env [95% block bootstrap] | DSR |
|---|---|---|---|---|
| SPY vol target | +0.76 | +0.78 / +0.74 | +0.013 [-0.031, +0.061] / -0.025 [-0.085, +0.044] | 0.952 / 0.933 |
| GLD vol target | +0.68 | +0.67 / +0.69 | -0.010 / +0.011 | 0.876 / 0.894 |
| risk parity | +0.69 | +0.69 / +0.71 | +0.004 [-0.020, +0.034] / +0.019 [-0.013, +0.056] | 0.919 / 0.927 |
| HRP | +0.66 | +0.64 / +0.66 | -0.024 / -0.005 | 0.850 / 0.869 |
| VNQ vol target | +0.50 | +0.42 / +0.41 | **-0.076** / -0.085 | 0.620 / 0.623 |

Every other single-asset difference lies between -0.05 and +0.08, and every confidence interval
spans zero except VNQ's, which is negative. On GARCH walks our forecasts are slightly *worse* than
EWMA (-0.016, se 0.007), the same as on real assets. The true-range and envelope forecasts were
built to rank the next few bars intraday. On a daily close-to-close horizon they add nothing over
EWMA.

**Volatility management does its known job, with or without us.** SPY's max drawdown falls from
-55.2% buy-and-hold to -26.3% vol-targeted, and its 2008 loss from -46.4% to -15.3%. Sharpe rises
from +0.63 to +0.76. That comes from standard EWMA targeting, not from anything this desk built.

| portfolio | Sharpe | ann | vol | max DD | 2008 | 2020 | 2022 |
|---|---|---|---|---|---|---|---|
| 60/40, buy and hold | +0.77 | +8.6% | 11.5% | -29.9% | -25.4% | -0.9% | -22.8% |
| equal weight | +0.58 | +6.7% | 12.6% | -37.0% | -29.8% | -8.2% | -13.4% |
| risk parity (ewma), 10% target | +0.69 | +7.1% | 10.8% | -22.4% | -12.2% | -10.3% | -14.4% |
| HRP (ewma), 10% target | +0.66 | +6.2% | 9.8% | **-19.5%** | +0.7% | -4.6% | -15.3% |

- **Risk parity and HRP** cut max drawdown by a third against 60/40, and nearly avoided 2008.
  2022 still hurt, because bonds and equities fell together.
- **60/40 buy-and-hold** has the best Sharpe (+0.77) of any portfolio. It is also the only one with
  a Deflated Sharpe Ratio above 0.95.
- **Nothing here deflates past 0.95 as an improvement over the standard recipe.**

**The shock overlay made things worse.** It flagged 13.2% of days in 2024-2026, and halving the S&P
on those days took Sharpe from +1.25 to +0.95 and max drawdown from -7.2% to -9.7%. The shock
forecaster predicts large moves in *either* direction, so cutting exposure before them costs as
much upside as it saves downside. It is a risk *measure*, not a timing signal.

## Part 2: what a fund would require

**Structures,** from most to least regulated:

- **A retail collective investment scheme:**
  - **US:** a 1940 Act mutual fund. Derivatives are limited by SEC Rule 18f-4: a derivatives risk
    manager, and a VaR no more than 200% of a reference portfolio's (relative test), or 20% of net
    assets (absolute test).
  - **EU:** a UCITS. Global exposure is limited to 100% of NAV under the commitment approach, or an
    absolute VaR of 20% of NAV; a VaR approach is required for complex strategies.
  - **Nigeria,** *an assumption about your location, from the session's time zone.* A collective
    investment scheme (a unit trust or an open-ended investment company) is registered with the
    SEC under the Investments and Securities Act 2025. The fund manager must be a CAMA-incorporated
    company registered with the SEC as a fund or portfolio manager, and the scheme needs a trustee,
    a custodian and a registrar.

    SEC Circular 26-1 (16 January 2026) raised full-scope fund managers' minimum capital to
    **₦5 billion** (₦2 billion for limited scope, from ₦150 million). Managers with AUM above
    ₦100 billion must hold at least 10% of AUM. Existing operators must comply by 30 June 2027.
- **A private fund** for sophisticated or qualified investors: lighter disclosure and investor
  limits, but still a regulated manager, an administrator, an auditor and a custodian or prime
  broker.
- **A managed account:** you trade clients' accounts under a mandate. It usually needs an adviser or
  portfolio-manager licence, but no pooled vehicle.
- **A signal, research or risk-tooling product:** sells information, not management. It is the
  least regulated, though still subject to investment-advice rules in many places.

**What every route needs that this desk does not have yet:**

- a licensed manager;
- independent custody and a trustee or administrator;
- audited accounts;
- risk disclosures;
- liquidity terms that match the assets;
- above all, **a live, audited track record**, typically 2-3 years before institutional allocators
  look.

**Why today's instruments don't fit a regulated fund:**

- **CFDs** are OTC contracts with the broker as the counterparty. They carry that counterparty's
  credit risk, count at full notional in the commitment and VaR tests, and are generally not
  eligible or practical assets for retail schemes.
- **Deriv's synthetics** aren't assets at all. They are games priced by the house, with a measured
  margin ([`deriv-payouts.md`](deriv-payouts.md)).

A fund would have to hold exchange-traded instruments: ETFs, listed futures or the underlying
securities.

## Part 3: recommendation

**Part 1 fails, so there is no fund strategy to launch on what we have built.**

1. **Our forecasts are not a fund strategy.** Our true-range, envelope and shock forecasts do
   not beat plain EWMA for daily portfolio risk management (0 of 20, all CIs span zero). The shock
   overlay hurt. A standard volatility-managed or risk-parity portfolio of ETFs does the job a fund
   would want, and that requires none of this infrastructure.
2. **The infrastructure is the asset.** What is genuinely built and measured, rather than hoped for:
   - an honest research platform (walk-forward, generated-walk controls, the zero-skill and
     deflation discipline);
   - calibrated intraday risk tooling (the shock forecaster, the envelope, touch rates, the volatility
     clock);
   - a production data, trading and journal stack.

   Realistic uses: an internal risk and research platform, a risk-analytics or signal service
   (intraday shock and range probabilities, which do validate), or a base for proprietary trading
   *once* a strategy earns its keep on it.
3. **If a fund is the goal anyway:**
   - start with a standard, transparent volatility-managed multi-asset ETF portfolio, e.g. HRP or
     risk parity at 10% volatility. Its drawdown and 2008 profile above is attractive, and its logic
     is well published;
   - run it on paper, then with a small amount of proprietary capital, audited, for **12-24 months**;
   - then offer it as a managed account or private fund;
   - move to a regulated scheme only once capital, licensing and track record allow. In Nigeria
     that is ₦2-5 billion of manager capital.

   Be clear with investors that this is a known premium managed for risk, not proprietary alpha.
4. **Gaps to close first:**
   - a live track record of any length on investable instruments, which is zero today;
   - capacity analysis, trivial for liquid ETFs;
   - a licensed entity and service providers;
   - a strategy that beats its benchmark after the deflation the desk now applies to itself.
