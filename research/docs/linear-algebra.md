# Eigenvalues, hidden states and the perceptron: three linear questions, three answers

Run: `python research/harness/eigen.py`, `research/harness/regimes.py`, `research/harness/perceptron.py`

**Measured 2026-09-23.** Three requests that turn out to be one subject - *"try eigen values and
vectors, try matrices and linear algebra"*, *"we should also have directional regimes, trend up,
trend down, ranging"* with *"use/test HMMs in decision making and state transitions"*, and
*"explore the concept of the perceptron, and see how far it takes us"*.

They meet because each one asks the same question about a different matrix: **how much of the
structure in this matrix is real?** For a correlation matrix the answer is an eigenvalue against a
noise floor. For a transition matrix it is a dwell time against a surrogate. For a weight vector it
is a margin. All three are computable, and all three came back.

| question | answer | where it binds |
| --- | --- | --- |
| how many factors does the book have? | **one, robustly; two given thousands of bars** | a rolling correlation matrix supports one |
| do hidden states exist? | **yes - they pass every surrogate test** | dwell 3.05-3.30 against 1.49-2.53 |
| do hidden states predict? | **no - direction and volatility both lose** | 0.491-0.498 AUC; QLIKE 3-72% worse than trailing |
| how far does a perceptron get? | **AUC 0.584 against the incumbent's 0.658** | the margin is **negative** |

## One: the book has one factor, and that is the whole cross-section

Seven instruments on 20,222 shared hourly bars. The eigenvalues of the correlation matrix are

    3.194   1.273   0.984   0.690   0.435   0.222   0.202

and the first carries **45.6% of total variance**. Its eigenvector is

    gbpusd -0.47   eurusd -0.47   usdcad +0.40

which is **not a generic "market mode" - it is the dollar.** EUR and GBP load together and USDCAD
loads against them, which is exactly the signature of one currency moving against the rest.

### Why a noise floor is not optional here

Even with all true correlations zero, a sample correlation matrix has dispersed eigenvalues.
Marchenko and Pastur give the band in closed form: with `q = N / T`,

    lambda_min = (1 - sqrt(q))^2   ...   lambda_max = (1 + sqrt(q))^2

**Two web sources the desk supplied were checked against this and neither addresses it.** A
university-style treatment of PCA in finance and a trading-site explainer both present
eigendecomposition, portfolio variance as `w' Sigma w`, and the minimum-variance solution
`Sigma^-1 1 / 1' Sigma^-1 1` - and neither mentions random matrix theory, eigenvalue significance,
or out-of-sample eigenvector stability. The first is explicit that "whether a small number explains
most variation depends on the assets, sample period, return frequency, scaling, and preprocessing"
and then offers no test.

That gap is worth a number. That source's worked yield-curve example reports PC1 at 72.8% and
**PC2 at 14.4% on 8 maturities over 500 days**. At `q = 0.016` the band runs to 1.29, and PC2's
eigenvalue is `0.144 x 8 = 1.15` - **inside the noise band.** The "slope factor" in the worked
example would not clear its own noise floor. That is not a criticism of the pedagogy; it is the
reason the floor belongs in the harness.

### The control, in both directions

| set | eigenvalues | above the floor |
| --- | --- | ---: |
| **real book**, 7 instruments | 3.194 ... 0.202 | **2** |
| **synthetics**, 8 instruments | 1.016 ... 0.984 | **0** |
| **pure noise**, same shape | 1.017 ... 0.986 | **0** |

`generated.md` measured the Deriv synthetics over 325 pairs and found no shared driver, so they
are a set of instruments *known* to be independent - and their entire spectrum sits inside the
band. The method finds two factors where factors exist and zero on two different known-null sets,
which is `controls.md`'s argument run in the useful direction.

**A correction made during the run.** A first version applied Laloux's variance adjustment - refit
the band to `sigma^2 = 1 - lambda_1 / N` - unconditionally, and it reported **8 of 8 synthetics as
signal**. The adjustment is only meaningful once the naive band has an outlier to remove: with
every eigenvalue at 1.00, subtracting a "first factor" worth 1.0 shrinks the band below a bulk that
was never dispersed. It now fires only when outliers exist, and one pass only - iterating it runs
away at small `q`, which is the next point.

### The number a desk can use: how many bars before a correlation matrix means anything

At `N = 7` and `T = 20,222`, `q = 0.0003` and the band is **0.07 wide**. Almost any dispersion
clears it, so "the structure is real" is true and useless. **No desk estimates correlations on
twenty thousand bars.** On a rolling window `q` is large enough for the theorem to bite:

| window | q | band to | factors found | on shuffled | lambda_1 | shuffled lambda_1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 0.140 | 1.888 | 1.05 | 0.01 | 3.491 | 1.563 |
| 100 | 0.070 | 1.599 | 1.16 | 0.02 | 3.471 | 1.383 |
| 250 | 0.028 | 1.363 | 1.26 | 0.04 | 3.460 | 1.257 |
| 500 | 0.014 | 1.251 | 1.40 | 0.00 | 3.430 | 1.168 |
| 1,000 | 0.007 | 1.174 | 1.45 | 0.00 | 3.398 | 1.113 |
| 2,000 | 0.004 | 1.122 | 1.70 | 0.00 | 3.357 | 1.085 |
| 5,000 | 0.001 | 1.076 | 2.00 | 0.00 | 3.327 | 1.050 |

Three things fall out, and the first is better than expected:

* **the dollar factor is detectable on fifty bars.** `lambda_1` is 3.49 at a 50-bar window and
  3.33 at 5,000 - it barely moves, against a shuffled control at 1.56 falling to 1.05. It is not
  a long-sample artefact;
* **the shuffled control finds essentially nothing at every window** (1.05 factors real against
  0.01 shuffled at 50 bars), so the count is not manufactured;
* **only one factor is reliably estimable on a rolling window.** The second needs thousands of
  bars to separate. So a covariance-based allocation on this book has **one** real degree of
  freedom, and anything built on a second or third rolling component is fitting noise.

Out of sample, factor 0's eigenvector overlaps **0.995** between halves and factor 1's **0.918**,
against 0.378 for two random directions. The top factor is a structure, not a fit.

### This closes an open question from `metals_pair.py`

That harness measured gold against silver at **+0.7631 contemporaneously with nothing at any lag**
(all `|.| < 0.012`) and could not say why. This says why: **both load on one factor.** The
correlation is a shared dollar exposure, not a lead-lag relationship, so there is no information
passing from one to the other and nothing to trade in the correlation itself. A relative-value
trade there would have to live in the residual after the factor is removed.

## Two: the regimes are real and they are useless

A three-state Gaussian HMM fitted by EM, refitted every 5,000 bars on a rolling 6,000-bar window,
with states labelled by the **forward filter only**.

That last point is the whole methodology. Smoothed labels - forward-backward, or the Viterbi path -
use bars *after* the one being labelled, so a smoothed state is a statement about what the regime
was, written by someone who saw how it ended. Both are reported here.

| instrument | series | dwell | dir filtered | dir smoothed | QLIKE hmm | QLIKE trailing | vol r |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **btcusd** | real | **3.18** | 0.4912 | 0.4971 | 0.8626 | **0.8368** | 0.291 |
| | phase | 1.49 | 0.4901 | 0.4772 | 0.2094 | 0.2162 | 0.007 |
| | shuffle | 2.53 | 0.5006 | 0.5010 | 0.9058 | 0.7219 | 0.006 |
| | gbm | 1.54 | 0.5018 | 0.5102 | 0.2167 | 0.2219 | 0.004 |
| **xauusd** | real | **3.05** | 0.4946 | 0.5002 | 1.2254 | **0.8077** | 0.193 |
| | phase | 1.53 | 0.4984 | 0.4923 | 0.2211 | 0.2262 | −0.011 |
| | shuffle | 2.23 | 0.5040 | 0.5041 | 0.9884 | 0.8344 | 0.003 |
| **eurusd** | real | **3.30** | 0.4983 | 0.5011 | 1.3766 | **0.8020** | 0.166 |
| | phase | 1.52 | 0.4960 | 0.4910 | 0.2173 | 0.2228 | 0.004 |
| | shuffle | 2.12 | 0.4967 | 0.4970 | 0.7989 | 0.7196 | −0.000 |
| | gbm | 1.53 | 0.4984 | 0.4969 | 0.2202 | 0.2233 | −0.001 |

**The states pass the test that withdrew them last time.** `families.md` found the surrogate's
persistence *larger* than the feed's and withdrew its three-state fit. Here the real series dwell
3.05 to 3.30 against 1.49 to 2.53 for every surrogate, on all three instruments.

The difference is the data, and it is worth recording: `families.md` tested on **Drift Switch
synthetics**, which are constant-sigma by construction. Real markets have volatility clustering,
and an HMM finds it. So that withdrawal was correct about the synthetics and does not generalise -
**on a real market, three-state EM finds genuinely persistent states.**

