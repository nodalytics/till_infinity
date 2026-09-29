"""ATLAS's self-improvement loop and Darwinian weights, run on agents with no skill at all.

github.com/chrisworsey55/atlas-gic describes LLM trading agents that "improve their own prompts":
every 5 trading days the agent with the lowest rolling Sharpe gets one prompt change, which is kept
if its Sharpe then rises and reverted if not; and every day agents in the top quartile have their
weight x1.05 and the bottom quartile x0.95, bounded to [0.3, 2.5]. Reported: 16 of 54 changes kept
(30%), e.g. "Financials: Sharpe improved from -4.14 to 0.45", and final weights with seven agents at
the 2.5 ceiling and four at the 0.3 floor.

Both mechanisms are selection on noisy scores, so the question is what they report when nothing is
learned. Here 25 agents make one recommendation a day whose return is pure noise, a "modification"
changes nothing, and the loop and the weights run exactly as described (60-day rolling Sharpe,
conviction-weighted, 378 days). Repeated 2,000 times.

Two ways of reading "Sharpe improved", since the write-up does not say which windows it compares:
  rolling   the 60-day rolling Sharpe before the change against the 60-day rolling Sharpe 5 days later
  fresh     the 60-day Sharpe before against the 5 days after, on their own
"""
from __future__ import annotations

import numpy as np

RNG = np.random.default_rng(3)
AGENTS, DAYS, LOOK, EVERY, RUNS = 25, 378, 60, 5, 2000


def sharpe(x):
    s = x.std()
    return x.mean() / s if s > 0 else 0.0


def run():
    r = RNG.standard_normal((DAYS, AGENTS)) * (RNG.integers(1, 101, (DAYS, AGENTS)) / 100)
    kept = {"rolling": [0, 0], "fresh": [0, 0]}
    gains = {"rolling": [], "fresh": []}
    pre_worst = []
    for t in range(LOOK, DAYS - EVERY, EVERY):
        s = np.array([sharpe(r[t - LOOK:t, a]) for a in range(AGENTS)])
        worst = int(np.argmin(s))
        pre = s[worst]
        pre_worst.append(pre)
        post = {"rolling": sharpe(r[t + EVERY - LOOK:t + EVERY, worst]), "fresh": sharpe(r[t:t + EVERY, worst])}
        for k, v in post.items():
            kept[k][0] += v > pre
            kept[k][1] += 1
            gains[k].append(v - pre)
    # Darwinian weights: daily, by rolling Sharpe quartile
    w = np.ones(AGENTS)
    for t in range(LOOK, DAYS):
        s = np.array([sharpe(r[t - LOOK:t, a]) for a in range(AGENTS)])
        q1, q3 = np.quantile(s, [0.25, 0.75])
        w = np.where(s >= q3, np.minimum(2.5, w * 1.05), np.where(s <= q1, np.maximum(0.3, w * 0.95), w))
    return kept, gains, np.array(pre_worst), w


def main():
    keep = {"rolling": [], "fresh": []}
    gain = {"rolling": [], "fresh": []}
    worst, at_max, at_min = [], [], []
    for _ in range(RUNS):
        k, g, pw, w = run()
        for m in keep:
            keep[m].append(k[m][0] / k[m][1])
            gain[m].extend(g[m])
        worst.extend(pw)
        at_max.append(np.sum(w >= 2.5 - 1e-9))
        at_min.append(np.sum(w <= 0.3 + 1e-9))
    print(f"\n{'=' * 100}\nATLAS NULL - {AGENTS} agents with zero skill, {DAYS} days, {RUNS:,} runs")
    print(f"  worst agent's 60-day rolling Sharpe (per recommendation) when picked: median {np.median(worst):+.3f}, "
          f"5th-95th {np.quantile(worst, 0.05):+.3f} to {np.quantile(worst, 0.95):+.3f}")
    for m in keep:
        print(f"  '{m}': a do-nothing change is kept {np.mean(keep[m]):.1%} of the time "
              f"(5th-95th across runs {np.quantile(keep[m], 0.05):.1%}-{np.quantile(keep[m], 0.95):.1%}); "
              f"mean Sharpe 'improvement' {np.mean(gain[m]):+.3f}, when kept {np.mean([x for x in gain[m] if x > 0]):+.3f}")
    print(f"  Darwinian weights after {DAYS} days: agents at the 2.5 ceiling median {np.median(at_max):.0f} "
          f"(5th-95th {np.quantile(at_max, 0.05):.0f}-{np.quantile(at_max, 0.95):.0f}), at the 0.3 floor median "
          f"{np.median(at_min):.0f} ({np.quantile(at_min, 0.05):.0f}-{np.quantile(at_min, 0.95):.0f})")
    print("  ATLAS reported: 16 of 54 kept (30%); 7 agents at 2.5 and 4 at 0.3 of 24")


if __name__ == "__main__":
    main()
