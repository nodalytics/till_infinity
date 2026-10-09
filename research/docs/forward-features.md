# The forward readings the contest cannot judge

**Four of the fourteen features the boosted FX 15m envelope is trained on are a
constant `0.0` in every training row and vary only in service.** They are
`ens_ratio`, `fc_ratio`, `garch_ratio` and `vol_stretch` - the readings
`engine._observe_forecasts` hands to `touches.advance` as `forward`.

Found on 2026-10-09 while adding a fifth such feature, which is the only reason
it was found: the question "will the contest be able to judge this one?" has an
answer, and for the four already there the answer was no.

## Why

`engine._observe_forecasts` passes them live:

    self._touches().advance(feed, interval, opened, high, low, close, sigma,
                            {"ensemble_bps": vol.ensemble_bps, ...})

`models/envelope_train.py` does not. It replays bars through `Ranges`, a
lightweight stand-in for `Volatility` that produces `ewma_tr_bps` and nothing
else, and called `advance` with no `forward` argument at all. `touches.base`
then reads `fwd.get("ensemble_bps")` out of an empty dict, `_ratio(None, sigma)`
returns `0.0`, and `vol_stretch` falls to its `0.0` default.

Replaying 400 bars through each path, counting distinct values per column:

| column | trainer | service |
|---|---:|---:|
| `ens_ratio` | **1** (`0.0`) | 151 |
| `fc_ratio` | **1** (`0.0`) | 151 |
| `garch_ratio` | **1** (`0.0`) | 151 |
| `vol_stretch` | **1** (`0.0`) | 151 |

## Why it matters, and why it is not an emergency

A constant column wins no splits in a gradient-boosted tree, so the model simply
ignores those inputs at inference - it is not being fed a *wrong* number, it is
being fed one it never learned to use. Nothing is mispriced. The cost is that
**the contest's verdict on these features is vacuous**: `vs_champion` measures no
loss from dropping a column of zeroes, so a reading that would have helped and a
reading that is worthless score identically. The comment in `_observe_forecasts`
claiming they "go into the envelope's features, where the retrain contest decides
whether they earn a place" was, for these four, not true. It now says so.

It is also why no shipped envelope model declares them. Every
`envelope_fx15m_*.json` in service carries the **2026-09-29 six-name recipe**
(`lvol, r1, r5, r20, rng, hour`), including the two promoted in the 2026-10-08
retrain - the features added on 2026-10-08 have never reached a trained model.

## The fix, which is not this change

Replay the trainer through `Volatility` rather than `Ranges`, so the three bps
readings exist to be passed, and hand them to `advance` as the engine does.
`Ranges` was chosen for speed over a year of 15m bars across a family, so this
is a real cost to measure rather than an obvious win, and it belongs in its own
change with its own contest.

`activity` is the exception and the reason this document exists now: the volume
it needs is already on `Bar`, so `envelope_train` keeps its own `ActivityBook`
and the column moves in training exactly as it does in service. It is the first
forward reading the contest can actually throw out.

## The test

`test_the_trainer_feeds_activity_but_still_not_the_bps_readings` pins both
halves - that `activity` varies, and that the other four do not. The second half
asserts a defect rather than a design. **When it starts failing, the skew has
been fixed, and this document is what wants updating.**
