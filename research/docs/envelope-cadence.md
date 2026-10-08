# Production's own retrain loop, replayed: retraining helps a little, the gate decides almost nothing

**Measured 2026-10-08.** [`fortnightly-retrain.md`](fortnightly-retrain.md)
pointed the champion/challenger protocol at a research model. This points it at
**the model production actually promotes** - the offline envelope quantile
forecaster - and asks three things the desk can act on.

Nothing here is a reimplementation. The trainer is production's own
`envelope_train.train` (quantile boosting at `MODEL_LEVELS`, the last
`RECENT_DAYS` of rows, `ITERATIONS` trees) and the score is production's own
**pinball loss** over `ev.TARGETS`, lower being better. Code:
[`envelope_fortnightly.py`](../ideas/envelope_fortnightly.py). Twelve fx series,
596,772 rows at horizon 20, 730 days.

## The result

Pinball loss, lower better. **The gate is production's own rule**, which is a
**tolerance and not a contest**: `GATES["vs_champion"] = 0.01` promotes a
challenger that is within 1% of the champion, so it refuses only a clear
regression.

| cadence | never retrain | always deploy | **gated** (production's rule) | promoted |
|---|---:|---:|---:|---:|
| 14d | 1.33431 | 1.32727 | **1.32420** | 12/14 |
| 28d | 1.34060 | **1.32958** | 1.33001 | 7/7 |
| 56d | 1.33346 | **1.31900** | 1.31953 | 4/4 |

Retraining against never retraining, as a share of the pinball: **+0.76%** at 14
days, **+0.79%** at 28, **+1.04%** at 56.

### A correction to the first run of this

The first version of this study implemented the gate as **"the challenger must
beat the champion"**, and on that rule the gate looked like the headline: it won
at all three cadences and the doc said so. That is not production's rule.
`retrain.py` promotes on a **1% tolerance**, and rerunning under the real one
changes the conclusion rather than refining it. The numbers above are the rerun;
the strict-gate figures are gone rather than kept for comparison, because they
measure a service the desk does not run.

## Retraining helps, by about 0.8-1.0%

Consistent at every cadence and in the right direction. Real, and small - which
is worth stating plainly, because a retrain service running every fortnight
implies a belief that the model goes stale fast, and on this evidence it does
not go stale fast at all.

## The gate is a wash, because it almost never fires

`gated` wins at 14 days (1.32420 against 1.32727, 0.23%) and **loses** at 28 and
56 by 0.03% and 0.04%. Three cadences, two of them the wrong way, every
difference inside a rounding error on four observations.

The mechanism is plain in the promotion column: **23 of 25 challengers were
promoted.** A 1% tolerance on a quantity whose whole spread across every arm here
is about 1.5% is a tolerance that nearly everything clears, so `gated` is
`always deploy` with two refusals in it and cannot differ from it by much.

This agrees with [`fortnightly-retrain.md`](fortnightly-retrain.md), which found
gating exactly neutral on the research model. Both now say the same thing: on
pinball alone **the gate is insurance, not selection.** That is a reasonable
thing for it to be - it exists to stop a broken export, not to pick a winner -
but it is not a source of improvement and should not be argued for as one.

The promotion rate is near-total at every cadence, so it carries no signal about
how much new data a refit wants.

## The fortnight buys nothing over two months

The *relative* gain over never retraining does not fall as the cadence slows:
+0.76%, +0.79%, +1.04%. A refit every 56 days captures what a refit every 14 days
captures, and on these numbers slightly more.

So `--every-days 14` could be **four times slower for the same result**: less
compute, fewer deployment events, and fewer chances to ship a broken export -
which the full `GATES` exist to catch, and which a gate only gets to catch if it
is run. The direction is clear even if the size is not.

## The `never` column is not a baseline. It is production.

Checked on tis 2026-10-08, and verified rather than inferred:

* **no retrain process** in the container - its command is `["till-infinity"]
  `["run"]`, the desk alone
* **no `.report.jsonl` anywhere.** `retrain.py` appends a run report *whether or
  not it promotes*, so its absence means the service has never completed a run
* **no `TI_MODELS_DIR`, `MODELS_*` or `RETRAIN` env** on the container
* **no host cron entry and no systemd timer**
* every model JSON - `envelope_fx15m_5/20/50`, `deriv_law`, `expansion`,
  `shocks` - carries the image build time and sits in
  `/app/till_infinity/models/`, which is **baked into the image**, not a mount

So the desk has been running whatever was packaged at build time, and will keep
doing so until the next rebuild. The `never` row above is not a hypothetical
control - it is what is live, and the gap to `gated` is what that costs:

| | pinball |
|---|---:|
| **production today** (`never`) | **1.333 - 1.341** |
| retrained on any cadence, gated or not | 1.319 - 1.330 |

The plumbing is correct and idle. `frozen.models_dir()` resolves to
`.data/models`, which is the `~/till-data` bind mount, and `frozen._source()`
checks it **before** the packaged copy - so a model dropped there is picked up
within `frozen.RECHECK`, five minutes, with no restart.

**Where it must not run.** tis has two cores and 1.2GB free against a container
already at 2.56GB of a 2.68GB cap, and the retrain pulls 50,001 bars for each of
twelve symbols before fitting five quantile regressors per horizon. Running that
inside the desk's cgroup is what OOM-killed the live desk on 2026-09-10 - and
`sklearn` *is* present in the production image, so it would start before it
died. The lab has 64 cores, 125GB and serves the bridge locally; it trains
there, and only the JSON travels.

## Why not to act on the cadence yet

* **730 days is all the 15m history that survives the feature replay**, which is
  14 periods at a fortnight and **4 at 56 days**. The slow arm is four
  observations.
* Every difference is **under 1.5%**, and there is no interval around any of
  them. The cadence comparison in particular is between arms covering different
  numbers of periods, so only the within-cadence improvement is a like-for-like
  reading.
* Only the **pinball comparison** is applied here, not the full `GATES`.
  Calibration, the control band on memoryless walks and the exactness
  reproduction guard against a broken export rather than a worse model, so the
  promotion rates above are an **upper bound** on what production would ship.

The honest conclusion is a direction, not a number: **turn the service on,
because the gap that matters is `never` against everything else; keep the gate as
the safety check it is rather than as a source of gain; and revisit the cadence
when there is more 15m history to test it on.** A change to
`--every-days` on four observations would be the same mistake as dropping an
instrument on one window - see [`zone-retest.md`](zone-retest.md) for what that
looks like when it is measured.
