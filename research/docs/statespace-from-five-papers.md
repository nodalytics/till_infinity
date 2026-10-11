# statespace: ideas from five references, each with the null it needs

Reviewed on 2026-10-11, on request. Nothing here is a result - these are
candidates, and the point of writing them down with their nulls attached is
that an idea without one is how this desk has produced most of its wrong
answers. Ordered by what they would actually change.

| | |
|---|---|
| Kretschmer, Harrieder, Witting, Böcker, *Times are changing but order matters*, Nature Methods (2026) | `.secrets/s41592-026-03243-2.pdf` |
| Minaei, Milke, Leung, Luca, *An Unsupervised Intelligent System for Adaptive Decision Control in Non-Stationary Financial Environments*, JRFM 19:801 (2026) | `.secrets/jrfm-19-00801.pdf` |
| Myshak, Bin Mizan, Timofeyev, *Parametric PINN vs Tensorial Reduced-Order Model for the Shallow-Water Dam-Break Problem*, Fluids 11:251 (2026) | `.secrets/fluids-11-00251.pdf` |
| Boulton, Shohfi, Walz, *How Does Payment for Order Flow Influence Markets?*, SEC DERA working paper (Jan 2025) | sec.gov/files/dera_wp_payment-order-flow-2501.pdf |
| *Auction Market Strategy*, TradeZella | tradezella.com/strategies/auction-market-strategy |

---

## 1. Predict the order, then map the order to the value

**The strongest idea here, and it comes from chromatography.** Retention
*times* change massively between instruments - even nominally identical ones -
so a model trained on one laboratory does not transfer. Retention *order* is far
better conserved. So the paper predicts a **retention order index**: a real
number whose *ordering* is the thing being learned, trained with a Siamese
pairwise ranking loss, with the instrument's conditions as explicit input
features. Then a **degree-two polynomial** maps that index onto absolute times,
fitted on about fifteen to thirty "anchors" measured in the target system.

Two tasks, disentangled, and the result transfers to systems with no training
data at all - outperforming models that *were* trained on the target.

**Why it belongs here.** This desk already has the result in miniature and did
not generalise it: over 293,252 live resolutions a level's raw record scores
**AUC 0.5005** while `|record - 0.5|` scores **0.6006**. A monotone
transformation of the same number carried everything; the level carried nothing.
That is the same lesson - the ordering survives what the value does not.

It also answers the portability problem directly. Today's work established that a
*window* is portable when stated in time; this says a *prediction* is portable
when stated as a rank. The architecture would be: one ranking model across every
instrument and timeframe, with the instrument's conditions as features, plus a
tiny per-instrument monotone map from rank to quantity refitted on recent
anchors.

Three details worth copying exactly:

* **A threshold on the pairs.** They only compare compounds whose retention
  times differ by more than ten seconds, because a pair closer than the
  measurement noise teaches the model noise. The analogue is sharp: compare
  outcomes only when they differ by more than **one spread**, which makes the
  cost model part of the loss rather than a filter applied afterwards.
* **Count the informatory pairs first.** 93.8% of their compound pairs never
  change order between conditions, so only 6.16% can possibly carry information
  about conditions - and the paper says so before claiming the conditions
  matter. The analogue is a **cheap pre-test before building any
  regime-conditional model**: count the pairs whose order changes between
  regimes. If almost none do, a regime-aware model cannot beat a regime-agnostic
  one, and that is knowable without training either.
* **The simple mapping won.** Median regression plus OLS on a degree-two
  polynomial beat GAMs, shape-constrained additive models and constrained
  B-splines. Null-first, again.

**The null.** The ranking model must beat the same model trained per instrument,
on the instruments it was not trained on. And the two-step must beat one step:
if predicting the quantity directly does as well, the disentangling bought
nothing.

## 2. The regime gate, and the control it shares with this desk

JRFM 19:801 gates execution rather than prediction: walk-forward K-means over
multi-timeframe features assigns a regime, and trades are permitted only in
admissible states, so "clustering governs **when** predictions are acted upon
rather than how they are formed". They report maximum drawdown halving on
several assets and the S&P 500 Sortino rising from 2.57 to 6.63.

**The reason to take it seriously is the control**, which is the one this desk
already uses: a Monte-Carlo **random-drop ablation** that randomly suppresses
baseline trades to match the gated count exactly, over 1,000 iterations, to show
the gain is not from trading less often. That is the duty-cycle control, and
every pause rule proposed here has died on it.

**The reason to be careful** is in their own abstract: *"Results are gross of
transaction costs."* A gate that cuts trade frequency by up to two thirds moves
a strategy's cost burden more than its returns, so a gross result from a gate is
the one place a cost line is least optional. This desk has the measurement that
makes the point - an effect at `t = -7.1` that was 0.16 spreads wide.

Two things are worth taking regardless of whether the result replicates:

* **Make the gate structurally necessary.** Their activation threshold is
  additive, with the technical weights set so that their maximum combined
  contribution stays strictly below the threshold - so no configuration of the
  directional signals can open a position without the regime layer agreeing. A
  veto applied afterwards can be argued away; a term that cannot reach the
  threshold alone cannot.
* **Gate on admissibility, not on direction.** Separating "is this state one my
  model was fitted for" from "what does my model say" matches the guiding
  principle already in `__init__.py`: a member whose parameters drift faster
  than they can be estimated is the failure with no remedy. `Changepoint` and
  `Paired` already compute the admissibility signal; nothing consumes it.

