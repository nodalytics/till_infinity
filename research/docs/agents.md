# Specialist small-LLM agents: do they know anything their inputs don't?

Harness: [`research/harness/agents.py`](../harness/agents.py). Model: qwen2.5:7b-instruct in the
lab's Ollama container, temperature 0. Run finished 2026-09-30.

## The question

The desk asked for small local models, each a specialist, whose opinions are weighed into one
decision:

- a **chart** agent;
- a **macro** agent;
- a **positioning** agent.

This is the shape ATLAS had ([`atlas.md`](atlas.md)). ATLAS could not show skill, because its test
years were ones the model had read about. Do specialists add anything a plain model on the same
numbers does not?

## Method

- **Signals.** 7 FX pairs (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD). Each trading day
  from 2025-01-02 to 2026-09-10 (528-529 days per pair), each agent answers
  P(the pair closes higher tomorrow) as JSON.
- **No recall.** The whole window is after Qwen2.5's training data, so no outcome can be recalled.
  The chart agent is also anonymised: prices as % from the last close, with no symbol and no date.
- **What each agent sees:**

  | agent | inputs |
  |---|---|
  | chart | the last 30 daily bars, distance from the 20- and 50-day means, RSI(14), distance to the 20-day high and low |
  | macro | the last 7 days of medium- and high-importance releases for both currencies, with the surprise's sign, and tomorrow's scheduled releases |
  | positioning | CFTC speculator and leveraged-fund net positioning in each non-USD currency's future: z-score against 3 years, and the 4-week change |

- **Combiners:**
  - equal weights;
  - hedge, i.e. multiplicative weights on running log loss (causal);
  - a stacked logistic regression fit on the first half.
- **Scoring.** The second half, as AUC, Brier skill against the first half's base rate, and a toy
  trade: long above 0.55, short below 0.45, 1 bp round-trip cost.
- **The decisive control.** A plain logistic regression on the same numbers the agents were shown.
- **A second control.** The chart agent, disguised identically, on four Deriv Volatility indices
  (206 days each). The design treated them as random walks. This desk now treats Deriv as a real
  market, so read that row as one more market the agent was shown.

## Results

11,924 calls; 0.0% unparseable.

**The answers are fixed priors, not forecasts.** Every agent is bullish on almost every day, for
every pair. That holds even though "up" means the dollar is weaker for EURUSD and stronger for
USDCHF, so no coherent view can be bullish on both.

| agent | n | answers > 0.5 | answers < 0.5 | mean | distinct values | most common answer (share) | realised up-share |
|---|---|---|---|---|---|---|---|
| chart | 3,700 | 94.6% | 5.4% | 0.607 | 19 | 0.65 (42%) | 51.5% |
| macro | 3,700 | 86.0% | 14.0% | 0.574 | 7 | 0.60 (**81%**) | 51.5% |
| positioning | 3,700 | 98.3% | 1.7% | 0.581 | 7 | 0.60 (51%) | 51.5% |
| chart on Deriv Volatility | 824 | 88.3% | 11.7% | 0.578 | 11 | 0.58 (38%) | 47.7% |

**Second half, out of sample** (n = 1,852 pair-days):

| | AUC | Brier skill | toy trade: days traded, net per day |
|---|---|---|---|
| agent chart | 0.481 | -0.0846 | 95%, -1.4 bp |
| agent macro | 0.503 | -0.0236 | 92%, -0.5 bp |
| agent positioning | 0.497 | -0.0158 | 59%, +0.1 bp |
| equal weights | 0.484 | -0.0260 | 85%, -0.8 bp |
| hedge weights | 0.488 | -0.0152 | 92%, -0.6 bp |
| stacked (fit on the first half) | 0.517 | +0.0004 | 0% (it learned to say 0.5) |
| **no-LLM logistic on the same inputs** | **0.515** | -0.0155 | 53%, -0.8 bp |
| chart agent on Deriv Volatility | 0.454 | | |

## What this means

- **No agent has skill.** Their AUCs (0.481-0.503) sit around a coin, and every Brier skill is
  negative: each agent is worse than quoting the base rate. The best combiner, the stacker, reaches
  0.517 only by learning to answer 0.5 every day, which is why it trades on none of them.
- **The agents behave like fixed priors, not readers.**
  - Macro answers exactly 0.60 on 81% of days.
  - Positioning is above 0.5 on 98% of days.
  - Chart is above 0.5 on 95%, and uses only 19 distinct values across 3,700 very different charts.

  A bullish lean on every pair at once is a habit of the model, not a view of the market.
- **The language model adds nothing to its inputs.** A plain logistic regression on the same numbers
  scores the same (0.515) and takes seconds instead of 20 hours. Whatever small structure there is,
  it lives in the numbers, not in the reading of them.
- **Weighting cannot rescue it.** Weighing experts (equal, hedge, stacked) helps only when some expert
  knows something. Here the weights can only choose between priors.

## For production

- **No specialist-agent layer.** Keep `AGENTS_ENABLED` off for decisions.
- If agents are used at all, it should be for summarising and explaining a card, where being wrong
  costs nothing, not for probabilities. [`agent-trading.md`](agent-trading.md) tests the other form
  of the request: agents that decide trades on structures signals.
