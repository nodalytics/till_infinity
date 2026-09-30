# Market topology and complex-systems early warning: nothing beyond what the shock forecaster knows

Harness: [`research/harness/topology.py`](../harness/topology.py). Lab run 2026-09-30, logs
`logs/topology_{real,walks,report}.log`, cells in `data/topology/cells.csv`.

## The question

[`findings.md`](findings.md): this desk forecasts risk, not direction. The user's cross-disciplinary
agenda proposed tools from topological data analysis, complex systems and statistical physics for
exactly that, as early warnings of regime transitions. Do they warn of a transition *before* it
comes, *beyond* what the production shock forecaster already reads? That forecaster uses
volatility state, clustering and the clock (AUC 0.73-0.76, [`anomalies.md`](anomalies.md)). And the
user's "killer question": are regimes told apart by topology when the conventional moments look the
same?

Related work not repeated here: [`susceptibility.md`](susceptibility.md) (the Ising susceptibility
of the efficiency ratio), [`manifold.md`](manifold.md) and [`state-and-memory.md`](state-and-memory.md).

## Method

Every statistic is computed causally, at every 4th bar at 15m, 2nd at 1h and every bar at 1d. It
uses the last 50 returns in units of the trailing 500-bar mean |return| (`z`):

| group | statistics | source |
|---|---|---|
| `tda` | persistent homology of the Takens delay embedding of z (dimension 3, delay 1): Vietoris-Rips H0 and H1 by ripser; persistence-landscape L1 and L2 norms, exact from the lifetimes (summed over layers, L1 = Σl²/4, L2² = Σl³/12); the count of H1 features living > 0.5 | Gidea & Katz 2018 |
| `tda_shape` | the same on the window standardised by its own sd (volatility level removed) | |
| `csd` | lag-1 autocorrelation of z and of \|z\|, variance, and Kendall's τ of variance over five 20-bar blocks | Scheffer et al. 2009 |
| `phys` | Hill tail exponent (250 bars, top 25), sample entropy at scales 1 and 2 (m = 2, r = 0.2 sd, 100 bars), Rosenstein largest Lyapunov exponent | |

- **Baseline:** the production shock forecaster's features computed from bars (volatility over its
  norm and its square, rank and its square, vol-of-vol, recent shock counts, hour, hours to the
  weekly close).
- **Targets, pre-registered:**
  - a shock (|r| > 4× the trailing mean) within 4 bars;
  - a range blowout (4×) within 4 bars;
  - a volatility-regime shift, meaning the next 20 bars' sd is at least 2× the last 100 bars'.

  The last is a defined proxy for a Markov-switching or Bai-Perron break, which would need the
  future to place.
- **Fit and score:** gradient boosting on the baseline against baseline + each group; train on the
  first 60% by time, test on the last 40%. The incremental AUC gets a paired day-bootstrap 95% CI
  and is reported for each half.
- **Families:**
  - FX (8 pairs), metals, crypto;
  - Deriv as a market (Volatility 75, Boom 1000, Crash 1000, Jump 50, Range Break 100);
  - walks we generate: iid t(3), and **GARCH(1,1) with t innovations**. GARCH has volatility
    clustering and nothing else, so it is the key control.

  Intervals 15m, 1h and 1d; about 1.35 million rows.
- **Pass bar:** incremental AUC ≥ 0.01, CI above 0, positive in both halves, and not on the GARCH
  walks. BH across all 250 cells, and the best cell deflated against the expected maximum of 250
  null draws ([`lopez-de-prado.md`](lopez-de-prado.md)).

## Results

**The baseline is strong on real markets and on GARCH walks, and weak on iid walks:**

| target, baseline AUC | FX 15m | FX 1h | metals 1h | crypto 1h | Deriv 15m | GARCH walks 1h | iid walks 1h |
|---|---|---|---|---|---|---|---|
| shock | 0.796 | 0.756 | 0.773 | 0.766 | 0.779 | 0.666 | 0.496 |
| range | 0.780 | 0.785 | 0.811 | 0.802 | 0.817 | 0.706 | 0.527 |
| vol shift | 0.766 | 0.641 | 0.705 | 0.662 | 0.821 | 0.627 | 0.484 |

**The borrowed tools add almost nothing to it.** Of 250 incremental cells, 4 pass the pre-registered
bar and 3 survive BH. None is on the GARCH walks.

