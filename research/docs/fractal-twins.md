# Markets remember their volatility fractally and their direction not at all, so historical twins can time an expansion and cannot call a trade

Measured 2026-09-26 on the lab with [`fractal_twins.py`](../harness/fractal_twins.py): 20 real
instruments (15 FX pairs, XAU, XAG, BTC, ETH, SOL) and four exact random walks from the Deriv
synthetics as the control, at a 15m base (with 1h and 4h above it) and a 1h base (with 4h and 1d),
about 1.18 million moments per base, forward horizon 16 bars.

Rules throughout:
- the twins' memory, and every model, come from each series' first 60% by time;
- everything is scored on the last 40%;
- trades are non-overlapping and net of spread, with both halves reported and a common-offset null.

## The claim

A product description:
> "Financial markets do not repeat linearly, but they rhyme fractally. Our engine embeds millions
> of historical multi-asset candles into 1536-dimensional vector space. When current price action
> forms, we retrieve the statistically dominant historical twins to calculate empirical win
> rates, volatility bands, and quantile trajectories."

It offers regime-shift alerts (compression to expansion), 15m market probabilities, and quantile
fan charts. All of it is tested here, with ML and deep-learning models alongside the twins.

- **Embeddings.** Each moment's recent candles as a vector - return, range and close location,
  each over the trailing baseline move. Three versions:
  - `shape`: 64 bars of the base timeframe;
  - `fractal`: 32 bars on each of three timeframes - the "rhymes across scales";
  - `learned`: the penultimate layer of a 1D CNN trained to predict the forward quantiles.
- **Twins.** The 50 most cosine-similar moments in a 300,000-moment memory drawn from the training
  block, all instruments pooled. The dimension does not matter to the method - 1536 is the size of
  a common text embedding - what matters is what the neighbours know.
- **ML and DL on the same windows and targets:** gradient boosting on the flattened fractal
  vector, and the CNN (the recurrent networks are below).

## Fractal memory is real - in volatility

DFA Hurst exponents (0.5 is no memory):

| | returns, 15m / 1h | \|returns\|, 15m / 1h |
| --- | --- | --- |
| FX | 0.513 / 0.511 | **0.730 / 0.673** |
| metals | 0.526 / 0.531 | **0.722 / 0.670** |
| crypto | 0.534 / 0.535 | **0.836 / 0.809** |
| random walks (control) | 0.508 / 0.507 | 0.528 / 0.529 |

**The size of moves has long memory, and their direction has almost none.** That one table
predicts everything below: whatever twins can do, they will do it for volatility and not for
direction.

## Direction - the "15m market probabilities": a coin

AUC of P(up over the next 16 bars) on the test block, real markets / random walks:

| | 15m base | 1h base |
| --- | --- | --- |
| twins, shape | 0.505 / 0.496 | 0.505 / 0.502 |
| twins, fractal | 0.508 / 0.497 | 0.501 / 0.503 |
| twins, learned | 0.502 / 0.501 | 0.503 / 0.497 |
| gradient boosting | 0.513 / 0.493 | 0.503 / 0.504 |
| CNN | 0.505 / 0.502 | 0.499 / 0.511 |

Traded, long above the training block's 80th percentile and short below its 20th, net in baseline
moves: **-0.33 to -0.45 at 15m and -0.06 to -0.27 at 1h, every model**, with the common-offset z
between -1.1 and +1.6. The twins' "empirical win rate" is the base rate of up-moves among
neighbours that are no more likely to go up than anything else.

## Volatility bands: the twins lose to a trailing sigma

Spearman correlation of predicted with realised |move| over 16 bars (real / control), and QLIKE on
real markets (lower is better):

| | 15m | 1h |
| --- | --- | --- |
| EWMA sigma x sqrt(H) | **+0.098** / -0.011, QLIKE **2.16** | **+0.125** / +0.010, QLIKE **1.90** |
| twins, shape | +0.080 / +0.008, 3.67 | +0.061 / -0.010, 2.82 |
| twins, fractal | **+0.140** / -0.002, 3.46 | +0.098 / -0.003, 2.78 |
| twins, learned | +0.039 / +0.001, 3.74 | +0.050 / +0.005, 3.01 |

The fractal twins rank volatility slightly better than the trailing sigma at 15m. But their
*level* is badly off - QLIKE 3.5 against 2.2 - because 50 neighbours' median move is a noisy
estimate of a scale a one-line EWMA already tracks. As a volatility band, a trailing sigma is
better and costs nothing.

## Quantile fan charts: the twins' fans are too narrow

