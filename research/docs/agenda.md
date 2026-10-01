# Research agenda: borrowing methods from other sciences

The desk's cross-disciplinary research agenda, set on 2026-09-30 and extended on 2026-10-01, and
where each item stands.
[`findings.md`](findings.md) has the results so far. This page is the map of what to do next and why.

## The strategy

> Borrow a mature methodology from another scientific field, identify a financial problem whose
> structure resembles that field, then test whether the borrowed machinery reveals something
> conventional quant methods miss. Borrow the **problem formulation**, not merely another
> algorithm.

Stop asking "which model predicts price better?" and start asking "what kind of system is a
financial market?"

**What our results add to that strategy.** Everything that has survived our controls and
deflation predicts *how much* price moves, never *which way*: shocks, volatility, band touches, the
volatility clock ([`findings.md`](findings.md)). So each program below is aimed first at **regime
transitions, early warning and risk**, where the desk has shown skill, and must beat the production
shock forecaster or walks we generate, in both halves and after deflation. A borrowed method that
only re-describes volatility clustering will be caught by GARCH walks.

## The meta-framework

    Market state = Information + Topology + Dynamics + Adaptation

| Component | Borrowed from | Question |
|---|---|---|
| Information | information theory | What information is entering the system? |
| Topology | network science, topological data analysis | How are assets and participants connected, and what shape is the state? |
| Dynamics | complex systems, statistical physics | What state is the market in, and is it near a transition? |
| Adaptation | ecology, evolution, control theory | How do participants and strategies respond, and how should we? |

## Agenda 1: the scientific toolbox

