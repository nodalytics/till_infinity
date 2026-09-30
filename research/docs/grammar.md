# A market language: symbols, grammar, inheritance, and whether any of it warns of anything

Harness: [`research/harness/grammar.py`](../harness/grammar.py). Lab run 2026-09-30. Logs:
`logs/grammar_{fx,metals,crypto,deriv,walks}.log`.

## The question

The user's top-ranked idea from the cross-disciplinary agenda: **OHLC → a symbolic market language →
its grammar → a structural state → regime transitions**, with two companions:
- **stratigraphy:** do identical patterns behave differently depending on the layers beneath them?
- **inheritance:** do structural traits propagate forward?

The user's question, put plainly: *what is the smallest language that describes market behaviour, and
does its grammar carry economic consequences?*

[`findings.md`](findings.md) sets the aim. The desk forecasts risk and has never forecast direction,
so the consequences tested are shocks and volatility-regime transitions, beyond the production shock
forecaster. Direction is checked for completeness.

This is not a rerun of the retrieval and sequence-model studies ([`state-and-memory.md`](state-and-memory.md),
the fractal-twins and hybrid-sequence work, all coin flips for direction). The new part is
formal-language structure: alphabets chosen by description length, grammar measured as
compressibility and Markov order, both against walks we generate.

## Method

- **Data:** 15m bars from 2024-06, 49,800 per series.
  - FX: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY.
  - Metals: XAUUSD, XAGUSD.
  - Crypto: BTCUSD, ETHUSD.
  - Deriv, as a market: Volatility 75, Boom 1000, Jump 50, Step.
  - Walks we generate, 59,800 bars each: three iid t(3) series, which have no structure at all, and
    three GARCH(1,1) series, which have volatility clustering and nothing else. GARCH is the bar a
    grammar has to clear, because clustering alone makes "compression → expansion".
- **Split:** fitted on each series' first 60% by time, scored on the last 40%, both halves reported,
  day-bootstrap intervals.
- **Two alphabets:**
  - **Hand-built,** 12 symbols (11 ever used), from production's structural vocabulary as bar-level
    definitions: a sweep up or down (wick through the 20-bar high or low, close back), a break (close
    through it), displacement (|r| > 2 vol, body over 60% of range), compression (true-range percentile
    < 0.2), expansion (> 0.8), and small up or down otherwise. The production Engine replay was too
    slow to symbolise every bar of 20 series, so these are the same quantities production reads,
    computed directly.
  - **Learned:** a Gaussian mixture on each bar's shape in volatility units (return, log range, body,
    both wicks), with the number of symbols chosen by BIC, the minimum-description-length criterion
    for a mixture.
- **Grammar,** on the test block:
  - Markov log-loss at orders 0-6, with the gain being order 0's log-loss minus the best order's, in
    bits per symbol;
  - LZ78 phrase count and Re-Pair grammar size, each as a share of a frequency-preserving shuffle's.
- **Inheritance:** the next bar's |r| quintile by gradient boosting, from shallow features (this
  symbol, the last one, the volatility state) against shallow plus deep layers (symbol counts over 20
  and 100 bars, bars since the last big move, position in and width of the 100-bar range).
- **Consequences:**
  - the production shock label and features (`models/shocks_train.dataset`, through the production
    `Shocks` class), with and without motif features. The motifs are the 30 most frequent hand
    3-grams, the 30 most frequent learned 3-grams, and the order-3 surprise;
  - the same for a volatility-regime transition (low state → high within 20 bars);
  - direction over the next 5 bars from the motifs alone;
  - each hand motif's shock rate against the base rate, with BH and the expected maximum of 180 null
    trials (2.73, [`lopez-de-prado.md`](lopez-de-prado.md)).

Pre-registered pass bars:
- grammar beats GARCH walks, with the interval clear;
- inheritance's out-of-sample gain beats the walks';
- motifs add ≥ 0.01 AUC over the shock features, in both halves, surviving deflation.

## Results

### 1. The alphabet: there is no small one

| | learned alphabet (BIC) | I(symbol; next \|r\| quintile), bits (of 2.32) |
|---|---|---|
| walks | 32, at the grid's ceiling | hand 0.0018 · learned 0.0049 |
| FX | 32, at the ceiling | hand 0.0212 · learned 0.0257 |
| metals | 32, at the ceiling | hand 0.0196 · learned 0.0249 |
| crypto | 32, at the ceiling | hand 0.0144 · learned 0.0177 |
| Deriv | 32, at the ceiling | hand 0.0223 · learned 0.0211 (0.001-0.085 by index) |

