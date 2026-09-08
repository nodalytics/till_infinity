# Papers, and the one thing they all guard against

References, what each actually does, the single idea that transfers here, and -
more usefully - what does not. Written because the interesting question is
never "what did the paper achieve" but "what of it survives contact with a
non-stationary, low signal-to-noise problem with no simulator".

Two halves. The first four are machine-learning papers read for their
methodology; the [market microstructure section](#market-microstructure-what-the-literature-says-about-the-things-this-desk-draws)
at the end is about the objects this system actually draws - levels, fair
value, positioning - and each entry there names the part of the code it would
change.

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

## The triple-barrier method - the one idea here already in use

Not from the four papers above, and worth its own section because this
repository arrived at it from the trading side rather than the literature.

**López de Prado, *Advances in Financial Machine Learning* (Wiley, 2018),
chapter 3.** The method: instead of labelling a bar by its forward return, set
three barriers - a profit target, a stop, and a **time limit** - and label the
observation by which one price touches first.

Why it is better posed than a return, and why it fits here:

* **both outcomes are defined in advance.** A direction call has to be scored
  against an arbitrary horizon; a barrier label is scored against the trade
  that would actually have been taken.
* **the vertical barrier is the part everyone forgets.** Without a time limit
  an open position is labelled by whatever eventually happened, which is how a
  weekend gap became a 27-volatility-unit rejection here once - and why
  `GAP_FACTOR` exists.
* **it is already the shape of the machinery.** A touch resolves when price
  travels `resolve_vol` either way or the horizon expires. That *is* a
  triple-barrier label, arrived at independently and named differently.

[barriers.md](barriers.md) applies the frame to two levels with price between
them, which is the trade `origin-swing` was written for.

The adjacent chapters are the more valuable ones for the problems this
repository keeps hitting, and are the honest "read next":

* **chapter 7, purged and embargoed cross-validation.** The discipline that
  stops the leakage found by hand in similarity.md and horizon.md.
* **chapter 4, sample uniqueness and concurrency.** Overlapping labels are not
  independent observations - directly the problem behind one grinding episode
  counted as 171 touches.
* **chapter 5, fractional differentiation.** Stationarity without throwing away
  memory, which is the trade-off `volatility.py` makes by hand.

The caution that applies to all of it: the book's own backtests are widely
argued to be optimistic, and its value here is the *methodology* rather than
any result. The triple-barrier method is a labelling discipline, not an edge.

## Market microstructure: what the literature says about the things this desk draws

Added 2026-09-07. Every paper here maps onto something already built, and in
three cases onto something built and read by nothing - the shape
[inert.md](inert.md) catalogues.

| | |
|---|---|
| **Support for Resistance** | Osler, *Technical Analysis and Intraday Exchange Rates*, FRBNY Economic Policy Review 6(2), July 2000. [SSRN 888805](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=888805) · [FRBNY](https://www.newyorkfed.org/research/epr/00v06n2/0007osle.html) |
| **VWAP** | Zarattini & Aziz, *Volume Weighted Average Price (VWAP): The Holy Grail for Day Trading Systems* (2023). [SSRN 4631351](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4631351) |
| **VWAP regimes** | Lee, *VWAP-Based Regime Classification Model for Intraday Price Dynamics*. [SSRN 6438039](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6438039) |
| **Open interest** | Hong & Yogo, *What Does Futures Market Interest Tell Us about the Macroeconomy and Asset Prices?*. [SSRN 1364674](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1364674) |
| **Funding rates** | Inan, *Predictability of Funding Rates*. [SSRN 5576424](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5576424) |

### Osler - levels work, and round numbers work as well

**What it does.** Takes the support and resistance levels **six FX firms
actually published to their customers**, and tests whether price stalls at
them. It finds strong evidence that they predict intraday trend interruptions,
with the predictive power varying by currency and by firm.

**What transfers.** This is the closest thing in the literature to an
independent test of what `structures` is for, and it is the right shape: the
levels were published *in advance* by someone with money on the line, so there
is no hindsight in where they were placed. That is the same discipline as
predict-then-update here.

The *variation by firm* is the more useful half. Levels are not a property of
the market alone - they are a property of the method that drew them - which is
the argument for `formation` being an experiment (`pip` against `run`) settled
by the outcome machinery rather than a setting to taste.

**What does not transfer, and it is the finding to take seriously.** Osler
also shows **round numbers predict about as well as most published levels**.
That is a control this repository has not run, and it is devastating in the way
[magnet.md](../docs/magnet.md)'s arbitrary-price baseline was devastating: if a
level drawn from Kalman-filtered swing origins across eight timeframes does no
better than "the nearest round number", the whole drawing apparatus is
decoration. **It is one query against the existing touch record** - bucket
resolutions by distance to the nearest round number and compare hold rates -
and it belongs above most of [todo.md](../docs/todo.md).

### Zarattini & Aziz - and why the numbers are the warning, not the promise

**What it does.** Long above VWAP, short below, intraday, on QQQ from January
2018 to September 2023: $25,000 to $192,656 net of commissions, 671%, maximum
drawdown 9.4%, Sharpe 2.1, against buy-and-hold's 126% at a 37% drawdown. On
TQQQ, the 3x leveraged version, 8,242%.

**What transfers.** VWAP as a *second definition of fair value* -
[idea.md](../docs/idea.md) defines it as where a supply or demand spree began;
this defines it as where the volume actually traded. Two definitions that
disagree is information, and a price both agree on is a stronger claim than
either alone, which is the argument `confluence` already makes across
timeframes. See [todo.md](../docs/todo.md) for what would have to be counted
first: the `bars` table's `volume` column is nullable and unevenly populated,
and whether there is volume to compute it from is a prior question to whether
it predicts.

**What does not transfer.** One instrument, one index, one regime, and the
regime is the 2018-2023 QQQ tape. A Sharpe of 2.1 with a 9.4% drawdown from a
rule with no parameters should raise the same suspicion this repository learned
to have of its own 84-88% accuracy: **be suspicious of a metric that is going
up.** Independent replications over longer windows report it working in a
minority of the years.

And the institutional reading, which is the honest one: institutions use VWAP
to gauge fair value and to place a large order without moving the market
against themselves. Both are uses of a *measurement*. Traded mechanically as a
standalone rule - no volume confirmation, no risk management - it draws down
heavily, which is the whole argument of
[idea.md](../docs/idea.md)'s opening.

### Lee - VWAP deviation as a regime label

**What it does.** Normalises the deviation of price from VWAP by volatility and
uses the result to classify intraday regimes as trend-dominated or
mean-reverting.

**What transfers.** The **normalisation**, which is the same move this system
makes everywhere: a deviation in price units is not comparable across
instruments, and one in volatility units is. Beyond that it is a direct
competitor to `learning/regimes.py`, which classifies from price alone - so the
question it poses is whether a volume-aware regime label beats a price-only
one, on the same touches, which is answerable here rather than arguable.

**What does not transfer.** A regime label that is not scored against outcomes
is a second opinion nobody can check. This one would have to earn its place the
way `slowing` did: uncorrelated with what is already in the model, then
marginal AUC.

### Hong & Yogo, and Inan - the two collectors that feed nothing

**What they do.** Hong & Yogo find that movements in futures-market open
interest predict commodity returns, bond returns and the short rate, *after*
controlling for known predictors - the argument being that open interest is
more informative than price when hedging demand and risk-absorption capacity
matter. Inan finds perpetual-swap funding rates are predictable out of sample
against a no-change benchmark.

**What transfers.** These are the papers for `prices/positioning.py` and
`prices/funding.py`, both of which collect and are read by nothing.
[crypto.md](crypto.md) already argues open interest ranks above funding here
and gives the reason - OI plus price direction separates fresh money from
closing, and the price path is identical in both cases - so Hong & Yogo is
support for the ordering already chosen rather than a new idea.

**What does not transfer.** Horizon and asset class. Both are about weekly to
monthly predictability in commodities and macro; this desk resolves touches in
minutes. And funding carries the leakage risk `crypto.md` names: it is computed
from the premium, which is computed from price, so a model handed funding may
be handed a lagged transform of what it already sees. Predictable is not the
same as *informative about something else*.

## Change points, and the one that answers the question we actually lose money on

Added 2026-09-08.

| | |
|---|---|
| **Residual time** | Agudelo-España, Gomez-Gonzalez, Bauer & Schölkopf, *Bayesian Online Prediction of Change Points*, UAI 2020, PMLR 124:320-329. [PDF](https://proceedings.mlr.press/v124/agudelo-espana20a/agudelo-espana20a.pdf) |
| **BOCPD, the original** | Adams & MacKay, *Bayesian Online Changepoint Detection* (2007) |
| **BOCPD in practice** | [MQL5: BOCPD, one regime-break signal, three ways to use it](https://www.mql5.com/en/articles/23482) |
| **Regime by autocorrelation** | [MQL5: a custom market regime detection system](https://www.mql5.com/en/articles/17737) |
| **HMM volatility states** | [MQL5: hidden Markov models for trend-following volatility prediction](https://www.mql5.com/en/articles/16830) |

### The UAI paper is about *when the next one comes*, and that is the gap here

Standard BOCPD maintains a distribution over **run length** - how long since the
last regime change - and infers change points retrospectively. This paper
extends it to infer the **residual time**: how many steps until the *next*
change. The abstract's own framing is that this "enables handling observation
models which depend on the total segment duration".

**That is the single most expensive unknown on this desk.** `thesis-only`
closed 74 trades at target or stop for a net **-7.10**, and 75 on the clock for
**-389.98**. Ninety-eight per cent of the loss was the hold timeout - a
constant nobody had measured, on a horizon nobody had modelled. `runner` has
the same shape: it widens its target and then closes 16 of 26 trades on a
four-hour clock, so the mechanism it exists for never operates.

`context/timing.py` already answers the neighbouring question -
`probability_within(distance_vol, bars)`, a first-passage model for how long
price takes to travel a distance. What it cannot say is how long the *regime*
has left, which is what decides whether a thesis is slow or dead. Residual time
is that quantity, inferred online, from a family this repository already uses
in `Cusum` and `regimes`.

**And it is not refuted by the change-point work already done here.**
[localising.md](localising.md) measured estimator H - a CUSUM change point - and
it lost to the fine-resolution transition, 0.205v against 0.124v. That test
asked **where in price** the transition sits. Residual time asks **how long
until the next one**. My own summary said H's loss was "evidence about the
family"; it is not evidence about this, and the distinction is the difference
between a fair prior and a closed door.

### The MQL5 BOCPD article is worth reading for its control, not its returns

Normal-Gamma conjugate prior, Student-t posterior predictive, log-space
arithmetic, constant hazard - the standard construction, written out. Its
result on EURUSD M30: a risk overlay that de-risks for a cooldown after each
detected break cut maximum drawdown from 856.50 to 755.60, **skipping 4 trades
of 97**.

The part worth copying is the next sentence: **a randomised control that
de-risked at the same frequency made results worse.** That is the null this
repository insists on - `research/null.md`'s argument, arrived at
independently - and it is what separates "the timing mattered" from "less
exposure helped". Any regime overlay built here should ship with that control
in the same run, not afterwards.

### The two regime articles, against what already exists

**Autocorrelation for trend versus range** is a simpler classifier than
`learning/regimes.py`, which is an online model over several inputs. The idea
worth taking is not the method but the **label**: positive autocorrelation as
trending, negative as ranging, is a definition that can be checked against
outcomes, and `regimes.py`'s label has never been scored against whether a
level held. That is a measurement this book can run today.

**The HMM over volatility states** trades only when a moving-average signal
coincides with a predicted high-volatility state, filtering about 70% of
trades: profit factor 1.73 against 1.48 out of sample, and 1.10 over a
2004-2024 rolling test at a 32.6% win rate. Two things to carry:

* The **filter is the product**, not the entry. Seventy per cent refused is the
  same shape as the confirmation gate on `swing-level`, which refuses 76% and
  is the only component of that strategy measured to pay.
* The rolling number - 1.10 over twenty years against 1.73 in one - is the
  honest one, and the gap between them is what a single out-of-sample window
  is worth.

**What does not transfer.** Both articles evaluate on one instrument with a
moving-average backbone this desk does not have and would not adopt. The value
is in the regime label and its control, not in the strategy wrapped around it.

## Game theory, and the question this desk never asks

Noted 2026-09-07, unread rather than summarised - listed because the question
it poses is one nothing here has an answer to.

| | |
|---|---|
| **GTO, the poker origin** | Bowling, Burch, Johanson & Tammelin, *Heads-up limit hold'em poker is solved*, Science 347 (2015) |
| **The economics** | Osborne & Rubinstein, *A Course in Game Theory* (MIT, 1994) - chapters 2 and 3 for minimax and mixed strategies |
| **Adversarial market models** | the market-making literature on adverse selection, Glosten & Milgrom (1985) being the standard entry |

**The idea, stated so it can be argued with.** A game-theory-optimal strategy
cannot be exploited whatever the opponent does; an exploitative one beats a
particular opponent and loses to a different one. **Everything on this desk is
exploitative.** `swing-level` bets a wall holds, `runner` bets a move extends,
`sweep-aware` bets a break traps - each a claim about what the other side will
do, fitted to a period in which they did it. When the population changes, the
only signal is the equity curve.

**What transfers.** Two things, and one of them is cheap.

*Mixed strategies.* Every gate here is deterministic - the same signal always
produces the same decision - which is precisely the property an adversary
needs. Randomising between two acceptable actions at a measured frequency is
the standard defence, costs almost nothing to implement, and is directly
testable: the replay harness can run a mixed policy against a pure one on the
same signals.

*Minimax as a research tool.* [null.md](null.md) already scores every feature
against a generated process with no structure. An adversarial process built to
defeat a *specific* gate is the stronger version of the same discipline, and it
answers a question the null cannot: not "is this measuring noise" but "what
would it take to make this wrong on purpose".

**What does not transfer, and it is most of it.** Poker is a finite game with
known rules, known payoffs and an opponent who is also playing it. A market has
no defined action set, no payoff matrix, and the "opponent" is a population
whose composition changes. Solving heads-up limit hold'em took an algorithm run
to convergence on a game whose entire tree is enumerable; nothing about this
problem is.

The specific trap is that GTO language makes a strategy *sound* robust without
making it so. Calling a fixed threshold "unexploitable" because nobody has
exploited it yet is the same error as reading 84-88% accuracy as skill - it is
[the reward hacking above](#the-thing-they-share-and-why-it-is-the-reason-to-read-them),
in a new vocabulary.

**Where it would start.** Traps are **64% of all attempts to break a level**
here and 84% at 1h - a false breakout is mechanically the obvious trade losing,
which is what an exploitative strategy looks like from the other side. That is
the one place on this book where an adversarial reading has a number behind it
already. See [docs/todo.md](../docs/todo.md).

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
