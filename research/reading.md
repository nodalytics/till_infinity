# Four papers, and the one thing they all guard against

References, what each actually does, the single idea that transfers here, and -
more usefully - what does not. Written because the interesting question is
never "what did the paper achieve" but "what of it survives contact with a
non-stationary, low signal-to-noise problem with no simulator".

| | |
|---|---|
| **AlphaGo Zero** | Silver et al., *Mastering the game of Go without human knowledge*, Nature 550 (2017). [UCL eprint](https://discovery.ucl.ac.uk/id/eprint/10045895/1/agz_unformatted_nature.pdf) |
| **Llama 3** | Grattafiori et al., *The Llama 3 Herd of Models* (2024). [arXiv:2407.21783](https://arxiv.org/abs/2407.21783) |
| **InstructGPT** | Ouyang et al., *Training language models to follow instructions with human feedback* (2022). [arXiv:2203.02155](https://arxiv.org/abs/2203.02155) |
| **DeepSeek-R1** | DeepSeek-AI, *Incentivizing Reasoning Capability in LLMs via Reinforcement Learning* (2025). [arXiv:2501.12948](https://arxiv.org/abs/2501.12948) |

## The thing they share, and why it is the reason to read them

All four are, underneath, about **a model optimising a proxy for what you
actually want, and what it does when the proxy has a cheaper solution than the
thing.** AlphaGo Zero avoids it by having a reward that is the thing itself
(win or lose). InstructGPT adds a KL penalty precisely because a policy
optimised freely against a learned reward model degenerates. DeepSeek-R1
reports language mixing and reward hacking in R1-Zero and adds a cold-start
stage to suppress it.

**This system has already done exactly that, and it took a month to notice.**
The metric was accuracy on touch direction. The cheapest solution is not to
predict anything: a touch approached from above that resolves inside a minute
resolves *upward* 100.0% of the time, because that is what a rejection means.
46% of resolutions are that fast, so every model scored 84-88% by reproducing a
definition, and the number looked like skill for weeks. See
[similarity.md](similarity.md) and [horizon.md](horizon.md).

That is the reward hacking these papers spend most of their engineering
guarding against, arrived at independently and unnoticed. It is the strongest
argument for reading them.

## AlphaGo Zero - search as a policy improvement operator

**What it does.** A single network with two heads - a policy over moves and a
value for the position - trained purely on self-play, with Monte Carlo tree
search used at every move. The trick is that MCTS output is *better* than the
raw policy, so the improved distribution becomes the training target. Search
improves the policy; the improved policy makes search better. No human games.

**What transfers.** Two things.

*One network, two heads.* The policy/value split is exactly the split this
system already has and keeps separate: direction (`probability_up`) and
magnitude (`expected_push`) are estimated by different machinery over the same
features. Sharing a representation between them is a cheap, well-evidenced
idea, and the value head is the one this repository has neglected -
[magnitude.md](magnitude.md) found `expected_push` ranks profit 7.5x while the
directional call is near chance at tradable horizons.

*Search as improvement.* The equivalent of MCTS here is a **replay**: take the
strategy's decision, roll it forward over stored bars, and use what actually
happened as the target rather than the model's own guess. The harnesses in
`harness/` already do the rolling forward; nothing yet feeds the result back as
a label.

**What does not transfer.** Nearly all of it, and the reasons are worth being
precise about. Go is deterministic, perfect-information, stationary, zero-sum
and has a *perfect simulator*. Markets have none of those - the "simulator" is
a replay of one realised path, so rolling forward does not explore alternatives,
it re-reads history. Self-play has no analogue at all: there is no opponent
whose improvement forces yours.

The nearest honest thing to self-play here is the **Deriv synthetics** - a
generated process we can draw unlimited samples from, with no structure to
find. That makes them a null rather than a curriculum, and a model that cannot
beat them is refuted rather than under-trained. See
[shelves.md](shelves.md).

## Llama 3 - the gains are in the data, not the architecture

**What it does.** A dense transformer at 8B/70B/405B, and the paper is unusually
frank that the architecture is deliberately conventional. The work is in data:
scale, quality filtering, deduplication, and an annealing phase on high-quality
data at the end of training.

**What transfers.** The headline finding, and it is directly actionable here:
**most of the gain came from curating the training data, not from the model.**

This system's training data is 46% tautology. That is a data problem of exactly
the kind Llama 3 spends its effort on, and no change of model fixes it - which
is what [learning.md](learning.md) found the hard way, with a kNN, a logistic
regression and a learned distance all landing within 0.7 points of each other
because they were all fitting the same degenerate label.

*Deduplication* has a sharp analogue too. One grinding episode was once counted
as 171 separate touches ([handoff.md](handoff.md)); consecutive touches within
seconds of each other are the same move counted several times, which is a
duplicate in every sense that matters to a fit.

*Annealing on high-quality data at the end* maps onto weighting the slow-horizon
touches, which are rare - 1,762 beyond thirty minutes against 30,118 under a
minute - and are the only ones whose labels are not free.

**What does not transfer.** The scale, obviously, and every conclusion that
depends on it. This box has 3.8GB and learns online from a few thousand rows;
none of the emergent-capability arguments apply to a model with nine features.

## InstructGPT - a reward model, and a leash on it

**What it does.** Three stages: supervised fine-tuning on demonstrations, a
*reward model* trained on human preference comparisons, then RL against that
reward model with a KL penalty back toward the SFT policy.

**What transfers.** The **KL penalty**, and it is a validation rather than a new
idea. The penalty exists because a policy optimised freely against a learned
reward finds the reward model's blind spots rather than the intent behind it.
The equivalent discipline is already here and was arrived at for the same
reason: `Memory.prior` shrinks toward the base rate, `base_rate_up` is
Jeffreys-smoothed so twenty agreeing observations give 0.98 rather than 1.0,
and `base_rate_for` shrinks a series' own rate toward the pooled one by
`BASE_WEIGHT`. Every one of those is a leash on a small sample.

The *reward model* half is the more interesting unexploited idea. Profit is a
terrible training signal - sparse, noisy, and 120 closed trades in total. A
model trained to predict the *touch outcome* is a dense, checkable proxy for it,
and that is close to what `reactions` already is. Stating it in these terms
makes the missing piece obvious: nothing measures how well the dense proxy
predicts the sparse thing anybody cares about.

**What does not transfer.** The human preference data. There is no analogue of
a labeller here and inventing one would be inventing the labels.

## DeepSeek-R1 - verifiable rewards, and what happens without them

**What it does.** R1-Zero applies RL directly to a base model with **rule-based,
verifiable rewards** - a maths answer is checkable, code either compiles or does
not - and reasoning behaviour emerges without any supervised reasoning data.
R1 adds a small cold-start supervised stage because R1-Zero, optimised purely
on outcome, produced unreadable and language-mixed output. The reasoning is
then distilled into much smaller dense models.

**What transfers.** Three things, and the last is a warning.

*Verifiable reward.* This is the property that makes R1 work, and this system
has one: a touch outcome is checkable - price held or it broke - which is why
the outcome machinery is the right foundation and profit is not. It also says
where to look for more: any quantity that can be *checked* against the record
rather than judged.

*Distillation.* R1's distilled small models retain much of the behaviour. The
analogue is running an expensive ensemble offline over the replay and distilling
it into the cheap online learner that fits the box - which is the only way
anything expensive ever runs in production here.

*And the warning, which is the most valuable part.* R1-Zero's reward hacking is
the same failure this system produced. Optimising a checkable proxy is not
enough if the proxy admits a degenerate solution. R1 needed a cold-start stage;
the equivalent here is not a stage but a **cut** - scoring by realised duration
so the degenerate population cannot dominate the number.

**What does not transfer.** The RL itself. R1 needs many rollouts per prompt
against a verifier; there is no verifier here that can be queried off-policy,
because the only way to find out what price did is to have been there.

## Where to read next

Each of these has a literature behind it that is closer to this problem than the
paper itself:

* **Search-as-improvement without a simulator** - the model-based RL line
  (Dreamer, MuZero) is the honest place to look, because MuZero learns the
  dynamics rather than assuming them, which is the actual obstacle here.
* **Data curation for noisy labels** - the learning-with-noisy-labels
  literature is more directly applicable than Llama 3's data section, and
  specifically anything on *instance-dependent* label noise, which is what a
  tautology at short horizons is.
* **Reward hacking and specification gaming** - the concrete-problems-in-AI-
  safety line, which catalogues exactly the failure above.
* **Purged and embargoed cross-validation** for financial series, which is the
  discipline that stops the leakage this repository keeps finding by hand.

Nothing in this document is a proposal. The one actionable conclusion is the
one the four papers agree on and that this repository has now demonstrated on
itself: **fix the data before the model**, and be suspicious of a metric that
is going up.