| # | Field → idea | Core question | Status |
|---|---|---|---|
| 1 | Information theory → information geometry | How much *new* information does X add to the market's existing state, I(Y; X \| Z)? | **Done:** program B, [`infoflow.md`](infoflow.md). A reusable novelty test (`novelty()`); only bar range and tick volume are new information about the next bar's size |
| 2 | Complex systems → regime topology | Are there measurable precursors before orderly regimes turn unstable (critical slowing down, bifurcations)? | **Done:** program A, [`topology.md`](topology.md). Critical slowing down never appears; nothing adds to the shock forecaster |
| 3 | Neuroscience → attention and information processing | Do limited processing capacity and attention create predictable behaviour (news → attention → flow → price)? | Not started. Adjacent: [`surprise.md`](surprise.md) (priced within 3 minutes) |
| 4 | Ecology → financial ecosystems | Does profitability fall because a strategy stops working, or because its population grows too large? | **Done:** program C, [`ecology.md`](ecology.md). Null: no decay-and-recovery beyond walks (0/39), no density dependence (0/44); the one trace is crowded crypto funding |
| 5 | Evolutionary biology → adaptive strategies | What does strategy evolution under costs and crowding mean economically? | **Done** in program C: evolved rules' "alpha decay" is selection bias, exactly as on walks |
| 6 | Epidemiology → contagion and cascades | Does a contagion reproduction number R(t) above 1 precede liquidation cascades? | **Done** in program C: real self-excitation (branching 0.61), R(t) > 1 doubles cascade odds, but nothing added to the shock forecaster |
| 7 | Fluid dynamics → order-book flow | Do pressure, turbulence and diffusion analogues describe microstructure usefully? | Not started. Needs order-book data we do not hold. Prior: [`orderflow.md`](orderflow.md) (null) |
| 8 | Network science → dynamic topology | How does cross-asset topology reorganise during regime transitions? | **Done** in program B: markets share volatility, not direction; no network measure, absorption ratio included, adds to the shock forecaster |
| 9 | Control theory → closed-loop trading | Position sizing and exposure as feedback control of state → action → new state | Partly done: [`fund.md`](fund.md) (vol-managed control ties EWMA); the production risk gates are feedback controls |
| 10 | Robotics → POMDPs and belief states | Decide on an inferred belief P(S_t \| X_1:t) rather than a return forecast | Not started. Natural next step once a state model passes |
| 11 | Causal inference → mechanism | Does liquidity loss cause volatility? Does funding pressure cause dislocation? | **Done:** program D, [`causal.md`](causal.md). The spread is a symptom, not a cause (the rollover's mechanical 15x widening moves nothing); releases cause volatility spikes whatever the surprise; funding marks the regime without pushing price. Volume is the strongest upstream candidate |
| 12 | Linguistics → narrative structure | Does the structure and propagation speed of a narrative predict changes in market state? | Not started. Needs text data beyond the calendar |
| 13 | Information retrieval → market memory | Which past states resemble today's, and what followed? | Done for direction: [`state-and-memory.md`](state-and-memory.md), fractal twins (coin-flip). Not yet as a retrieval-based *regime* model |
| 14 | Topological data analysis → market shape | Are regimes distinguishable by topology when the moments look the same? | **Done:** program A - yes, but GARCH walks gain the same: it is clustering dynamics, which the forecaster already reads |
| 15 | Statistical physics → phase transitions | Do tail exponents, entropy and correlation change jointly around transitions? | **Done** in program A: add nothing beyond the shock forecaster, except Deriv mechanics |

The three priority programs named in the agenda map to what is running:
- **A (market state topology)** is [`topology.md`](topology.md);
- **B (information flow)** is [`infoflow.md`](infoflow.md);
- **C (adaptive market ecology)** is [`ecology.md`](ecology.md).

## Agenda 2: the stranger fields

| # | Field → idea | Core question | Status |
|---|---|---|---|
| 1 | Archaeology → market stratigraphy | Can the sequence of historical layers explain why identical patterns behave differently? | **Done** in program E, [`grammar.md`](grammar.md): deeper layers add 0.002 bits, on FX only |
| 2 | Forensics → event reconstruction | Which hidden event chain most plausibly produced what we observe? | Partly **running** in program D (causal discovery, clearly labelled exploratory) |
| 3 | Game design → mechanism design | How do tick size, funding, liquidation design and maker/taker pricing shape behaviour? | Partly done: [`game-theory.md`](game-theory.md), [`deriv-payouts.md`](deriv-payouts.md); the funding event study is in program D |
| 4 | Operations research → capital allocation | Allocate scarce capital across simultaneous opportunities under cost and liquidity constraints | Not started. Needs opportunities with an edge first ([`triage.md`](triage.md)) |
| 5 | Compiler theory → a market intermediate representation | Can price behaviour be written as a formal language (OHLC → IR → structure)? | **Done:** program E - no small alphabet exists (bar shape is a continuum) |
| 6 | Music theory → market motifs | Are there reusable temporal motifs (tension, resolution) that indicators miss? | **Done** in program E: motifs add +0.004-0.008 AUC to the shock forecaster, under the bar |
| 7 | Cryptography → commitment and revelation | How does incremental revelation of committed information drive price discovery? | Not started. Adjacent: [`surprise.md`](surprise.md) |
| 8 | Anthropology → market rituals | Does the market behave differently when participants collectively anticipate an institutional ritual? | **Done:** program F, [`rituals.md`](rituals.md). Rituals are loud on the day (FOMC, NFP, the month-end fix), barely anticipated, and carry no drift; the pre-FOMC drift is absent in USD, gold and BTC |
| 9 | Legal theory → rule changes | Do rule changes produce breaks that regime models mistake for behavioural regimes? | Not started. Adjacent: [`rollover.md`](rollover.md) (a broker mechanism mistaken for market behaviour) |
| 10 | Geography → landscapes and basins | Are some states basins of attraction? | Done as a state manifold: [`manifold.md`](manifold.md) |
| 11 | Genetics → structural inheritance | Do structural traits propagate through time? | **Done** in program E: an order-1 grammar about size, nothing deeper |
| 12 | Linguistics → market grammar | What production rules recur, and which transitions matter? | **Done:** program E - a one-bar grammar about size (+0.04-0.06 bits), no economic consequence beyond volatility |
| 13 | Astronomy → inverse inference | Can hidden events be reconstructed from their observable signatures? | Partly in program D. VPIN as a hidden-flow signature was null ([`vpin.md`](vpin.md)) |
| 14 | Paleontology → extinct regimes | What can dead market structures teach about today's? | Not started. Needs long, multi-era data |
| 15 | Immunology → self against non-self | Does an unusual state precede a structural transition? | Largely done: the shock forecaster and anomaly work ([`anomalies.md`](anomalies.md)) |
| - | Formal methods → verified trading systems | Under what conditions is the system guaranteed not to violate its invariants? | **Done:** program G, [`verification.md`](verification.md). All 19 invariants hold; the tests run in CI |

The agenda's top pick, OHLC → symbolic market language → grammar → structural state → regime
transition, is program E. It asks what the smallest language describing market behaviour is, which
grammatical structures recur, which transitions correspond to changes in state, and whether those
transitions have economic consequences.

## Agenda 3: the radical frontier (parked for later)

Set on 2026-10-01, to be researched later. These are fields whose basic objects, mathematics or
worldview are far from finance. The strategy is the same: borrow the **problem formulation**, not
an algorithm. Where earlier work already touches an item, it is noted.

| # | Field → idea | Core question | Related work here |
|---|---|---|---|
| 1 | Mycology → decentralised resource routing | Does liquidity reroute through venues like a fungal network after one is impaired (redundancy, path efficiency, damage and recovery)? | None. Needs multi-venue liquidity data |
| 2 | Architecture → markets as designed spaces | Are some states (price × liquidity × volatility) structurally easier for capital to move through? | None |
| 3 | Cartography → a market atlas | Can markets be represented as navigable state spaces rather than time series? | [`manifold.md`](manifold.md) (a state manifold) |
| 4 | Paleoclimatology → market climates | Reconstruct a multidimensional latent "liquidity climate" from proxies (spreads, volume, funding, OI, correlation), then study climate transitions | Partly: the shock forecaster's state; [`infoflow.md`](infoflow.md) |
| 5 | Seismology → financial seismology | Infer a shock's source, magnitude, propagation and aftershocks; the propagation medium is the object | [`infoflow.md`](infoflow.md) (volatility spills over, about 2x), [`ecology.md`](ecology.md) (Hawkes self-excitation, branching 0.61) |
| 6 | Volcanology → pressure accumulation | Is the market accumulating structural pressure before a threshold release? | [`topology.md`](topology.md) (critical slowing down never appeared), [`susceptibility.md`](susceptibility.md) |
| 7 | Materials science → market fatigue | Does cumulative stress predict instability better than instantaneous volatility? | None directly; testable against the shock forecaster |
| 8 | Fracture mechanics → liquidity cracks | Do micro-anomalies (spread, depth, basis, funding, cross-venue price) behave like microcracks before dislocations? | [`causal.md`](causal.md): the spread is a symptom, not a lever. Needs order-book data |
| 9 | Oceanography → capital currents | Estimate a capital-flow field (currents, eddies, convergence) across BTC → ETH → majors → small caps | [`infoflow.md`](infoflow.md) (no directional flow between assets) |
| 10 | Phonology → market phonemes | Can episodes be built hierarchically from structural primitives (phoneme → morpheme → word)? | [`grammar.md`](grammar.md): no small alphabet; a one-bar grammar about size |
| 11 | Gene regulation → strategy activation networks | Model strategies as conditionally activated and mutually regulating, not as correlated assets | [`ecology.md`](ecology.md) |
| 12 | Immunology → immune memory | Does a market remember shocks, and for how long: P(S_t+1 \| S_t, shock history) against P(S_t+1 \| S_t)? | Partly: shock clustering in the forecaster and in [`ecology.md`](ecology.md); memory *length* untested |
| 13 | Cognitive archaeology → collective beliefs | Reconstruct what the market collectively believed at t from its artefacts (options surfaces, curves, positioning) | Needs options and futures data |
| 14 | Incomplete-information games → belief wars | How fast do beliefs converge after information arrives, and when does disagreement itself create volatility? | [`surprise.md`](surprise.md) (priced within 3 minutes), [`rituals.md`](rituals.md) |
| 15 | Anthropology of time → market time | Replace clock time with market time, dτ = g(X_t)dt, for volatility, regimes, event studies and memory | Partly: the volume clock in [`vpin.md`](vpin.md); the weekday × hour clock in [`calendar-returns.md`](calendar-returns.md) |
| 16 | Thermodynamics of computation → the cost of information | What does it cost to turn information into a decision, and what is information efficiency per resource spent? | None |
| 17 | Evolutionary game theory → markets without rational agents | Strategy → environment → strategy feedback as a theory of adaptive markets | [`ecology.md`](ecology.md): no density dependence beyond walks |
| 18 | Information archaeology → forgotten alpha | Re-test old hypotheses with new data and methods: the fossil record of quant finance | [`chan.md`](chan.md), [`lopez-de-prado.md`](lopez-de-prado.md) |
| 19 | Cybernetics → reflexive markets | How does deploying a predictive signal change the signal's own statistics (the deeper reason alpha decays)? | [`ecology.md`](ecology.md): "alpha decay" of evolved rules was selection bias |
| 20 | Semiotics → prices as signs | Context-dependent price meaning: the same price is a breakout, a support or a liquidation threshold | Partly: the structures engine's levels and zones; [`focal-points.md`](focal-points.md) |
| - | **Metrology → the science of measuring financial concepts** | Is "liquidity" one variable or several? Are volatility, trend, regime and alpha well-defined measurements of latent structures? | See below: our own record argues for this first |

**The most promising chain, as the agenda framed it:**

    Market measurement -> representation -> grammar -> dynamics -> intervention

That is metrology, then compiler theory and linguistics, then cybernetics. The question underneath
it: *what if most of quantitative finance's objects are poorly defined measurements of deeper latent
structures?*

**Why metrology deserves to go first: our own record already supports it.** Several of this
program's largest "findings" turned out to be measurement problems, not market behaviour:

- the boosted envelope's gain was mostly correcting a noisy volatility unit; walks gained the same
  ([`gbm-envelope.md`](gbm-envelope.md));
- the rollover "market behaviour" in FX level statistics was a broker quote artefact
  ([`rollover.md`](rollover.md));
- crypto spreads were read 1,000x too wide from an inferred point size ([`vetoes.md`](vetoes.md));
- the levels' hold rate was the geometry of the label, the same on random walks
  ([`skill.md`](skill.md));
- the empirical envelope on Deriv's constant-volatility indices added error by measuring in a
  noisy live volatility estimate ([`deriv-variants.md`](deriv-variants.md)).

A first metrology program could ask, for volatility, liquidity and "regime": how many distinct
latent constructs does each name hide (factor analysis across competing measures)? How much
measurement error does each measure carry, judged against walks where the truth is known? Which
measures are stable across venues, timeframes and estimators?

## Agenda 4: another science's way of defining reality (parked for later)

Set on 2026-10-01, to be researched later. These fields deliberately avoid the ones above. Their
concerns are memory, emergence, measurement, spatial organisation, computation, perception,
uncertainty and hidden structure. The standard is stricter: **don't borrow another algorithm.
Borrow another science's way of defining reality.** The foreign field has to supply the problem's
mathematical ontology, not a new transform of the same bars.

| # | Field → idea | Core question | Related work here |
|---|---|---|---|
| 1 | Geology → layers, faults and tectonics | Can latent fault lines (liquidity discontinuities, crowded positioning, leverage concentration, correlated exposures, cross-venue fragmentation) be detected before a dislocation? | [`grammar.md`](grammar.md) (stratigraphy: deeper layers add 0.002 bits). Needs positioning data |
| 2 | Acoustics → market resonance | Which forcing frequencies (funding, expiries, rebalancing, sessions, macro calendar) does a market amplify or suppress, H(f) = response / forcing? | [`calendar-returns.md`](calendar-returns.md) (the weekday × hour volatility clock), [`rituals.md`](rituals.md) |
| 3 | Signal processing → blind source separation | Can movement be decomposed (ICA, NMF, sparse coding) into latent behavioural sources (macro, flow, leverage, information) rather than statistical factors? | None |
| 4 | Computer vision → shape without images | Treat [O,H,L,C,V] trajectories as objects: contours, segmentation, tracking, and an optical-flow field v(x,t) across market dimensions | [`grammar.md`](grammar.md) (bar shape is a continuum), [`patterns.md`](patterns.md) |
| 5 | Robotics SLAM → localisation and mapping | Infer P(state, map \| data) together: a system that builds its map of the market while navigating it, not a fixed model | Partly: online learners (AgACI, [`conformal.md`](conformal.md)); [`manifold.md`](manifold.md) |
| 6 | Astronomy → gravitational lensing | Infer hidden positioning from the distortions it leaves in prices, basis, the volatility surface, liquidity and cross-asset behaviour | [`positioning.md`](positioning.md), [`vpin.md`](vpin.md) (a hidden-flow signature, null). Needs derivatives data |
| 7 | Bayesian experimental design → active sensing | Which next observation most reduces uncertainty about the regime, IG(X) = H(H_i) − H(H_i \| X)? | None |
| 8 | Reliability engineering → alpha hazard | Treat a strategy as a component: its hazard h(t) and h(t \| crowding, volatility, regime, size) | [`ecology.md`](ecology.md) ("alpha decay" was selection bias), [`triage.md`](triage.md). Needs strategies with an edge to fail |
| 9 | Aerospace → fault-tolerant trading | Design for graceful degradation (primary + fallback + isolation + recovery) rather than nominal performance | Partly: [`verification.md`](verification.md) (19 invariants), the risk gates, the shadow gates |
| 10 | Distributed systems → consensus latency | After an information event, how long until venues converge on a new price, T_consensus? | [`surprise.md`](surprise.md) (priced within 3 minutes), [`infoflow.md`](infoflow.md), [`coinbase-premium.md`](coinbase-premium.md). Needs multi-venue ticks |
| 11 | Queueing theory → congestion markets | Is instability a congestion phenomenon, λ(t) > μ(t), with execution demand over capacity? | [`queueing.md`](queueing.md) (the desk's own strategy queue, not the market's). Needs order-book data |
| 12 | Manufacturing → statistical process control | Is the price-generating process still the same mechanism, θ1 → θ2, detected before a model notices its assumptions died? | Partly: [`structures-context-cusum.md`](structures-context-cusum.md), [`structures-learning-drift.md`](structures-learning-drift.md), the ZMA e-process ([`zma-conformal.md`](zma-conformal.md)) |
| 13 | Meteorology → nowcasting conditions | Predict the state Ŝ(t+Δ) (volatility, liquidity, correlation, spread, volume, breadth), not the price | Largely the desk's working direction: the shock forecaster, the envelope, the vol clock ([`findings.md`](findings.md)) |
| 14 | Bioinformatics → sequence alignment | Align episodes structurally (insertions, deletions, substitutions, speed changes), richer than dynamic time warping | [`fractal-twins.md`](fractal-twins.md) (twins time volatility, not direction), [`grammar.md`](grammar.md) |
| 15 | Error-correcting codes → noise-invariant structure | Find representations of market structure that survive realistic market noise | Ties to metrology (agenda 3) |
| 16 | Morphogenesis → how structure forms | Which local interactions (liquidity, flow, agent rules) generate trends, ranges and dislocations? Generative microstructure | [`ecology.md`](ecology.md) (evolved agents) |
| 17 | Crystallography → symmetry and its breaking | Do states show measurable symmetries T(X) ≈ X (time, scale, repetition), and does symmetry breaking mark a regime change? | None |
| 18 | Archaeological dating → regime age | Does the chance of a transition depend on the regime's age, P(transition \| A_t)? | [`states.md`](states.md) (a level's behaviour over its life), [`structures-learning-decay.md`](structures-learning-decay.md) |
| 19 | Information retrieval → market analogues | Retrieve genuinely analogous historical states under a learned structural similarity metric | [`fractal-twins.md`](fractal-twins.md), [`similarity.md`](similarity.md), [`structures-vol-analogue.md`](structures-vol-analogue.md) |
| 20 | Philosophy of science → falsification engines | A system built to destroy each hypothesis: alternative definitions, costs, regime splits, placebos, feature destruction, delayed information, execution degradation | Largely how this program already works: walk controls, both halves, deflation ([`lopez-de-prado.md`](lopez-de-prado.md), [`controls.md`](controls.md)) |

