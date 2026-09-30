# Causal inference: the spread is a symptom, not a cause

Harness: [`research/harness/causal.py`](../harness/causal.py). Lab run 2026-09-30, logs
`logs/causal_{roll,news,fund,pcmci,report}.log`.

## The question

[`findings.md`](findings.md): the desk forecasts risk, not direction, and the shock forecaster works
(AUC 0.73-0.76). But prediction is not mechanism. A wider spread predicts a bigger bar. Does
withdrawn liquidity *make* price move, or does a moving market make dealers withdraw? Does funding
pressure move crypto? Does crowding cause decay? Only variation in one variable that the other did
not cause can separate them. This study looks for such variation in the calendar and in the broker's
own mechanics.

A cause matters to production and a symptom does not, in one specific way. A cause is a lead you can
act ahead of. A symptom can still predict, but reacting to it is reacting to what already happened.

## Designs and their identifying assumptions

| | Design | Assumption |
|---|---|---|
| D1 | **Scheduled releases.** Liquidity withdrawn *before* a release whose content nobody knows, against the same weekday and time in event-free weeks; the release's surprise \|z\| (surprise.md) as exogenous information | The release time is fixed in advance, and the surprise is as good as random given the consensus |
| D2 | **The 17:00 New York rollover.** The broker widens FX spreads mechanically every weekday ([`rollover.md`](rollover.md)). Does a bigger spike cause more volatility afterwards, measured once the spread has normalised? | Given the pre-rollover hour's volatility, the pair and the weekday, the spike's size is unrelated to how volatile the next hour would have been |
| D3 | **Binance funding settlement** at 00/08/16 UTC, with the rate being paid as treatment intensity | The settlement schedule is fixed; funding at non-settlement hours is the placebo |
| D4 | **Crowding to alpha decay** | Not identifiable with our data: no exogenous crowding shifts (index inclusions, reporting surprises). The density-dependence test is the ecology program's |
| D5 | **PCMCI** (tigramite, ParCorr, τ ≤ 3) over the shock forecaster's inputs at 1h | *Exploration only.* An edge is a hypothesis, checked against D1-D2 and against a walk whose true graph we built |

Controls:
- placebo cutoffs (15:00 New York), placebo outcomes (the hour before the cutoff) and placebo event
  times (matched event-free weeks);
- walks we generate: a mechanical, price-independent daily spike on bid-based bars;
- Deriv as a no-rollover comparison market (a design role, not a null claim);
- both halves, day-clustered standard errors, and BH across all 27 design × outcome tests.

The pass bar for "causal" was set before the run: |t| ≥ 3, the same sign in both halves, placebo
|t| < 2, walk |t| < 2, and BH q < 0.05.

## Results

### D2: an exogenous spread spike does not cause volatility

4,033 FX pair-days, with a median rollover spike 15× the normal spread. The regression is outcome on
log(spike size), with pre-hour volatility, pair and weekday controls.

| Test | Coef | t | Halves |
|---|---|---|---|
| **Rollover spike → volatility after it** (bars +3..+6) | +0.016 | **1.66** | −0.014 / +0.060 |
| Rollover spike → placebo outcome (before the cutoff) | −0.010 | −0.81 | |
| Rollover spike → the spike bar itself | +0.178 | 8.19 | bid-quote mechanics |
| **15:00 New York "spike" (ordinary spread variation) → volatility after it** | +0.086 | **5.08** | +0.072 / +0.138 |
| Deriv at 17:00 New York (no rollover) | +0.054 | 0.59 | |
| Walks: mechanical spike → volatility after it | −0.007 | −0.79 | |

Crypto bars carry a constant spread, so crypto can't be tested this way (not identifiable).

The contrast is the finding. When the spread widens for a reason unrelated to the market (the broker's
rollover), later volatility does not follow: t 1.66, with halves of opposite sign. When the spread
varies for ordinary reasons (15:00), it predicts later volatility strongly (t 5.08). **So the spread's
predictive power comes from a common cause, market activity and conditions, not from the spread
itself.**

### D1: information arrival causes volatility; the surprise's size and pre-release liquidity do not show

1,865 high-importance release times; 3,358 pair-releases at 15m and 668 at 3m.

| Test | Coef | t |
|---|---|---|
| Pre-release spread, event vs matched event-free weeks (15m) | −0.004 (1.018x vs 1.022x) | −0.72 |
| Pre-release \|r\|, event vs control (15m / 3m) | +0.011 / +0.020 | 0.66 / 1.37 |
| \|z\| → spread at the release bar (15m / 3m) | +0.003 / −0.010 | 1.28 / −0.71 |
| \|z\| → \|r\| at the release bar (15m / 3m) | −0.015 / +0.051 | −0.14 / 0.10 |
| \|z\| → \|r\| after the release (15m / 3m) | −0.022 / −0.004 | −1.55 / −0.39 |