**The null.** The duty-cycle control, and the cost line. Both.

## 3. Shock-aware collocation: gate the prior where it is invalid

Fluids 11:251 compares a physics-informed neural network with a tensorial
reduced-order model on the shallow-water dam-break problem. The transferable
content is in the ablations rather than the comparison.

* **Shock-aware collocation.** At a discontinuity the differential form of the
  equation is not valid, so enforcing it there degrades the fit. They sample
  more densely near the shock and **gate the PDE term**. The analogue is exact:
  a Kalman's smoothness prior is invalid at a jump, and the member currently
  fights the data there. `Changepoint` already publishes `changepoint` - the
  posterior mass on a fresh run - so the improvement is to **inflate the process
  noise in proportion to it** rather than to reset. A reset throws away the
  state; this just stops asserting continuity for as long as the evidence says
  there isn't any.
* **Slow Kolmogorov `n`-width for transport-dominated problems.** A moving front
  cannot be compressed by a fixed linear subspace, however many modes it is
  given - which is a *structural* argument for mixtures and local bases over one
  Gaussian, and so an argument for `swarm` that does not depend on `swarm`
  winning a bake-off. It also predicts where a single-Gaussian member should
  fail: when the thing being tracked *moves*, rather than when it is noisy.
* **Residual scaling**, so terms of different magnitude contribute comparably to
  one objective. The analogue is the `noise`-means-variance correction already
  made here, and the same class of error.
* **Interpolation and extrapolation in parameter space are reported
  separately.** Worth copying as a discipline: a member fitted over one range of
  volatility should be scored inside and outside that range as two numbers.

**The null.** Process noise driven by `changepoint` must beat both a fixed
process noise and a hard reset, on held-out likelihood, on the same series.

## 4. Costs are a time series, and the flow composition moves them

The SEC DERA paper uses Robinhood's crypto token introductions as a payment-for-
order-flow shock and measures what happens to market quality: volume falls,
order imbalance shifts to net sales, and average trade size, **implied spreads**
and return volatility all rise, for about **$4.8 million a day** in extra
trading costs. PFOF in crypto carries fees 4.5 to 45 times those in equities.

Three things transfer:

* **Implied spreads where there is no reliable quote.** They measure spreads
  from trades alone, which is this desk's situation on several feeds, and
  `volatility_ceiling.py` already computes Roll's estimator. The idea is to
  **prefer it to the broker's spread field** wherever the two disagree - and the
  disagreement is itself a measurement, since the broker's number is the one the
  desk is charged against.
* **Cost as a state with its own dynamics.** Every cost gate here uses a
  constant: one spread, or 4bp. This paper's whole finding is that the number
  moves, and moves with the *composition of the flow* rather than with
  volatility alone. A member whose subject is the spread - observed jointly
  through implied spread, trade size and volatility - would make the gate
  forecast-based rather than average-based. That is the time-varying `R`
  improvement already recorded in the README, with a reason to build it.
* **An exogenous event as identification.** They do not search for an effect;
  they take a shock with a known date and measure around it. The desk's
  equivalent already works - scheduled releases run at **2.42x** normal
  volatility on the print - and the lesson is to find *more* events with known
  dates (venue changes, contract rollovers, session boundaries, synthetic index
  resets) rather than mining for effects without one.

**The null.** For the spread member: beating a trailing average of the spread,
out of sample. Nothing else counts, and that null is a hard one.

## 5. Auction market theory, as a set of claims to test

The TradeZella page is a vendor write-up rather than a source, and it should be
read as a list of hypotheses. Its substance: the market alternates between
**balance** (price rotating around fair value) and **imbalance** (one side
aggressive, seeking new value); the **point of control** is the target; entries
sit at **low-volume nodes**; and no trade is taken without order-flow
confirmation.

It is worth recording because the vocabulary maps onto this package almost
one-to-one - balance is a mean-reverting state, imbalance is an integrated one,
and `changepoint` is the transition between them - which makes it testable
rather than decorative. A two-state member whose states are exactly those, with
the transition fitted rather than drawn, is a concrete member to build.

**Two numbers it asserts without a source**, and both are directly measurable
here: that price stays in balance about **70%** of the time, and that it
reverses from balance about **70%** of the time. The desk has already measured
the neighbouring claim and found it false - price reaches a level within twenty
bars **44.9%** of the time against **49.5%** for an arbitrary price the same
distance away, so a level is not a magnet. The same control applies: a 70% rate
means nothing until the rate for an arbitrary comparable price is beside it.

**The null.** Any balance/imbalance member must beat `linear` on held-out
likelihood, and the 70% claims must be scored against a matched arbitrary-price
control before either is quoted.

---

## What to build first, if anything

1. **Count the informatory pairs** (§1). It is a few hours of work, needs no
   model, and it decides whether *any* regime-conditional or
   condition-conditional model in this package can work. If orders rarely change
   between regimes, several open ideas are already dead and nothing needs
   training to find out.
2. **Process noise driven by `changepoint`** (§3). The signal exists and is
   published; nothing consumes it; the null is one line.
3. **The rank-then-map architecture** (§1), which is the largest of these and
   the one most likely to matter, because it attacks portability - and
   portability is what this week's measurements showed is the binding constraint
   rather than model class.
