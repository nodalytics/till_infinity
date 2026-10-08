# The envelope already knows it: the magnitude model is a rediscovery

**Measured 2026-10-08.** [`zscore-magnitude.md`](zscore-magnitude.md) found the
one positive result in the z-score work - strip the sign and a boosted model
predicts |forward move| over the ATR, beating every single feature fourfold and
holding across seven annual refits and sixty unseen instruments.

But predicting |move| **is** volatility forecasting, and this desk already ships
an offline quantile forecaster that does exactly that:
`models/envelope_train.py`, with its own fortnightly retrain contest. So the
comparison that decides whether the work is an addition or a rediscovery is not
against raw ATR, which it wins. It is against the model already in production.

Code: [`envelope_vs_magnitude.py`](../ideas/envelope_vs_magnitude.py).

## Run on the envelope's own ground

Nothing tilted toward the challenger:

* **its bars** - 15m, the fx family, `model_applies` deciding membership. Twelve
  series, 600,000 bars
* **its features** - `MODEL_NAMES` = `lvol, r1, r5, r20, rng, hour`, replayed
  through `Touches` exactly as the engine builds them
* **its target** - `log(close[i+h] / close[i]) / sigma[i]`, the signed move in
  volatility units, at its own horizons 5, 20 and 50
* scored against **|y|**, the magnitude, which is the quantity in dispute

A date split at 70%, the boundary purged by the horizon.

## The result

| horizon | n test | **shipped envelope**, (P90-P10)/2 | **direct magnitude fit**, same features | shuffled |
|---:|---:|---:|---:|---:|
| 5 | 179,078 | IC **+0.2478** / spread 0.934 | IC +0.2547 / spread 0.989 | -0.0313 |
| 20 | 178,978 | IC **+0.2804** / spread 2.138 | IC +0.2803 / spread 2.082 | -0.0123 |
| 50 | 178,922 | IC **+0.3009** / spread 4.184 | IC +0.2959 / spread 4.183 | -0.0254 |

**They are the same model.** The shipped quantile forecaster and a direct
magnitude regression on its own features are within **0.007 IC at every
horizon**, and the direct fit is the *worse* of the two at horizons 20 and 50.

So the quantile fit is not leaving magnitude information on the table. Changing
the objective from quantiles to |move| - the change that made the whole z-score
line work - buys **nothing** on the model this desk actually runs.

## What follows

**The magnitude work is a rediscovery.** It found a real effect by a different
route, on different bars with a different normaliser, and production has been
exploiting the same effect through `envelope_train.py` for some time. That is
not a wasted result - an independent route to the same place is evidence the
place is real - but it is not a reason to build anything new.

**Nobody should integrate the magnitude model.** The correct move for any
sizing or stop-width work is to read the envelope's quantiles, which are
already fitted, already gated, already retrained fortnightly, and already in
service.

## The one thing this does not close

The comparison holds the **features** fixed and varies the objective. It does
not ask whether the z-score feature set - the ceiling-normalised levels at six
windows, the term structure, the candle shape - adds anything to the envelope's
six. That is the only remaining way the magnitude work could be an addition
rather than a rediscovery, and it is a different run: join those features to
these 15m rows and refit.

Worth doing, with one caveat set against it in advance. The envelope's own
features already carry a volatility state (`lvol`), three realised moves
(`r1, r5, r20`) and a range - which is most of what the z-score features
measure, in a different coordinate system. The prior should be that they add
little.

Measured with the fortnightly protocol in
[`fortnightly-retrain.md`](fortnightly-retrain.md), not a single split, if it is
run at all.