**Five research universes, as the agenda grouped them:**

| Universe | Fields | Concerns |
|---|---|---|
| A: financial geophysics | Geology, seismology, volcanology, materials science, acoustics | Shocks, faults, stress, resonance, fractures |
| B: financial computation | Compiler theory, distributed systems, error-correcting codes, formal methods, information retrieval | Representation, state, consensus, noise correction, verification |
| C: financial morphology | Morphogenesis, crystallography, cartography, architecture, computer vision | Shape, symmetry, spatial structure, formation |
| D: financial epistemology | Philosophy of science, cognitive archaeology, semiotics, experimental design, metrology | What markets know, what we think they know, and whether we measure it correctly |
| E: financial reliability | Aerospace, manufacturing, reliability engineering, queueing theory, fault-tolerant computing | Degradation, failure, congestion, robustness, recovery |

**The idea circled in red: financial failure mechanics.** Materials science, reliability engineering,
seismology and microstructure combined. The market is a structure accumulating stress:

    Stress -> Damage -> Crack -> Fracture -> Cascade

with stress σ_t = f(leverage, liquidity, positioning, correlation), damage
D_t = ∫ g(σ_τ, conditions) dτ, and a dislocation when D_t > D_critical. Its concrete questions:

1. Can cumulative stress be estimated from OHLCV plus derivatives?
2. Does stress accumulate even while volatility falls?
3. Are there observable "microcracks" before major dislocations?
4. Does fatigue explain why identical shocks have different consequences?
5. Can the age and history of stress explain nonlinear responses?
6. Does one framework work across BTC, FX, equities and commodities?

