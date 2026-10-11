# statespace: ideas from the references, each with the null it needs

Reviewed on 2026-10-11, on request, and added to as more arrive. Nothing here is a result - these are
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

---

## 6. Lattice Boltzmann, multiphase thermal flow - the thinnest of the six

Li, Zhuang, Yamaguchi and Dong, *Interface Dynamics and Heat Transfer in
Droplet-Laden Rayleigh-Bénard Convection*, Processes 14:3253 (2026).
`.secrets/processes-14-03253.pdf`. Reviewed 2026-10-11.

Stated plainly: this is further from the problem than the other five, and most
of it - wetting boundary conditions, Nusselt numbers, droplet diameter - does
not transfer at all. Four things do, and one of them is a second independent
vote for something already recorded.

* **Separate distributions, coupled through their moments.** The model carries
  *three* distribution functions - density, order parameter, temperature - each
  with its own relaxation equation, systematically coupled so that the
  macroscopic equations come out right. The analogue is a family of members per
  **subject** coupled through shared moments rather than one joint Gaussian over
  everything, which is close to what `subjects.py` already gestures at and has
  never been built: a level member, a volatility member and a regime member that
  exchange moments rather than state.
* **Design at the distribution level, verify the macroscopic behaviour.** The
  model is validated by Chapman-Enskog expansion - a proof that the intended
  large-scale equations emerge from the small-scale rules. statespace asserts
  its macroscopic model in docstrings (`linear` is integrated jerk, `reverting`
  is an integrated Ornstein-Uhlenbeck) and tests the *code*, not the **implied
  moment dynamics**. A test that simulates a member forward and checks its
  realised drift and diffusion match the model it claims would be the
  equivalent, and nothing like it exists.
* **Mass dissipation at interfaces, and an explicit correction term.** The
  phase-field model loses mass at interfaces and the literature's repair is a
  correction term that puts it back. `changepoint` folds its truncated tail into
  the last kept component precisely so "a posterior that quietly sums to less
  than one" cannot happen - the same bug class and the same fix, arrived at
  independently in a field with nothing else in common. Worth recording because
  it raises confidence in a choice that was argued rather than measured.
* **Diffuse interfaces beat sharp ones for stability**, which is why the
  phase-field branch exists at all. That is a **second independent vote** for
  the improvement already taken from Fluids 11:251: handle a regime change by
  widening the process noise across a transition band rather than resetting the
  filter at a point. Two fluid-dynamics papers, different methods, same
  preference.

One methodological caution, which is the most portable thing in it: **the
response to a parameter is not monotone**. The thermal conductivity ratio
*enhances* heat transfer at small values - the droplet acts as a thermal fin -
then crosses a critical threshold near 30-40 where local instability causes a
sharp drop, then reorganises again. A sweep that tests the endpoints and
interpolates would report the opposite of the truth in the middle. Several
grids in this repository are coarse enough for that, and the fix is to sweep
densely enough to see a cliff rather than to assume the interior.

---

## 7. Lillo on order flow and price formation - the richest of them

Fabrizio Lillo, *Order flow and price formation*, arXiv:2105.00521. A review,
and it contains the single most useful connection to work already in this
package.

### The `3/4` in our own roughness harness is this paper's number

`volatility_roughness.py` says in its header: *"The theory predicts H ~ 0 (from
H0 ~ 3/4 and H = 2*H0 - 3/2)"*. That `H0` was never sourced. **It is the Hurst
exponent of the order flow sign**: the autocorrelation of the sign of market
orders decays as `C(tau) ~ tau^-gamma` with `gamma ~ 0.5` empirically, giving
`H0 = 1 - gamma/2 ~ 0.75`. So the roughness prediction this desk has been
measuring against descends from a measured property of order flow, and the two
numbers are the same object seen at two scales.

That also sharpens what the roughness measurement means. We read `H` of 0.04 to
0.18 on FX against a predicted 0. If the chain `H = 2*H0 - 3/2` holds, our
reading implies `H0` of 0.77 to 0.84 against the literature's 0.75 - closer than
"we measured 0.1 and theory says 0" makes it sound.

### Order splitting, not herding, and it is measured

The long memory has two candidate causes: many traders agreeing (**herding**) or
one trader slicing an order (**splitting**). Toth et al. decompose the
autocorrelation exactly, `C(tau) = C_split(tau) + C_herd(tau)`, using
broker-labelled data, and find `C_split` is **always above 75% and above 85%
except at the very shortest lags**.