- **The release itself causes a volatility spike.** At 3m, around releases with |z| > 1.5, |r| is 2.10
  in the release bar against about 0.55 in the bars around it.
- **The spike's size in these bars doesn't scale with the surprise.** surprise.md found the surprise
  sets the *direction* of the release bar, not its size.
- **The spread hardly moves, 1.07x at the peak.** At 3m, spread and |r| peak together (k = 0). |r| is
  back to half within 1 bar and the spread only by 3, so the spread lags and outlasts volatility.
- **No pre-release liquidity withdrawal is visible in bar spreads,** so D1(a) has no treatment to
  identify with. A limitation: the MT5 bar `spread` is a single figure per bar, not the widest quote
  inside it, so intra-bar widening at news may not be recorded. Tick quotes would be needed.

### D3: funding settlement exerts no directional pressure; funding size is a regime marker

48,189 settlements across 10 coins. Returns are signed by the side that pays.

| Test | Coef | t |
|---|---|---|
| \|funding\| → signed return in the 3h into settlement | −0.008 | −0.25 |
| \|funding\| → signed return in the 3h after settlement | +0.011 | 0.61 |
| \|funding\| → \|r\| after settlement | +0.052 | 4.17 |
| Placebo, 4h off settlement: \|funding\| → \|r\| after | +0.051 | 2.97 |
| Walks carrying the real funding series: signed pre / post | | 0.51 / 1.14 |

The quintile table shows no dose-response in the signed returns either (pre −0.009 to −0.068,
post −0.007 to +0.019). High funding goes with higher volatility **at every hour**, settlement or
not. It is a marker of a hot regime, not a pressure released at settlement.

### D5: causal discovery, as hypotheses

PCMCI at 1h, links into log|r| (MCI, p < 0.001):

| | spread(t−1) → \|r\| | volume(t−1) → \|r\| | volume(t−1) → shock |
|---|---|---|---|
| EURUSD | +0.057 | **+0.184** | +0.057 |
| USDJPY | +0.098 | +0.084 | +0.037 |
| XAUUSD | not significant (p 0.34) | **+0.149** | +0.039 |
| BTCUSD | −0.022 (p 0.008) | +0.122 | +0.072 |
| Volatility 75 | none | none | none |

On the walk with a known graph (GARCH volatility drives both |r| and the next bar's spread, and the
spread causes nothing), PCMCI found no spread → |r| edge and did find the |r| → spread link. So it
doesn't invent the reverse edge where none exists.

- **Discovery's spread → |r| edge on EURUSD and USDJPY is contradicted by D2's identified estimate.**
  It is confounded, the classic reason discovery isn't identification.
- **Volume is the strongest upstream candidate everywhere,** for |r| and for shocks. It isn't
  identified here: volume and volatility share the same unmeasured driver, market activity.
- **Deriv shows no links,** as a generated series with a constant spread should.

### Multiple testing

Of 27 tests, BH leaves four at q < 0.05:
- the spike bar's mechanics;
- the 15:00 correlation;
- funding → |r| at settlement;
- funding → |r| at its placebo hours.

**None meets the pre-registered causal bar.** Each survivor is mechanical, correlational, or fails
its placebo.

## What this means

- **The spread is a symptom of market conditions, not a cause of volatility.** Mechanically widened
  spreads leave later volatility unchanged; naturally varying spreads predict it. The spread is a
  reading of the market, not a lever on it.
- **Keep the spread as a predictor, but don't read it as a warning you can act ahead of.** In the
  shock forecaster and the envelope it's a valid *predictive* input: prediction doesn't need
  causation. What this rules out is using a spread widening as an early warning to get out ahead of
  a volatility burst that it would *cause*: it causes none. The spread gate stays what `vetoes.md`
  found it to be, a cost gate.
- **Information arrival is causal, so the calendar is a real lead.** A scheduled high-importance
  release causes a volatility spike whatever its surprise, and its time is known in advance. That
  is the one variable here the desk can act *ahead* of, and the shock forecaster already uses
  calendar proximity (anomalies.md: gaps AUC 0.92-0.97).
- **Funding is a regime flag, not a trade.** Its link to volatility is not a settlement effect.
- **Volume is the hypothesis to test next.** Test it as an incremental shock-forecaster feature
  (prediction, which needs no identification) before any causal claim. MT5 tick volume is a weak
  proxy (lopez-de-prado.md), so real traded volume is where it would be worth identifying.
- **Crowding → decay isn't identifiable here** without exogenous crowding shifts.

## Production components this touches

- **Shock forecaster:** no change. The spread stays as a predictive input; volume is a candidate
  feature for the next retrain contest.
- **Risk gates:** no change. The spread gate is a cost gate. News timing is the causal lead, and
  vetoes.md already found blackouts don't improve R (the spike is two-sided).
- **Cards:** none.
