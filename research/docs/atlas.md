# ATLAS's self-improving agents, run on agents with no skill - and what is worth taking from it

Read 2026-09-29: [github.com/chrisworsey55/atlas-gic](https://github.com/chrisworsey55/atlas-gic)
at `cf4349f`. The repository is an architecture write-up with result files, not a working system:
its agent prompts, weights and scorecards are withheld. The null was measured on the lab with
[`atlasnull.py`](../harness/atlasnull.py).

## What it claims

- **The agents.** 25 LLM agents (Claude Sonnet) in four layers: macro, sector desks,
  "superinvestor" personas, and a decision layer with a CRO and a CIO. They make daily
  stock/ETF calls.
- **The autoresearch loop.** Every 5 trading days, the agent with the lowest rolling Sharpe gets
  one prompt change. The change is kept (git commit) if the agent's Sharpe rises and reverted if
  not. 16 of 54 changes were kept, for example "Financials: Sharpe improved from -4.14 to 0.45".
- **Darwinian weights.** Every day the top quartile's weight is multiplied by 1.05 and the bottom
  quartile's by 0.95, bounded to [0.3, 2.5]. The system is said to have "independently discovered
  its own portfolio manager (CIO) was its weakest component".
- **Other features:**
  - regime cohorts (PRISM);
  - a meta-layer (JANUS) that treats short-window models beating long-window ones as a "novel
    regime";
  - a "reflexivity engine" (maximum consensus = maximum fragility);
  - agents that spawn more agents.
- **Results:** "+22% in 173 days" in the deployment phase.

## What its own files say

- **`results/summary.json`:** from 2024-09-01 to 2026-03-07, the total return is **-5.91%**
  ($1,000,000 to $940,938).
- **`results/portfolio_trajectory.csv`** starts on day 1 at **-33.9%**, so the "+22%" is measured
  from a trough and not from the start.
- **The PRISM regime cohorts** returned +7.7%, -13.1%, -30.2%, -29.0% and +14.3%.
- **Look-ahead:** every backtest ran an LLM over 2016-2026. The model's training data contains
  those years' outcomes, so an LLM backtest over a period the model has read about cannot be told
  apart from look-ahead. Only a forward test says anything about skill.

## Both selection mechanisms, on zero-skill agents

25 agents make one conviction-weighted recommendation a day, and its return is pure noise. The
loop and the weights run as described: 60-day rolling Sharpe, 378 days, 2,000 runs. A
"modification" changes nothing.

| | on noise | ATLAS reported |
| --- | --- | --- |
| do-nothing change to the worst agent kept ("Sharpe improved") | **66%** (57-75% across runs) | 30% (16 of 54) |
| agents ending at the 2.5 ceiling | **6** (4-9) | 7 |
| agents ending at the 0.3 floor | **7** (5-9) | 4 |

- **Picking the worst agent guarantees an "improvement".** It was picked for being unlucky, and
  its next window regresses toward the mean. On noise, two thirds of do-nothing edits "improve"
  it, and a before/after comparison against the next five days alone shows gains of +0.6 Sharpe
  when kept. "-4.14 to 0.45" is the shape of that effect.
- **ATLAS kept fewer changes than doing nothing would have.** That is 30% against 66% on this
  reading. The windows it compared are not published, so this is the direction and not a verdict.
  What the loop cannot do is show that any change helped.
- **The final weights are what noise produces.** Multiplicative ±5% steps bounded at 0.3 and 2.5
  push about a quarter of any set of equal agents to each bound in 378 days. The CIO at the floor
  is one of the four agents noise put there.

## Ideas worth taking from it, for this desk

1. **Crowding and reversal ("maximum consensus = maximum fragility").**
   - This is the one genuinely new *non-price* directional hypothesis in the repository. Every
     price-based and flow-based direction test here has been null ([`orderflow.md`](orderflow.md),
     [`state-and-memory.md`](state-and-memory.md)).
   - It is testable with free positioning data: Binance funding rates, open interest and the
     top-trader long/short ratio (data.binance.vision, the same archive as `orderflow.py`), and
     CFTC COT for FX (`news/cot.py` already reads it).
   - Hypothesis: extreme one-sided positioning precedes a move against it. Score it on direction
     AUC and a traded return against the shifted null. **The best candidate.**
2. **Weight experts on a proper score, and put every selection loop through a null first.**
   - Rolling Sharpe with quartile rules is a noisy score with a bounded random walk on top.
   - The principled version is multiplicative weights (Hedge) on log loss or Brier. It is what the
     `structures` skill harness ([`skill.py`](../harness/skill.py)) is measuring the inputs for.
   - The same null belongs on this desk's own weightings: `council` and the signal registry's
     "worth now". Run them on zero-skill inputs and see whether their weights separate beyond
     what noise does.
3. **Forward-test an LLM macro caller, never backtest one.**
   - Daily pre-registered probability calls on the FX majors, scored by Brier against the base
     rate for a quarter.
   - It is cheap, and it is the only design that is immune to the model having read the outcome.
4. **"No flip-flopping in Fed weeks" (a 15-day minimum between reversals).** It is a claim about
   whipsaw around policy events. It can be checked against this book's reversals around releases,
   next to [`surprise.md`](surprise.md) and `release_in_hold`.
5. **JANUS (a short window beating a long one = a novel regime).** It is a change-point detector
   by another name. For direction there is nothing to detect ([`manifold.md`](manifold.md)). For
   volatility, memory does not decay ([`state-and-memory.md`](state-and-memory.md)), so a
   short-window win should be rare, and it is not worth building ahead of 1 and 2.

The rest is not testable, or not relevant to an FX/metals/crypto CFD book: agent spawning,
MiroFish swarm futures, superinvestor personas and sector desks. Its "convergent meta-rules"
(cap conviction, a VIX regime filter, hard position limits) are risk rules. This desk already has
position and loss limits and spread gates, and VIX has been measured as a volatility input
([`implied.md`](implied.md)).