That is a mechanism for something this desk keeps finding and not explaining.
Persistent directional pressure is mostly *one participant executing*, not the
market learning something - and the two have opposite consequences: a metaorder
ends, and price reverts; information does not revert. It is a candidate
explanation for the short-horizon reversal measured in
`statespace-time-windows.md` at -2.1pt on FX 15m, and for why that reversal is
absent on v75, which has no participants.

### Conditioning on the right state makes the memory disappear

The deepest idea here for a state-space package. Huang et al.'s **queue-reactive
model** makes order arrivals Poisson with an intensity that is a *function of
the current book state* - and then "the empirically observed autocorrelation of
the order flow is seen as a consequence of the persistence of the queue size".

The long memory is not in the process. It is in the state, and conditional on
the state the process is memoryless.

That is the design principle this package half-states and never applies as a
criterion: **choose the state so the innovations are independent**. The
machinery to check it already exists - `diagnostics.py` runs Ljung-Box on the
standardised innovations - but it is used as a specification *test* rather than
as the thing a state is selected to satisfy. A member whose innovations fail
Ljung-Box has the wrong state, not bad luck.

### A power-law decay kernel, where we use exponentials

The transient impact model in multi-asset form:

    p_i(t) = p_i(0) + sum_j integral f_ij(rate_j(s)) G_ij(t-s) ds + noise

`f` is non-linear, well described by a power law with exponent below one, and
`G` is a **decay kernel**. Every member here decays exponentially, because that
is what a Markovian state does - and an exponential kernel cannot produce long
memory, which is the thing the data has. The S4/HiPPO lineage already in this
package's reading list exists precisely to give long-memory kernels a
state-space form, so the two halves are present and have never been joined.

**The null.** Any long-memory kernel must beat the exponential one on held-out
likelihood, member against member, which is the comparison `members()` is for.

### Cross-impact, which this desk can measure and has not

`R_ij(tau)`, the response of asset `j` to an order on asset `i`, is non-zero and
about **five times smaller** than the self-response. Three sources: correlated
prices, commonality in liquidity, and quote revision. `prices` already collects
many instruments on one clock, and `structures` already prices a *relationship*
as a subject - so the ingredients are here and the measurement is not.

## 8. TradeFM, and what it independently confirms

Kawawa-Beaudan, Sood, Papasotiriou, Borrajo and Veloso, *TradeFM: A Generative
Foundation Model for Trade-flow and Market Microstructure*, arXiv:2602.23784. A
524M-parameter decoder-only transformer over billions of trade events from 9,000
US equities.

**It confirms the fix made in `rank_then_map.py` today, at scale.** One model
spans nine thousand instruments and transfers **zero-shot to APAC markets**, and
the mechanism is exactly the one that turned our global ranker from +0.05 to
+0.19: every feature is **scale-invariant**. Interarrival in seconds, volume in
logs, price depth normalised by the mid, price relative to the day's open. Not a
per-instrument model anywhere. Taken with the chromatography paper and the
informatory-pairs measurement, that is three independent arrivals at the same
place: *make the quantity comparable and one model spans the conditions*.

Three concrete things:

* **Conditions as input tokens.** Liquidity tier, price-level change, and a
  market-versus-participant indicator are conditioning inputs, not separate
  models - the third instance of the pattern after the paper's column and pH and
  our volatility tercile and session.
* **Binning recipe.** Quantile bins for price depth, equal-width bins on *log*
  values for volume and time, and **outliers beyond the 1st and 99th percentiles
  to their own bins** rather than clipped into the end bins. The
  informatory-pairs harness uses equal-frequency deciles, which agrees; the
  outlier bin is the part worth copying, since clipping a tail into a bin makes
  that bin mean two things.
* **Evaluation by stylized facts, which this package does not do.** The model is
  judged on whether rollouts reproduce near-zero return autocorrelation, slowly
  decaying autocorrelation of *absolute* returns, and kurtosis declining toward
  Gaussian at longer intervals - plus K-S and Wasserstein distances against real
  data.

**That last one is a gap worth closing cheaply.** `paths.simulate` already
exists. Every member here is scored on held-out likelihood and **never on
whether simulating it forward produces a series that looks like a market**. A
member that cannot reproduce volatility clustering is mis-specified whatever its
likelihood says, and this is three stylized facts and an afternoon.

## 9. Düring's programme: structure-preserving schemes, and kinetic derivations

Bertram Düring's research page spans kinetic opinion and wealth models,
Wasserstein gradient-flow discretisations, high-order compact finite differences
for option pricing, and pricing-kernel asset pricing. Four things transfer.