**What we already know that bears on it:**

- A fatigue proxy has been measured once and had the **wrong sign**: susceptibility predicted
  volatility *falling* ([`susceptibility.md`](susceptibility.md)). Critical slowing down never
  appeared ([`topology.md`](topology.md)).
- The shock forecaster already carries instantaneous stress (recent volatility, range, volume). A
  damage integral D_t is only a finding if it adds to that, incrementally, on held-out data, and
  not on GARCH walks.
- σ_t as framed needs leverage and positioning, which OHLCV does not carry. An OHLCV-only first pass
  tests questions 2, 4 and 5. Questions 1 and 3 need derivatives or order-book data.

## Agenda 5: reconstruction, perception and representation (parked for later)

Set on 2026-10-01, to be researched later. This batch takes ideas from fields whose core problem
is reconstruction, perception, representation, failure or hidden-state inference. Most of them
recast the task as an **inverse problem**: infer the hidden state S_t from the observables X_t
(X_t → S_t), rather than forecasting the next return (X_t → r_t+1).

| # | Field → idea | Core question | Related work here |
|---|---|---|---|
| 1 | Medical imaging → financial tomography | Reconstruct latent positioning and state, Ŝ_t = T(X_t), from many indirect projections (price, volume, spreads, funding, OI, options, flow, cross-asset) | [`positioning.md`](positioning.md). Needs derivatives and flow data |
| 2 | Radar → markets seen through their echoes | Infer hidden liquidity, institutional execution, latent demand, liquidation pressure or market-maker withdrawal from how observables respond, r(t) = H(s(t), θ) + ε | [`vpin.md`](vpin.md) (a hidden-flow echo, null), [`orderflow.md`](orderflow.md) |
| 3 | Remote sensing → sensor disagreement | When price says calm, options say stress, funding says crowded and liquidity says fragile, does the **inconsistency** itself signal a regime transition? | [`agreeing.md`](agreeing.md) (one change point across timeframes), [`implied.md`](implied.md) |
| 4 | Inverse rendering → the invisible scene | What hidden configuration could have generated the observations we see? | Same inverse framing as 1 and 2 |
| 5 | Traffic engineering → financial traffic | Is instability sometimes congestion (demand over liquidity capacity, q_in > q_max) with stop-and-go waves and capacity collapse, rather than a volatility phenomenon? | Agenda 4 item 11 (queueing). Needs order-book data |
| 6 | Wildfire science → ignition | Not every spark becomes a fire: P(cascade \| state), with fuel (leverage, crowding), ignition, spread and barriers | [`crash-timing.md`](crash-timing.md) (a crash can be timed, not signed), the shock forecaster |
| 7 | Avalanche science → metastability | Can a stable market be told from a metastable one at the same volatility? | [`topology.md`](topology.md) (no critical slowing down), [`susceptibility.md`](susceptibility.md) |
| 8 | Hydrology → liquidity drainage | Does the liquidity reservoir drain, dL/dt = inflow − outflow, while price looks normal, and does depletion precede instability? | [`causal.md`](causal.md) (the spread is a symptom). Needs depth data |
| 9 | Plasma physics → collective fields | Model aggregate fields (position density, capital-flow velocity, a liquidity field) and their collective instabilities, not individual agents | [`ecology.md`](ecology.md), [`agents.md`](agents.md) |
| 10 | Cellular automata → minimal local rules | What minimal local rules generate trends, volatility clustering, bubbles, crashes and liquidity gaps? | Agenda 4 item 16 (morphogenesis); [`ecology.md`](ecology.md) |
| 11 | Percolation → liquidity connectivity | Is there a critical connectivity p_c below which arbitrage relationships across venues break down? | [`coinbase-premium.md`](coinbase-premium.md). Needs multi-venue data, crypto first |
| 12 | Category theory → compositional finance | Can strategies be written as composable maps (state → signal → decision → portfolio) with properties formally preserved under composition? | [`verification.md`](verification.md) (invariants on the pipeline) |
| 13 | Type theory → impossible trades | A type system for research: Price<5m> vs Price<1h>, Volatility<realised> vs <implied>, State<trend>, so invalid operations (mixed scales, future data, out-of-regime use, conditional-as-unconditional) fail before the backtest | Our own bugs argue for it: crypto spreads read 1,000x wide (a units error), the lost size brake, the rollover quote artefact ([`findings.md`](findings.md)) |
| 14 | Cryptanalysis → distinguishers | What statistical property distinguishes this process from the null, D(X) ∈ {structure, null-like}, before asking whether it predicts? | Largely our walk-control method ([`controls.md`](controls.md), [`null.md`](null.md)) |
| 15 | Algorithmic information theory → compressibility | Does the compressibility K(X_{t−k:t}) of the market change systematically before regime transitions, and does it track forecastability? | [`grammar.md`](grammar.md) (entropy of a bar alphabet) |
| 16 | Psychophysics → the just-noticeable difference | How large must a change be, θ = f(volatility, attention, context), before participants collectively react? | [`surprise.md`](surprise.md) (macro surprises priced within 3 minutes) |
| 17 | Gestalt psychology → market objects | Extract structural objects (compression, reversal, breakout) by figure-ground separation, continuity and closure, not indicators | [`grammar.md`](grammar.md), [`patterns.md`](patterns.md), the structures engine's levels and zones |
| 18 | Human factors → the human-model system | Does the operator, model and interface together decide well under uncertainty: alert overload, hidden uncertainty, inconsistent intervention? | The cards and notifications; [`agent-trading.md`](agent-trading.md) |
| 19 | Semiconductor fabrication → defect detection | Do tiny local defects (an abnormal spread, a broken correlation, stale liquidity, inconsistent pricing) predict large-scale deterioration? | [`anomalies.md`](anomalies.md) (anomaly work feeding the shock forecaster) |
| 20 | Film editing → event segmentation | Find natural boundaries between episodes, X_1:T → E_1…E_n, instead of fixed windows | [`structures-context-cusum.md`](structures-context-cusum.md), [`agreeing.md`](agreeing.md) |
| 21 | Dramaturgy → market tension | Does a latent tension T_t = f(positioning, disagreement, volatility, liquidity) accumulate before large structural events, beyond what volatility shows? | Overlaps agenda 4's failure mechanics |

