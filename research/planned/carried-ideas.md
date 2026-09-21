# Carried ideas — not built here

**Status: a triage, not a plan.** None of this exists in this code. It collects research
directions from earlier work of mine elsewhere and grades each one against what has since been
measured *here*, so the ones already answered are not run twice and the ones still open are
stated precisely enough to run.

Two filters are applied to everything below, and they kill most of it:

* **the cost hurdle.** Break-even at reward-to-risk one is a **52.0%** hit rate on FX and
  **51.6%** on the synthetics, from `costs.md`. An idea that cannot plausibly clear two points
  is not worth the harness.
* **the power floor.** `power-and-sizing.md` requires the minimum detectable effect to be
  computed *before* the run. Several ideas below are attractive precisely because they produce a
  single score rather than a rare conjunction, which is what makes them detectable at all.

## Already answered here — do not re-run

| carried idea | what was measured here | verdict |
|---|---|---|
| Topological structure shift / persistent homology as a signal | `topology.md` — persistence landscapes lost to six trailing ratios by 6.8 points on volatility; `shapes` and `motifs` died on bootstrap and at two embeddings | closed |
| Criticality / phase detection as continuation | `breakout-runs.md` — the reversal hazard is **flat** after two bars, so nothing exhausts with age | closed for the age form |
| Reversal at over-extension | `stretch.md` — six stretch measures, six triggers, five timeframes, three instrument sets; no monotone decile gradient anywhere and the most stretched decile is worst on daily | closed |
| Quantum superposition / decoherence | rejected in the earlier work itself — zero collapse events on any asset | closed |
| RL optimal execution | rejected in the earlier work itself — 10,000 training steps is about 40 episodes, which the author correctly called grossly insufficient | not evidence either way |

## Still open, ranked by what they would cost to settle

### 1. β0 as a reversal lead — worth one run

The claim from the earlier work: the number of connected components in the price topology
**drops 5-10 bars before reversals**, described as universal across assets, with ETH at
p = 0.0003.

Worth running despite `topology.md`, because it is a **different claim**. That document tested
persistence features as *volatility* predictors and as shape descriptors; this is a directional
lead on turns. And β0 on a Vietoris-Rips complex over a price window is the Euclidean minimum
spanning tree — cheap, already implemented in the topology harness, and reducible to one number
per bar, so it is a single hypothesis with the whole series as its sample.

Predict before running: if β0 is falling before reversals, it is measuring dispersion collapse,
which is range contraction — and `stretch.py`'s `stall` trigger already tested range contraction
and found nothing. **So the pre-registered expectation is that β0 adds nothing over stall**, and
the run is worth it only because the ablation against `stall` is the cheap way to find out.

### 2. Transfer entropy and lead-lag across instruments — worth one run

The earlier work found crypto moving as a triad (correlation 0.57-0.66) with lagged cross-class
contagion, and ranked directed information flow between features.

This is the one direction with a structural reason to work *here* that nothing has tested: the
book trades 32 instruments and every study so far has treated them one at a time. A lead-lag
edge is not a claim about price history repeating, it is a claim about one venue pricing a move
before another.

But the measured correlations here set the ceiling. Cross-correlation across the Boom, Crash and
Volatility families is at most **0.009** — they are independent generators and carry no
information about each other, so the synthetics are out. That leaves FX, the indices and crypto,
where a dollar leg is genuinely shared. Test on those and not on the synthetics.

### 3. Effective dimension of the feature set — cheap and diagnostic

The earlier work found a participation ratio of **5.0 ± 0.3** across assets: eleven features
compressing to about five independent factors.

Not a signal, but a directly useful diagnostic here, and almost free. `candles.features` produces
34 features and `breakout_runs` uses 40. If the effective dimension is five, then most of that
is redundancy, which explains why ridge and trees returned near-identical nothing in
`breakout-runs.md` and tells any future model how many factors it can honestly fit. Run it as a
one-off on the existing feature matrix.

### 4. Order-flow absorption — blocked, and worth saying why

Needs level-2 depth. The bridge serves bars and a single spread figure per bar; there is no book.
**This cannot be run at all on the current data**, and the honest entry is that it is blocked
rather than untested. It is also the same class of missing data as the tick history that would
settle the slippage bracket in `costs.md`, so one acquisition would unblock both.

### 5. Multi-timeframe attention and regime embeddings — deferred, deliberately

Both are learned representations over features, and both would sit downstream of a signal that
works. Nothing here has found one. Fitting a representation over features whose individual
effects are inside their own error bars is how a model learns the noise; `power-and-sizing.md`
is the argument for not starting here.

They become interesting if [ensembles.md](ensembles.md) finds that a combination clears the
hurdle, because at that point there is something for a representation to sharpen.

## Ideas about process rather than markets

From other earlier work, a multi-agent framework built on an event bus with debate, veto,
consensus and a metacognition layer that rewrites underperforming prompts.

Relevant here in one specific way, and it is not "run the research with agents". It is
**adversarial verification of a finding**. The single most expensive class of error in this
repository has been a result that looked real and was a modelling artefact - the Boom asymmetry
that reversed sign once losses were charged honestly, the fixed detector threshold that fired
never, the three wrong guesses about exposure in one sitting. Each was caught by a check
someone had to think to run.

A standing adversary whose only job is to attack a new result - find the cost that was not
charged, the look-ahead in the indexing, the comparison count that was not corrected - is worth
more here than another hypothesis, and `power.py` is the first instance of exactly that pattern
written down rather than performed ad hoc.

The swarm machinery itself is out of scope: this is a two-core production box and a research lab
that already serves the live desk's terminal, and `starving.md` records what happens when
research competes with the desk for cores.

## What this list is deliberately missing

No field-equation or market-model formulation is carried over. `barrier_pde.py` already
implements the one PDE that earned its place here - and it earned it by being *checked*: the
analytic drift formula was wrong and the finite-difference solver caught it. A formalism without
that kind of internal cross-check is decoration, and this repository has enough measured nulls
that another framework is not what it is short of.