Share of outcomes inside the forecast 10-90% band (target 80%), and pinball loss (lower is
better), real markets:

| | 15m | 1h |
| --- | --- | --- |
| Gaussian from EWMA sigma | 89.1%, 1.452 | 88.5%, 1.486 |
| twins, shape | 77.2%, 1.415 | 77.7%, 1.471 |
| twins, fractal | 76.6%, 1.417 | 76.6%, 1.476 |
| twins, learned | 76.1%, 1.441 | 75.6%, 1.494 |
| gradient boosting (quantile) | 78.1%, **1.376** | 78.3%, **1.438** |
| CNN (quantile) | 76.5%, 1.387 | 81.4%, 1.438 |

The Gaussian fan is too wide, and the learned fans are a little too narrow (the 1h CNN, at
81.4%, slightly wide); the quantile models edge out the twins on pinball loss. **None of the fans'
centres carries direction** - they come from the same models whose direction AUCs are above. A fan
chart here describes how wide the next four hours may be. It cannot say which side of it price
will end on.

## Regime shift, compression to expansion: the one thing that works

From a compressed state (14-bar true-range percentile at or below 0.2 of its last 1,500 bars),
does an expansion (percentile at or above 0.8) follow within 16 bars?

| real markets | 15m: AUC, top-10% precision (lift) | 1h |
| --- | --- | --- |
| base rate from compression | 4.9% | 7.4% |
| twins, shape | 0.574, 6.4% (1.31x) | 0.505, 6.5% (0.88x) |
| twins, fractal | 0.639, 8.9% (1.79x) | 0.591, 10.3% (1.39x) |
| twins, learned | 0.627, 8.6% (1.75x) | 0.610, 12.4% (1.68x) |
| **gradient boosting** | **0.728, 14.4% (2.91x)** | **0.738, 22.1% (2.98x)** |
| CNN | 0.672, 10.3% (2.08x) | 0.708, 19.8% (2.67x) |

On the random walks every model sits at AUC 0.50-0.56 and lift 1.0-1.4x. **Expansion from
compression is predictable, about three times the base rate, and gradient boosting does it best -
better than any twin.** It is the volatility memory in the Hurst table, at work. This is the
same volatility memory [`crash-timing.md`](crash-timing.md) found for large bars, which is
already built into live sizing as the spike switch (deployed, off until `TRADING_SPIKE_ABOVE` is set).

**And the side of the expansion is a coin.** Among real compressed moments that did expand, the
fractal twins call its direction at AUC 0.531 (15m) and 0.505 (1h), and the CNN at 0.466 and 0.494.

## Every sequence architecture: the same three answers

The CNN was the first deep model; it was not the last. On the same 96-step multi-timeframe
sequences (32 bars on each of three timeframes, return, range and close location), the same targets
and the same split, twelve more architectures were trained (`PART=rnn`, `seq`, `hybrid`, `more`,
`tcnattn`, `cnnlstm`, `trlstm`, `grucnn` in [`fractal_twins.py`](../harness/fractal_twins.py);
150,000-moment training sample, against 250,000 for gradient boosting and the CNN):
- **recurrent:** LSTM, a two-layer stacked LSTM, GRU, a vanilla RNN, a bidirectional LSTM
  (legitimate here - the whole window is already in the past);
- **attention and convolution:** a transformer encoder, and a TCN (dilated causal convolutions
  with residual connections);