**A unified failure model, the batch's synthesis.** Hydrology (accumulation and drainage),
materials science (damage and fatigue), avalanche science (threshold instability), traffic theory
(congestion) and radar or tomography (hidden-state inference) fit one chain:

    liquidity accumulates -> stress builds -> local defect appears -> threshold crossed -> cascade propagates

The target becomes P(structural failure | S_t), where S_t holds latent stress, connectivity,
liquidity, congestion, positioning and fragility, across BTC, equities, FX, commodities and rates.
It is agenda 4's financial failure mechanics, given a hidden-state front end.

**The representation architecture:** tomography + radar + type theory + cellular automata:

    observations -> latent state reconstruction -> formal state representation -> generative dynamics

Observe the market indirectly, reconstruct what is happening underneath, represent it formally,
then ask what local rules could have generated it.

**Notes for when this is picked up:**

- Most items need data the desk does not hold: order-book depth, derivatives (options, funding,
  open interest), positioning, multi-venue ticks. OHLCV plus tick volume can test items 6, 7, 10,
  14, 15, 16, 17, 20 and 21. Crypto venues are the cheapest source of the rest.
- Two items are method, not market, and can start without new data: **type theory** (item 13) and
  **distinguishers** (item 14). Type theory is the most direct follow-on to agenda 3's metrology:
  several of our worst errors were type errors.