| cell | + group | incremental AUC [95%] | halves | GARCH walks, same cell |
|---|---|---|---|---|
| metals 1d vol shift | phys | +0.032 [+0.015, +0.048] | +0.080 / +0.028 | +0.008 |
| metals 1d vol shift | tda | +0.025 [+0.005, +0.045] | +0.129 / +0.002 | −0.019 |
| Deriv 15m range | phys | +0.010 [+0.005, +0.017] | +0.012 / +0.009 | −0.000 |
| FX 1h vol shift | tda | +0.012 [+0.001, +0.025] | (passes, not BH) | +0.003 |

Everywhere else the increments sit within ±0.005, and are often negative. For example, FX 15m
shocks: tda −0.0001, csd −0.0012, phys −0.0016, all −0.0022. The median `tda` increment by family is
−0.002 to +0.002.

**Deflation.** The best real cell (metals 1d vol shift, `phys`) has t = 3.35 against an expected
maximum of 2.84 over 250 null cells. It survives nominally, but it is fragile:
- the second half is a third of the first (+0.080 / +0.028);
- the "all" group, which contains the same statistics, reads −0.003;
- it rests on 2 instruments' daily bars, 3,262 test rows and about 150 events.

The FX 1h cell does not survive BH.

**Deriv 15m range blowouts** is the one clean survivor: +0.010 in both halves and nothing on GARCH.
The single statistics say what it is. Low sample entropy (AUC 0.266) and a low Hill exponent (0.286)
come before range blowouts, meaning the window is step-like and fat-tailed. That reads as the
mechanics of the Range Break and Boom/Crash indices, which follow their own generators
([`deriv-variants.md`](deriv-variants.md)). It is a finding about those instruments, not a general
early warning.

### The killer question: topology beyond matched moments

Against a baseline of the window's *moments* only (sd, skew and kurtosis of z, plus their tercile
cells), adding the volatility-free topology (`tda_shape`) does help:

| family | shock | range |
|---|---|---|
| FX 15m | +0.006 [+0.001, +0.011] | **+0.021 [+0.005, +0.036]** |
| crypto 15m | +0.012 [+0.006, +0.020] | **+0.028 [+0.017, +0.042]** |
| metals 15m | +0.015 [+0.001, +0.029] | +0.010 [−0.015, +0.035] |
| **GARCH walks 15m** | **+0.015 [+0.006, +0.023]** | +0.009 [−0.001, +0.019] |
| **GARCH walks 1h** | **+0.013 [+0.006, +0.019]** | **+0.017 [+0.004, +0.030]** |
| iid walks 1h | +0.003 [−0.011, +0.018] | −0.005 [−0.027, +0.018] |

So yes: regimes with matched moments *are* told apart by the shape of the delay embedding. But the
GARCH walks show the same gain, and they have nothing but volatility clustering. What topology sees
beyond static moments is **the dynamics of clustering**, the ordering that moments throw away. The
production forecaster already reads that through its volatility-state and shock-history features,
which is why topology adds nothing once they are in the baseline.

## What this means

- **None of these tools is an early warning beyond what the desk already has.** Persistent
  homology, critical slowing down, tail exponents, entropy and Lyapunov estimates carry information
  about coming transitions: single-statistic AUCs reach 0.60-0.73. But that information is
  volatility clustering, which the production shock forecaster already reads.
- **The killer question has a precise answer.** Topology distinguishes regimes that moments cannot,
  because moments discard ordering. The same holds on GARCH walks, so the extra information is
  clustering dynamics, not a topological property of markets.
- **Critical slowing down does not appear.** Autocorrelation and variance trends add nothing (csd
  within ±0.004 in every real cell), consistent with markets not approaching bifurcations the way
  ecosystems do at these horizons.
- **Two narrow survivors, neither for production yet:**
  - Deriv 15m range blowouts (+0.010, instrument mechanics);
  - metals daily volatility shifts (+0.032, fragile: a small sample, a weak second half, and absent
    when all tools are added).

  Either could be re-tested on a longer or fresh sample before being considered.
- **For the cross-disciplinary agenda:** tools that measure the *shape* or *complexity* of a price
  window are re-measuring volatility clustering on these markets. Borrowed methods are more likely
  to add something if they bring **new information** that the price series does not contain. On the
  agenda's list, that means information flow across assets (the network and transfer-entropy
  program), causal interventions, and real order-flow data (the VPIN study now running), rather
  than another transform of the same bars.
