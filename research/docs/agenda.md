# Research agenda: borrowing methods from other sciences

The desk's cross-disciplinary research agenda, set on 2026-09-30, and where each item stands.
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
| - | Formal methods → verified trading systems | Under what conditions is the system guaranteed not to violate its invariants? | **Running:** program G, [`verification.md`](verification.md) (property-based and stateful tests of the risk invariants) |

The agenda's top pick, OHLC → symbolic market language → grammar → structural state → regime
transition, is program E. It asks what the smallest language describing market behaviour is, which
grammatical structures recur, which transitions correspond to changes in state, and whether those
transitions have economic consequences.

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
