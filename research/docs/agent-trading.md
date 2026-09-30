# Agents that trade structures signals: does a small LLM, shown the card, choose better than chance?

Harness: [`research/harness/agenttrade.py`](../harness/agenttrade.py). Model: qwen2.5:7b-instruct
in the lab's Ollama container, temperature 0, JSON output. Run finished 2026-09-30.

## The question

The desk's request was: "test agents for trading: agents do the trading based on the signals, not
deterministic rules". [`agents.md`](agents.md) found that specialist agents forecasting tomorrow's
close have no skill. This tests the other form: an agent that sees each structures signal the way a
trader would, on its card, and decides whether to take the trade, which way to trade it, how
confident it is, and how big to go.

## Method

- **Signals.** Every zone touch the production `Engine` opens, replayed over the lab's 15m and 1h
  bars from 2025-09-01. The replay covers real markets (FX, metals, crypto), Deriv's indices as a
  market of their own, and walks we generate.
- **The card.** At each touch the harness reads off the engine what production would put on the
  card:
  - the level, the side it was touched from, and its hold rate, symmetric hold rate and touch count;
  - the engine's P(up) and edge;
  - the next-5-bar envelope (P10 / P50 / P90, as % from price);
  - the shock probability and its lift;
  - the ZMA z-score and whether it is stretched;
  - the hour's volatility multiple;
  - the last 20 closes as % from the last close;
  - the family. Walks are shown as an unnamed index.
- **The answer.** The agent returns take or skip, fade or break, a confidence from 0 to 1, and a
  size tier.
- **Prompts and anonymity.** Two prompts, a neutral "trader" and a "risk-first" trader, each get half
  the signals. Half of each half is anonymised: no instrument and no date.
- **Settlement.** Every signal is settled both ways at the touch's close, with the stop anchored one
  bar-volatility beyond the level (`stophunt.py`'s geometry). Targets are 1R and 2R, with a 40-bar
  limit and costs in R. So taken trades, skipped trades and every null share one ledger.
- **Sample and answers.** 2,353 cards, stratified by family and interval: the strata held fewer cards
  than the 3,000 asked for. Every card was answered in valid JSON.

**Pre-registered pass:** taken trades beat random selection at the same take rate, with the agent's
own fade/break mix, by at least 0.05R gross at 1R, with t ≥ 3 (days resampled). This must hold in
both halves of time and must not show on the walks.

## Results

**The agents barely choose.**

| prompt | family | cards | take rate | break share | anonymous vs named take rate |
|---|---|---|---|---|---|
| trader | real | 716 | **100.0%** | 1.0% | 100% / 100% |
| trader | Deriv | 289 | 100.0% | 0.3% | 100% / 100% |
| trader | walks | 172 | 100.0% | 0.6% | 100% / 100% |
| risk-first | real | 718 | 83.8% | 0.0% | 85.9% / 81.7% |
| risk-first | Deriv | 311 | 84.6% | 0.0% | 90.9% / 78.3% |
| risk-first | walks | 147 | 89.1% | 0.0% | 90.8% / 87.8% |

- The neutral trader takes every signal and fades almost all of them, which is exactly the
  deterministic "fade everything" rule.
- The risk-first trader skips about one in six, never trades a break, and puts 70-75% of its trades
  in the "small" size tier.
- Its confidence takes only 13-24 distinct values, between about 0.55 and 0.81.

**Against random selection at the same rate and mix** (1R, in R per trade):

| prompt | family | taken, gross | random, gross | agent − random (t) | halves | taken, net | skipped, gross |
|---|---|---|---|---|---|---|---|
| trader | real | −0.079 | −0.086 | +0.007 (+0.2) | +0.006 / +0.007 | −0.364 | — |
| trader | Deriv | −0.093 | −0.087 | −0.007 (−0.1) | −0.013 / −0.001 | −0.170 | — |
| trader | walks | −0.174 | −0.186 | +0.011 (+0.1) | +0.021 / +0.000 | −0.273 | — |
| risk-first | real | −0.044 | −0.079 | **+0.035 (+0.8)** | +0.012 / +0.055 | −0.319 | −0.259 |
| risk-first | Deriv | −0.087 | −0.087 | −0.001 (−0.0) | −0.040 / +0.037 | −0.163 | −0.083 |
| risk-first | walks | −0.130 | −0.129 | −0.001 (−0.0) | −0.004 / +0.012 | −0.219 | −0.125 |

The 2R results are the same shape: every agent − random difference is within ±0.035R, with |t| at
or below 0.6.

**Confidence does not sort outcomes.** Win rate at 1R by confidence quartile, lowest to highest:

| prompt | family | lowest | 2nd | 3rd | highest |
|---|---|---|---|---|---|
| trader | real | 46% | 49% | 44% | 46% |
| risk-first | real | 48% | 55% | 45% | 44% |

The other families look the same. The size tiers don't sort outcomes consistently either: for the
risk-first prompt on real markets, "small" read −0.014R and "normal" −0.113R, but the reverse held on
the walks.

## What this means

- **The agent is a fade rule with a thin skip.** Shown the full card, the neutral prompt fades every
  signal, the deterministic baseline. The risk-first prompt drops about one in six. None of this
  tests an LLM's judgement, because it barely exercises one.
- **Its skips are the only candidate for skill, and they fall short of the bar.** On real markets the
  risk-first agent's taken trades beat random selection by +0.035R gross (t 0.8), positive in both
  halves (+0.012, +0.055). The trades it skipped did much worse (−0.259R gross). The direction is
  right, but it is a quarter of the way to t ≥ 3, and the same prompt reads zero on Deriv and on the
  walks. Recall doesn't drive it: anonymised cards were taken at about the same rate.
- **Every choice still loses after costs:** −0.16 to −0.36R net per trade, the same arithmetic as
  [`triage.md`](triage.md). A selector that is at best slightly better than random cannot pay a
  spread that large.
- **Confidence and size carry no information,** so they couldn't be used for sizing even if taking
  worked.

## Recommendation

- **No LLM agent decides trades.** It passes no bar, and its one faint signal, the risk-first skip on
  real markets, is too weak to act on.
- If the skip idea is kept alive, run it the way the confirmation gates are run: shadowed, recording
  the agent's take or skip on live signals and settled later against random. It would need about
  four times this sample's real-market size to reach t ≥ 3, if the +0.035R were real.
- Agents remain useful, at most, for explaining a card in words, where being wrong costs nothing.