* **Replace clamps with a discretisation that cannot violate the constraint.**
  The gradient-flow scheme gives "built-in conservation of mass and
  non-negativity of the solution" and appears unconditionally stable with no
  time-step restriction. This package instead *clamps*: `existence = min(1.0,
  ...)`, `max(spread, 1e-12)`, a covariance kept positive by construction in
  some members and by arithmetic luck in others. A clamp is a bug that has been
  prevented from crashing, not a model. Where a quantity must stay in `[0, 1]`
  or stay positive, the discretisation should make that impossible to violate.
* **Macroscopic behaviour derived from microscopic rules, not asserted.** The
  kinetic programme starts from pairwise interaction rules and derives a
  Fokker-Planck equation in a quasi-invariant limit, and the **tail index of the
  steady state is a function of the interaction rules** - Pareto tails come out
  of the exchange dynamics rather than being assumed. This package asserts its
  process models in docstrings (`linear` is integrated jerk) and has a recorded
  but unbuilt "Student-t observation model". That idea is backwards: fat tails
  should **emerge** from the dynamics, as they do here from multiplicative noise
  and a saving propensity, rather than be bolted onto the observation equation.
* **Wasserstein as a metric, which we never use.** The comparison of two wealth
  models turns on convergence *rate* to the steady state - exponential for one,
  at best algebraic for the other - measured in Fourier and Wasserstein metrics.
  TradeFM uses Wasserstein too. Our members are compared on likelihood alone,
  and how fast a predictive distribution relaxes to its stationary form is a
  second, independent axis of discrimination.
* **The particle member has a name in this literature.** The Lagrangian scheme
  with "a time-dependent spatial grid that is naturally adaptive to the movement
  of the density" *is* `swarm`, and this is the theory that says why it should
  beat a fixed grid when the thing being tracked moves - the same argument the
  Kolmogorov `n`-width gives in §3, from a different direction.

Two smaller ones. **High-order compact schemes** are fourth-order in space on a
three-point stencil with von Neumann stability analysis to prove unconditional
stability; `selective.py` currently chooses between Euler, ZOH and bilinear
discretisation with no stability analysis at all, and von Neumann is the tool for
settling that. And the **pricing-kernel** work derives serial correlation in
returns, volatility smiles and crash-like patterns endogenously from declining
relative risk aversion - a *rational* mechanism for the short-horizon serial
correlation we measure, which is worth having beside the microstructure one.

---

## 10. A DNN surrogate for a multiphysics solver - the thinnest of the set

Rana, Islam, Surja, Ali, Mukherjee, Biswas, Neogi and Afikuzzaman, *Multiphysics
Modelling of Tri-Hybrid Nanofluid Transport over a Quadratically Radiative Riga
Surface*, Computation 14:248 (2026). `.secrets/computation-14-00248.pdf`.

Said plainly, because inflating it would be the error this file exists to
avoid: this is further from the problem than any of the others, and almost all
of it - Riga surfaces, electroosmotic forcing, Brownian thermophoresis,
nanoparticle volume fractions - transfers not at all. The structure is: solve
the coupled PDEs with a finite-difference method in FORTRAN, use that solver to
generate a training set, fit a feed-forward network to it, and report
`RMSE < 3.2e-2` with `R^2 > 0.987`.

Two things are worth keeping, and the second is a warning rather than a method.

* **A generator whose ground truth you control is a validation instrument.**
  The surrogate is trainable *and checkable* only because the solver can
  produce as much labelled data as wanted with the answer known. This package
  has the same instrument and has used it for one thing: `paths.simulate`
  generates a path with the latent truth attached, and `diagnostics.fit_jerk`
  recovers parameters from it. Nothing else uses it. The obvious extension is
  `ranking.py`: train and score it on **simulated** series where the true
  conditional magnitude is known, which separates "the model cannot find the
  ordering" from "the market has no ordering to find". Right now those two are
  confounded in every result in `statespace-rank-then-map.md`, and the second
  is the interesting one.

* **It validates only in-distribution, and that is the shape to recognise.**
  Every figure overlays DNN predictions on the numerical curves the DNN was
  trained against, and the residual histograms are centred at `1e-4` with
  standard deviations to match. None of it is held out in *parameter* space.
  Fluids 11:251 - the other surrogate paper in this file - makes a point of
  reporting interpolation and extrapolation separately, and that contrast is
  the lesson: a surrogate's accuracy on its own training distribution is close
  to uninformative, and uniformly excellent residuals are bug shape #10 in the
  `finding-bugs` skill rather than a result.