- Every reconstruction claim needs a ground truth. Generate the hidden state ourselves (agents or
  automata with known positioning), check the reconstruction recovers it, then apply it to markets.
  Deriv's feeds are markets, not ground truth.

## How a program is judged

- Walk-forward by time, both halves, pre-registered pass bars.
- Walks we generate as controls: GARCH walks for anything that could be volatility clustering, iid
  walks for mechanics. Deriv is a market, never a control.
- An **incremental** test against what production already has (the shock forecaster, the volatility
  unit, the vol clock). A new lens that only rediscovers volatility is not a finding.
- Benjamini-Hochberg within a program, and deflation across the program
  ([`lopez-de-prado.md`](lopez-de-prado.md)). Count every motif, window and threshold as a trial.
- Costs on anything that trades.

## Sources cited in the agenda

- Big data in finance, *Review of Financial Studies* 34(7), and "Next Chapter of Big Data in Finance",
  *RFS* 38(3).
- "Information-Theoretic Asset Pricing Model", *Journal of Financial Econometrics* 23(1).
- "Graph-Based Methods for Forecasting Realized Covariances", *JFEC* 23(2).
- Gu, Kelly & Xiu, "Empirical Asset Pricing via Machine Learning", *RFS* 33(5).
- "Language Modeling for the Future of Finance", arXiv 2504.07274.