BIC fell monotonically through k = 3, 4, 6, 8, 12, 16, 24 and 32 in every family, walks included.
Description length keeps asking for more symbols, so bar shape is a continuum without natural
clusters. Any finite alphabet is a quantisation of it, not a discovered vocabulary.

What the symbols know about the next bar's size is about 1% of its uncertainty on real markets, and
about a fifth to a quarter of a percent on walks.

### 2. Grammar: order 1 on bar shape, and it is volatility

**Learned alphabet.** Gain of the best Markov order over order 0, in bits per symbol:

| series | best order | gain [95%] | LZ78 / shuffle | Re-Pair / shuffle |
|---|---|---|---|---|
| walks, iid and GARCH (6) | 0 | +0.0000 in every series | 0.998-1.000 | 0.994-1.004 |
| EURUSD | 1 | +0.0594 [+0.0493, +0.0682] | 0.992 | 0.989 |
| GBPUSD | 1 | +0.0641 [+0.0551, +0.0734] | 0.990 | 0.991 |
| USDJPY | 1 | +0.0461 [+0.0374, +0.0573] | 0.995 | 0.987 |
| AUDUSD / USDCAD / EURJPY | 1 | +0.047 / +0.048 / +0.048, all clear of 0 | 0.993-0.994 | 0.992-0.999 |
| XAUUSD / XAGUSD | 1 | +0.0512 / +0.0620, clear of 0 | 0.991-0.994 | 0.985-0.988 |
| BTCUSD / ETHUSD | 1 | +0.0396 / +0.0444, clear of 0 | 0.993 | 0.986-0.987 |
| Deriv Volatility 75, Jump 50, Step | 0 | +0.0000 | 0.999-1.001 | 1.000-1.006 |
| Deriv Boom 1000 | 1 | +0.0812 [+0.0738, +0.0904] | 0.975 | 0.970 |

Real markets' bar shapes carry order-1 structure that no walk has, not even GARCH, whose symbols are
volatility-normalised. It is 0.04-0.06 bits of about 4.9: roughly 1% of the per-symbol entropy.
Longer contexts never help, since the best order is always 1.

The Deriv rows validate the harness. Volatility 75, Jump 50 and Step are published as memoryless
([`deriv-variants.md`](deriv-variants.md)) and read exactly 0. Boom, whose spikes and inter-spike drift
are a mechanism, does not.

**Hand alphabet: mechanical, not evidence.** Every series, the walks included, shows a large order-2
gain: iid +0.276-0.284, GARCH +0.307-0.309, FX +0.305-0.369, metals +0.33, crypto +0.21-0.24, Deriv
+0.39-0.59. The hand symbols are defined on overlapping windows (the 20-bar high and low, a rolling
true-range rank), so neighbouring symbols share state by construction.

Three FX pairs clear the GARCH walks' intervals: EURUSD, GBPUSD, USDCAD. But **Deriv's Volatility 75,
a memoryless constant-σ process, scores +0.40, above every GARCH walk.** Its symbols' mechanics depend
on the return distribution's shape, which differs between the t(4) walks and each market. So the
hand-alphabet gain measures the definitions, not the market, and it is not counted.

### 3. Stratigraphy and inheritance: a trace on FX, nothing clean elsewhere

Next-bar |r| quintile, log-loss gain of the deep layers over the shallow ones, in bits per bar:

| | gain [95%] | halves |
|---|---|---|
| walks | +0.0003 [−0.0001, +0.0006] | +0.0001 / +0.0005 |
| FX | **+0.0019 [+0.0012, +0.0028]** | +0.0008 / +0.0030 |
| metals | +0.0012 [−0.0006, +0.0028] | +0.0043 / −0.0019 |
| crypto | +0.0001 [−0.0017, +0.0022] | −0.0006 / +0.0008 |
| Deriv | +0.0243 [+0.0223, +0.0262] | +0.0249 / +0.0238 |

- **FX** clears the walks, but the gain is 0.002 bits on a log-loss of 2.29, under 0.1%.
- **Metals and crypto** span zero.
- **Deriv's large gain is almost certainly instrument identification, not stratigraphy.** The four
  indices are pooled, and their |r| distributions in volatility units differ sharply (Step is
  discrete, Boom spikes). The deep features include 100-bar symbol counts, which fingerprint *which*
  index a row comes from; the shallow model has no instrument identity.

### 4. Consequences: nothing the shock forecaster does not already know