And they predict nothing.

* **direction is null on all three**, and slightly *below* a coin: 0.4912, 0.4946, 0.4983;
* **the look-ahead buys nothing either.** Smoothed labels reach 0.4971, 0.5002, 0.5011 - within
  0.003 of filtered. That is worth knowing on its own: the reason published regime work looks good
  is not the smoothing look-ahead, because there is no directional signal to leak;
* **volatility loses to a trailing standard deviation everywhere**, by 3% on BTC and 72% on
  eurusd. The forecast is positively correlated with realised volatility (0.166 to 0.291) and
  worse calibrated than 100 bars of arithmetic.

So the answer to "we should have directional regimes" is that the states are real, cost a fitted
model with twelve parameters and a refit schedule, and beat neither a coin nor a standard
deviation. The thing that **does** separate outcomes is already in production and is not a regime
model: `trend.py`'s twelve-bar efficiency ratio, at 1.4% break share in its top decile against
11.3% in chop.

## Three: the perceptron reaches the margin, and the margin is negative

192,402 resolved touches - the subset of `break-trade.md`'s 312,420 carrying all seven causal
features - predict-then-update in time order, so every prediction is out of sample.

| | mistake rate | AUC |
| --- | ---: | ---: |
| always-hold | **0.1240** | 0.5 |
| perceptron, averaged weights | 0.1895 | 0.5838 |
| perceptron, last weights | 0.1895 | 0.5771 |
| **online logistic at the production rate** | **0.1248** | **0.6582** |

The mistake curve does not fall. It runs 0.138, 0.148, 0.211, 0.219, 0.212, 0.189 across the pass -
**up, then flat.** Novikoff's bound says a perceptron converges in at most `(R / gamma)^2` mistakes
on separable data. Here `R = 420.2` and the minimum margin is **−91.3**: points of both classes sit
on the wrong side of every plane the data admits, the bound does not exist, and the perceptron
cycles forever. The median margin is `+0.018` and the tenth percentile `−0.014`, so the classes
overlap right through the separating plane.

**That is a statement about the data, and it binds every linear model including the one in
production.** It is also the mechanism behind `models.md`: a 1KB logistic regression beat trees,
forests, cosine similarity and an MLP because when classes overlap this thoroughly, extra capacity
has nothing to fit but noise.

Three further readings:

* **the perceptron is worse than always-hold** on error rate - 0.1895 against 0.1240. A
  mistake-driven update chases a 12.4% minority class and pays for it on the majority. This is
  the same failure `breaking.py` documents for its own model, where accuracy was 87.4% against
  always-hold's 93.2% while the *ranking* was fine;
* **the smooth loss is worth +0.074 AUC** - 0.658 against 0.584. That is what graded updates buy
  over a hard threshold on non-separable data, and it prices the whole difference between a
  perceptron and the production model;
* **whitening changes nothing.** Rotating onto the correlation matrix's eigenvectors and scaling
  to unit variance - PCA with nothing discarded - moves the mistake rate from 0.1895 to 0.1900 and
  the AUC by 0.0002. So the features were not badly conditioned; they are simply not separable.
  Averaging matters more after whitening (0.5890 against 0.5376 for last weights), which is the
  expected behaviour on cycling data and a small confirmation the implementation is sound.

### An independent replication worth recording

The online logistic in this harness scores **AUC 0.6582** on the unconditional population. `force.md`
and `breaking.py` report **0.658** for the joint break model, measured in the 300-1,800s band with
a different implementation.

Those agree to three decimals from different code on a different population. Given that
`break-trade.md` found the *individual* features' AUCs inverting between the band and the
population, the joint model's headline number surviving that shift is the most reassuring thing on
this page.

## What this changes

Nothing ships from it. What it settles:

* **do not build a regime model.** The states are real and predict neither of the two things worth
  predicting, and the incumbent that does separate outcomes is twelve bars of arithmetic;
* **do not build a second or third rolling factor.** One is estimable on a rolling window; the
  rest need thousands of bars, and the count on shuffled data is zero at every window, so there is
  no room to be wrong in the optimistic direction;
* **stop testing model classes against each other on these features.** The margin is negative and
  `R / gamma` does not exist; the ceiling is a property of the data. `models.md` found this
  empirically across five model families and this is the reason;
* **the dollar factor is worth carrying as context.** It is detectable on fifty bars, stable at
  0.995 overlap out of sample, and explains a correlation this folder had measured and could not
  account for. It is not a signal - it is the thing a relative-value trade would have to remove
  first.