The second point generalises to this desk directly. A member fitted and scored
on one stretch of one instrument is a surrogate validated in-distribution, and
the leave-one-instrument-out design in `rank_then_map.py` exists precisely
because that is not enough.


---

## 11. Echo state networks *are* state-space models

Singh and Raman, *Echo State Networks as State-Space Models: A Systems
Perspective*, arXiv:2509.04422. The most directly on-topic of the eleven, and
it validates a diagnostic built here the same day.

**It says the thing `spectrum.py` does is the right thing to do.** The paper's
central move is *small-signal linearization*: take a nonlinear reservoir,
linearise it, and read the resulting LTI system's **poles and memory
horizons**. That is exactly what `spectrum.py` computes - eigenvalues of `F`
converted to half-lives in hours - and the paper's argument is that this is how
you understand a nonlinear state-space model rather than an optional extra.

It also says what to do about `selective.py`, which is nonlinear through its
softplus and reports `eigenvalues()` as a *design constant*, `-(n+1)`. Those
are the poles of the model as written; the poles that matter are the ones after
the input-dependent `delta` has scaled them, and getting at those is a
linearisation around the operating point. Measured today, `selective`'s
realised half-lives at a one-hour step are **0.69h, 0.35h, 0.23h, 0.17h** -
every mode under forty minutes - which says structurally that it cannot
represent a daily horizon however it is fitted. That is a stronger statement
than a disappointing likelihood and it needed no data.

Four more things transfer:

* **The echo-state property is input-to-state stability**, checkable from the
  leak rate, the spectral scaling and the activation's Lipschitz constant.
  `spectrum.stability` checks the linear members mechanically; the nonlinear
  ones need this version, and `selective` currently has no stability argument
  at all beyond the sign of its eigenvalues.
* **A lifted/Koopman random-feature expansion rewrites a nonlinear SSM as a
  linear one in an augmented state**, which buys transfer-function and
  convolutional-kernel analysis - and with it, *when a reservoir can emulate a
  structured SSM kernel*. That is the question `fractional.py` raises from the
  other side: a sum of exponentials is a structured kernel, and whether
  `selective` can already emulate it is answerable rather than arguable.
* **EM for the hyperparameters** - leak rate, spectral radius, process and
  measurement noise - which is the README's item 3 confirmed from outside, and
  `diagnostics.fit_both` is the coordinate-ascent stand-in until the smoother
  carries lag-one covariances.
* **A hybrid subspace procedure that shapes the spectrum under contraction
  constraints.** `fractional.py` chooses geometric half-lives by hand; this
  says spectrum shaping is a design step with a stability side-condition, and
  gives the form of the condition.

**And the member it suggests.** An echo state network is a fixed random
recurrent state with a *trained linear readout* - no fitting of the state
dynamics at all. That is unusually well suited to this package's discipline,
because the expensive half is fixed by construction and only the cheap half is
learned. Its null is `linear` and `fractional` on held-out likelihood, and its
spectrum is checkable before it is fitted.

---

## 12. A physical echo state network, and what two ESN papers in a row mean

*Physical echo state network based on the nonlinearity and dynamic response of
ambipolar heterostructure transistors*, Nature Communications 17:3321 (2026),
`s41467-026-70171-2`. A hardware paper: the reservoir is built out of ambipolar
organic-inorganic heterostructure transistors, whose saturation region supplies
a tanh-like nonlinearity and whose dynamic response supplies the memory.

Most of it does not transfer - this desk is not fabricating transistors - and
saying so is the point of reading it. Three things do.

* **Arriving second, it sharpens what the first one means.** arXiv:2509.04422
  says an echo state network *is* a state-space model; this one says the state
  dynamics can be an arbitrary physical process nobody designed, as long as its
  spectrum is characterised. Together they describe a member whose dynamics are
  **fixed and uncharacterised by choice** and whose only learned part is a
  linear readout - which suits this package's discipline unusually well,
  because the expensive half is not fitted and `spectrum.py` can characterise
  it before a single reading.
* **The nonlinearity and the memory are separable ingredients.** Theirs come
  from two different device properties - the saturation curve and the transient
  response - and that decomposition maps straight onto `selective.py`, which
  has a softplus for one and a retention for the other. It says the two can be
  measured and designed independently rather than tuned together, which is what
  `selective`'s grid search currently does.
* **They distinguish tasks that need the memory from tasks that do not** -
  reporting what the device achieves *without* its dynamic mechanisms. That is
  a null in hardware clothing, and it is the one this package would need before
  building any reservoir member: **a memoryless nonlinear readout on the same
  features**. If that matches, the recurrence bought nothing, and the finding
  is about the features rather than the model - which is exactly the argument
  `structures/learning/baseline.py` makes about the kNN.