AUC with the production shock features, then with the motifs added:

| | shock within 4 bars | gain [95%] | halves | vol regime low → high within 20 | direction, 5 bars, motifs alone |
|---|---|---|---|---|---|
| walks | 0.6463 → 0.6483 | +0.0020 [−0.0002, +0.0043] | +0.0005 / +0.0035 | +0.0012 [+0.0000, +0.0025] | 0.5007 |
| FX | 0.7878 → 0.7919 | +0.0041 [+0.0023, +0.0062] | +0.0044 / +0.0037 | +0.0005 [−0.0008, +0.0018] | 0.5091 |
| metals | 0.7698 → 0.7782 | +0.0083 [+0.0038, +0.0130] | +0.0095 / +0.0070 | +0.0008 [−0.0011, +0.0026] | 0.5010 |
| crypto | 0.7652 → 0.7672 | +0.0020 [−0.0009, +0.0051] | +0.0001 / +0.0038 | +0.0004 [−0.0022, +0.0026] | 0.5105 |
| Deriv | 0.6782 → 0.6794 | +0.0012 [−0.0030, +0.0046] | −0.0015 / +0.0034 | +0.0026 [−0.0013, +0.0046] | 0.5057 |

No family reaches the 0.01 bar. Metals' +0.0083 comes closest. Regime transitions gain nothing
anywhere.

The direction AUCs are 0.50-0.51. FX's 0.509 and crypto's 0.511 carry no interval here and were not
charged costs. FX 15m short-term reversal is already known not to pay
([`indicators.md`](indicators.md), [`calendar-returns.md`](calendar-returns.md)). They are not pursued.

**The one strong univariate motif is compression, and it points the other way from the folklore.**
Three compressed bars in a row (C > C > C) are followed by *fewer* shocks:

| | shock rate after C>C>C | base rate | z | hand motifs passing BH | max \|z\| vs E[max] 2.73 |
|---|---|---|---|---|---|
| FX | 0.025 (n 4,036) | 0.066 | 10.30 | 26 of 30 | 10.30 |
| metals | 0.031 (n 1,208) | 0.075 | 5.81 | 16 of 30 | 5.81 |
| crypto | 0.029 (n 869) | 0.086 | 5.95 | 18 of 30 | 5.95 |
| Deriv | - | 0.020 | - | 0 of 30 | 2.50 |
| walks | (d>d>C) 0.058 | 0.080 | 3.37 | 4 of 30 | 3.37 |

- It clears deflation by a wide margin, and every top motif is compression-led.
- But the walks show the same direction (4 motifs pass BH on noise).
- Added to the shock forecaster it is worth +0.004 AUC on FX: it is the volatility state the
  forecaster already reads.

## What this means

- **The smallest language is not a small one.** Description length finds no natural alphabet: bar
  shape is a continuum. The one piece of structure that repeats is how big bars are, which is
  volatility state (compressed, normal, expanded). Production already tracks that directly, as the
  unit, the envelope, the true-range percentile and the vol clock.
- **There is a grammar, and it is order 1 and about size.**
  - Real markets' bar shapes depend on the previous bar by 0.04-0.06 bits per symbol, which no
    memoryless or GARCH walk reproduces, and which Deriv's memoryless indices correctly lack.
  - Longer "sentences" add nothing, and neither do deeper layers (FX's inheritance is under 0.1% of
    the log-loss).
  - The information is about the next bar's size, not its direction.
  - **One limitation:** the GARCH control has no intraday clock. Part or all of the order-1 excess
    on FX, metals and crypto may be the weekday × hour volatility profile
    ([`calendar-returns.md`](calendar-returns.md)) that a trailing volatility unit lags. Separating
    the two needs a clock-matched walk, which this run did not have.
- **Its economic consequences are already priced into the risk model.** Motifs add at most +0.008
  AUC to the shock forecaster (the bar was 0.01), nothing to regime transitions, and nothing to
  direction. The hand vocabulary's apparent grammar is an artefact of overlapping-window definitions,
  shown by a memoryless Deriv index scoring higher than the GARCH walks.
- **Verdict against the pass bars:**
  - **grammar beyond walks:** passes on the learned alphabet (clean, and validated by Deriv's
    memoryless indices), fails on the hand one (mechanical);
  - **inheritance:** a trace on FX only (+0.002 bits);
  - **motifs → transitions:** fails in every family.

  Nothing goes to production. It agrees with [`findings.md`](findings.md): the structure markets
  carry is volatility, and the production stack already has it.