- **hybrids:** LSTM + attention, GRU + attention, TCN + attention (self-attention over the
  sequence model's outputs and a learned attention pooling), CNN-LSTM, GRU-CNN, and
  transformer-LSTM.

Real markets, test block, 15m base / 1h base:

| model | direction AUC | traded, net | fan coverage (target 80%), pinball | alert AUC from compression (lift) |
| --- | --- | --- | --- | --- |
| *gradient boosting* | *0.513 / 0.503* | *-0.33 / -0.06* | *78.1%, 1.376 / 78.3%, 1.438* | ***0.728 (2.91x) / 0.738 (2.98x)*** |
| *CNN* | *0.505 / 0.499* | *-0.43 / -0.27* | *76.5%, 1.387 / 81.4%, 1.438* | *0.672 (2.08x) / 0.708 (2.67x)* |
| LSTM | 0.503 / 0.507 | -0.61 / -0.22 | 80.3%, 1.393 / 79.5%, 1.449 | 0.543 (1.08x) / 0.637 (2.17x) |
| LSTM x2 (stacked) | 0.502 / 0.500 | -0.58 / -0.36 | 80.4%, 1.393 / 79.7%, 1.448 | 0.544 (1.55x) / 0.656 (2.09x) |
| GRU | 0.501 / 0.500 | -0.61 / -0.35 | 80.7%, 1.393 / 79.7%, 1.448 | 0.598 (1.63x) / 0.646 (2.00x) |
| vanilla RNN | 0.509 / 0.498 | -0.55 / -0.16 | 80.6%, 1.393 / 79.7%, 1.448 | 0.618 (1.63x) / 0.629 (1.66x) |
| bidirectional LSTM | 0.503 / 0.503 | -0.41 / -0.35 | 80.6%, 1.393 / 79.6%, 1.447 | 0.615 (1.87x) / 0.693 (2.42x) |
| transformer | 0.511 / 0.512 | -0.55 / -0.18 | 80.7%, 1.393 / 80.1%, 1.448 | 0.697 (2.47x) / **0.753 (3.07x)** |
| TCN | 0.505 / 0.502 | -0.64 / -0.16 | 80.2%, **1.377** / 80.8%, **1.433** | 0.717 (2.88x) / 0.745 (3.05x) |
| LSTM + attention | 0.510 / 0.515 | -0.56 / -0.20 | 79.7%, 1.392 / 79.0%, 1.446 | 0.666 (2.00x) / 0.679 (2.22x) |
| GRU + attention | 0.513 / 0.516 | -0.49 / -0.21 | 80.6%, 1.393 / 79.1%, 1.444 | 0.643 (1.93x) / 0.686 (2.35x) |
| TCN + attention | 0.507 / 0.510 | -0.48 / -0.20 | 80.6%, 1.389 / 78.5%, 1.439 | 0.659 (1.86x) / 0.741 (3.09x) |
| CNN-LSTM | 0.498 / 0.503 | -0.65 / -0.40 | 80.2%, 1.393 / 79.8%, 1.448 | 0.631 (1.95x) / 0.702 (2.43x) |
| GRU-CNN | 0.507 / 0.510 | -0.52 / -0.24 | 81.2%, 1.393 / 80.5%, 1.445 | 0.622 (1.78x) / 0.684 (2.19x) |
| transformer-LSTM | 0.512 / 0.512 | -0.54 / -0.07 | 80.5%, 1.393 / 79.7%, 1.449 | 0.673 (2.34x) / 0.730 (2.89x) |

(net in baseline moves per trade, long above the training block's 80th percentile and short below
its 20th, non-overlapping, net of spread. Random walks: direction AUC 0.492-0.511 and alert AUC
0.508-0.573 for every architecture.)

Three answers, the same from every architecture:
- **Direction is a coin.** Fourteen deep models land between 0.498 and 0.516, within reach of the
  random walks' 0.492-0.511, and every one loses when traded: -0.41 to -0.65 at 15m, -0.07 to -0.40
  at 1h. None clears the common-offset null in its favour (z -3.0 to +1.2 across the 26 sequence-model rows).
  Recurrence, attention, bidirectionality and every hybrid change nothing, because there is
  nothing in the sequence for them to find.
- **The fan is well calibrated and cannot be told apart between models.** The sequence models
  cover 78.5-81.2% (the CNN's 76.5% at 15m is the one outlier). Pinball loss sits between 1.377 and 1.393 at 15m, and 1.433 to 1.449 at
  1h. The TCN is marginally the best at both, level with gradient boosting.
- **The expansion alert is where architecture matters, and it tops out where gradient boosting
  already is.** The transformer at 1h (AUC 0.753, 3.07x) and the TCN (0.745 at 1h, 0.717 at 15m)
  are the best deep models, and they match gradient boosting (0.738, 0.728) rather than beat it.
  The plain recurrent networks are the weakest here (0.54-0.66). What they are all detecting is the
  volatility memory in the Hurst table.

## What this settles

- **"Rhymes fractally"** is true of volatility (Hurst 0.67-0.84 on |returns|) and false of
  direction (0.51-0.54, next to the random walks' 0.51).
- **Historical twins** are a weaker volatility model than a trailing EWMA and no directional
  model at all. Gradient boosting on the same windows beats them on the fan and the alert.
- **Deep learning does not change it.** Fourteen architectures - CNN, LSTM, stacked LSTM, GRU,
  vanilla RNN, bidirectional LSTM, transformer, TCN, and six hybrids of them with each other and
  with attention - reproduce gradient boosting's answers: no direction, a calibrated fan, and an
  expansion alert that the best of them only match.
- **The useful product** in that description is the regime-shift alert. Scored honestly it is a
  volatility-timing signal - about 3x the base rate for expansion from compression - with no side,
  so its use is sizing, which is what the spike switch is for.