So: no new mechanism, one corroboration, and a null specified before the member
it would test. Written down because an idea with its null attached is worth
more than a mechanism without one, and because two independent arrivals at the
reservoir idea in one week is the kind of coincidence worth recording rather
than acting on.

---

## 13. Three in-house idea sets, and what survives contact with this package

Reviewed 2026-10-11 from internal research material held elsewhere in the
workspace. Summarised rather than cited, and every item is stated with the
null it would need here - which is the thing most of them lack, several of
them say so, and that honesty is why they are worth reading.

### Liquidity as a switching state, not a level

One set models liquidity as cycling through named regimes - thin, building,
deep, **draining** - and argues the transition into draining precedes price
moves, with the *side* that drains revealing direction.

What transfers is the shape rather than the claim: that is a **switching
state-space model whose observed quantity is depth rather than price**, and
`switching.py` is now the machinery for it. Two regimes already work; four is
the same interacting-multiple-model recursion with a wider transition matrix.
The signed version - bid-side versus ask-side withdrawal - is a second state
rather than a second model.

**The null is awkward and must be named first.** Depth withdrawal and
volatility rise together, so "draining predicts a move" has to beat a trailing
standard deviation before it means anything, exactly as every magnitude claim
here does. And this desk has no order-book depth on most feeds - the FX
"volume" is a tick count - so the measurement is available on crypto and
nowhere else.

### Repricing latency is a transport delay, and `B u` can carry one

Another argues that thin markets reprice **5 to 60 minutes** after an event
that logically affects them, and that the delay is tradeable.

The transferable part is that a repricing lag is a **transport delay in the
state equation**: `x' = F x + B u(t - tau)`, with `tau` a duration. `linear`
now takes `control`, so the only missing piece is the delay, and it is one
parameter - fittable by the same likelihood search as everything else, which
makes `tau` a *measurement* rather than an assertion.

This desk has the adjacent number already: volatility runs **2.42x** on a
scheduled print and **0.79x** in the two hours before. That is the response,
not the latency, and the latency is what a delayed `B u` would estimate.

### The physics material: two strong results and one caution

A third set applies physical models to fill dynamics. Two of its results are
strong enough to be worth importing as *questions*:

* **A path-integral action ranks fills at Spearman 0.94**, which is a very
  high rank correlation for anything in this domain and far above anything
  measured here. The quantity is a kinetic action accumulated along the price
  path - and `facts.py` now computes path-like statistics, so the ingredient
  exists.
* **A Hawkes fit gives a branching ratio of 0.944**, near-critical, with a
  92x fill rate in the top intensity decile. Self-excitation at that level is
  the same long-memory phenomenon Lillo describes, approached from the event
  side, and it is the strongest argument yet for the long-memory kernel
  `fractional.py` only half-implements.

The caution is in the same material and is the reason to read it carefully: a
quantum-tunnelling model came out **inverted** (`r = -0.247`), a symmetry-
breaking breakout test came out at **51.2% continuation, exactly random**, and
the authors say so. A set of physics analogies produces some strong results and
some null ones, and the discipline that separates them is the one this package
already applies.

**The null for any of them here is the same**: a Hawkes intensity must beat a
trailing standard deviation at forecasting magnitude, and a path action must
beat it at the same job, because that is the null nothing in this repository
has beaten.

### The pattern catalogues, and the strategy repository

Two of the named sources are a general technical-analysis text and a
chart-pattern encyclopedia, and one is a large open-source trading repository
with a very large number of hand-written entry conditions. **I have not read
the books here**, and saying so matters more than a plausible summary would.

What transfers without reading them is methodological, and it is a warning
rather than an idea. A catalogue of patterns is a catalogue of *hypotheses*
with published hit rates, and the hit rates are almost never quoted against a
**base rate** - which is the control that has already killed the strongest
pattern claim this desk tested, "price is drawn to a level": reached 44.9% of
the time against **49.5%** for an arbitrary price the same distance away. A
pattern with a 65% continuation rate in a market that continues 63% of the
time is a pattern with nothing in it.

The same applies with more force to a strategy repository whose entry logic is
hundreds of conjoined conditions. That is a very large search over a fixed
history, and the honest way to borrow from it is to take **one** condition, ask
what state-space quantity it is a proxy for, and measure that quantity against
its own control. Taking the conjunction would be importing the search.

**So nothing from these three goes in as a feature.** What goes in is the
question they each pose, with the control attached, and the controls are the
same three this package already uses.
