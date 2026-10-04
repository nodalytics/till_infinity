# Can a break of structure be predicted before it happens?

**Measured, 2026-10-04. The side is not predictable beyond geometry. The timing is, a little, and
mostly through volatility.** The geometry of the two live swing levels decides which one breaks first at
AUC 0.75. That is just as true on iid and GARCH walks (0.755-0.757), so it is arithmetic, not
information. Adding volatility compression, "Levels Likely to Break" pressure, the Weinstein stage, the
FVG magnet, MCFL violence and the swing-label sentence leaves the side AUC flat or slightly worse,
on Binance and on MT5. The primary fails. Whether a break comes within a day or two is about 0.81 AUC
from geometry alone. Compression (G1) adds +0.004 on Binance and +0.003 on MT5 beyond what it adds on
GARCH walks. Four other groups add +0.0004 to +0.001 on Binance. Those cells pass the frozen bar, but the
gains are too small to use.

Script: [`ideas/bos_predict.py`](../ideas/bos_predict.py). Rule, frozen and committed before any
real-data run: [`ideas/bos_rule.json`](../ideas/bos_rule.json). This follows
[turning-points.md](turning-points.md) and [ladder.md](ladder.md) (the side is a coin flip at turns
and at levels), [expansion.md](expansion.md) (volatility expansion can be forecast) and
[models.md](models.md) (a small logistic regression is the model to beat).

## The question

At each sampled bar t:
- **H** is the most recent MCFL v2 3/3 swing high that is known by t (3 bars after the swing) and that
  no close has gone above since. So H is at or above the close.
- **L** is the mirror swing low.

H and L stay fixed for the label. There are two targets:

- **(a) timing:** is there a close beyond H or L within N bars (N = 24 on 1h, 12 on 4h)?
- **(b) side:** given the first close beyond either comes within 60 bars, is it above H?

**Sample:**
- 4h uses every bar and 1h every 3rd bar, after a 300-bar warm-up.
- The chart is not flipped. Up and down stay as labelled.
- Binance: 12 perpetuals from 2021. MT5: 10 markets. Both on 1h and 4h.

**Model:**
- Logistic regression on standardised features, L2 with C = 1.
- One model per venue and per source, with 1h and 4h pooled.
- Trained on bars whose 60-bar label window closes before 2024-01-01, and scored on 2024-01-01 onward.

**Score:** held-out AUC. A group's gain is AUC(G0+X) − AUC(G0) on the same rows, with a 90% interval
from 1,000 day-bootstrap draws (the same draws for every set).

**Controls:** the identical pipeline on iid and GARCH(1,1) walks matched to each series' sigma, built
from 256 sub-steps a bar, carrying the real timestamps, with synthetic volume from `mcfl.synth.ticks`.

**The bar to pass:** a group predicts only if its real gain has its interval above 0 **and** beats its
gain on both walks.

**Feature groups** (full definitions in the JSON):

| | |
|---|---|
| G0 geometry (baseline) | distance to H and to L in ATR (raw, log1p, log ratio), ATR5/ATR50, the bars since each swing, is_4h |
| G1 volatility | 10-bar range / ATR50, ATR5/ATR20, Bollinger width percentile (100 bars), ATR14/ATR100 |
| G2 Levels Likely to Break (Zeiierman, re-implemented) | repeated-pivot flag for H and L, 5-bar move toward, relative volume, close location (plain and volume-weighted), absorption at H and at L, 5-bar compression, fresh touches of H and of L |
| G3 Weinstein stage (MarkitTick, re-implemented) | SMA(30), slope z (in ATR, against its own 500-bar sd; flat band ±0.5 sd), the four-stage machine one-hot, bars in stage, price vs SMA, 30-bar breakout and breakdown |
| G4 FVG magnet (Neblok, re-implemented) | nearest unfilled gap above and below (≥0.25 ATR): distance, size, age, a fill rate learned causally per (type, size bucket, age bucket), and the net pull |
| G5 MCFL violence | DISPLACE_C, DELIVERY_SHIFT, BREACH_REVERT, up and down, in the last 5 bars; range_z of bar t |
| G6 structure sentence | the last three swing labels (HH LH EH LL HL EL), one-hot |

## Primary: (b) side, G0+all against G0, Binance. It fails.

| Binance, side | AUC G0 | AUC G0+all | gain [90%] |
|---|---|---|---|
| **real** | 0.7514 | 0.7505 | **−0.0009 [−0.0016, −0.0001]** |
| iid walk | 0.7549 | 0.7544 | −0.0005 |
| GARCH walk | 0.7567 | 0.7554 | −0.0012 |

There are 163,507 training rows and 155,343 held-out rows, and 51% of the rows break up first. The
features beyond geometry do not just fail to help: their interval sits below zero. The
extra 62 features are noise that costs a little out of sample, on real data and on walks alike. The
G0 AUC itself is no evidence of skill. Whichever level is nearer in ATR tends to break first, and on a
walk that does slightly *better* than on real markets.

**Calibration** (`bos_calibration.png`): the side model is well calibrated in every decile, real and
walks. The real top decile predicts 0.873 up first and realises 0.869; the bottom predicts 0.143 and
realises 0.154. The walks' curves lie on top of the real one. Calibration here measures geometry, and
geometry is the same on a random path.

**The trade follow-up was not run.** It was registered only for a passing side model (top decile of
P(up first), long at t+1's open, stop beyond L). The top decile is also where H is nearest, which a walk
reproduces.

## Secondary: every group, both targets, both venues

The held-out AUC gain over G0, real against walks. ✔ marks the frozen bar: interval above 0 and above
both walks.

| venue | target | set | real gain [90%] | iid | GARCH | |
|---|---|---|---|---|---|---|
| Binance | side | +G1 | +0.0002 [−0.0000, +0.0004] | −0.0001 | −0.0001 | |
| Binance | side | +G2 | −0.0003 [−0.0006, +0.0001] | −0.0001 | −0.0003 | |
| Binance | side | +G3 | +0.0001 [−0.0004, +0.0006] | +0.0001 | −0.0002 | |
| Binance | side | +G4 | −0.0004 [−0.0006, −0.0002] | −0.0003 | −0.0004 | |
| Binance | side | +G5 | −0.0002 [−0.0003, −0.0000] | −0.0001 | −0.0001 | |
| Binance | side | +G6 | −0.0001 [−0.0004, +0.0003] | +0.0000 | −0.0001 | |
| Binance | time | +G1 | **+0.0039 [+0.0029, +0.0049]** | +0.0005 | +0.0019 | ✔ |
| Binance | time | +G2 | +0.0010 [+0.0006, +0.0015] | −0.0001 | +0.0001 | ✔ |
| Binance | time | +G3 | +0.0007 [+0.0001, +0.0013] | −0.0002 | −0.0001 | ✔ |
| Binance | time | +G4 | +0.0006 [+0.0001, +0.0012] | −0.0001 | −0.0000 | ✔ |
| Binance | time | +G5 | +0.0004 [+0.0001, +0.0006] | +0.0000 | +0.0000 | ✔ |
| Binance | time | +G6 | +0.0002 [−0.0001, +0.0005] | −0.0001 | −0.0002 | |
| Binance | time | +all | **+0.0043 [+0.0029, +0.0057]** | −0.0002 | +0.0016 | ✔ |
| MT5 | side | +G1..G6 | −0.0007 to −0.0001; G2 and G4 intervals below 0 | | | |
| MT5 | side | +all | −0.0017 [−0.0025, −0.0009] | −0.0007 | −0.0010 | |
| MT5 | time | +G1 | **+0.0031 [+0.0021, +0.0041]** | +0.0007 | +0.0014 | ✔ |
| MT5 | time | +G2 | +0.0006 [+0.0002, +0.0009] | −0.0000 | +0.0000 | ✔ |
| MT5 | time | +G3 | −0.0002 [−0.0003, −0.0001] | −0.0002 | +0.0001 | |
| MT5 | time | +G4 | +0.0001 [−0.0003, +0.0005] | +0.0000 | −0.0002 | |
| MT5 | time | +G5 | +0.0004 [+0.0002, +0.0007] | +0.0000 | +0.0001 | ✔ |
| MT5 | time | +G6 | −0.0002 [−0.0003, +0.0000] | −0.0004 | −0.0001 | |
| MT5 | time | +all | +0.0023 [+0.0011, +0.0035] | −0.0000 | +0.0011 | ✔ |

**Base AUCs (G0):**

| | Binance real | iid | GARCH | MT5 real | iid | GARCH |
|---|---|---|---|---|---|---|
| (a) timing | 0.806 | 0.840 | 0.836 | 0.810 | 0.841 | 0.839 |
| (b) side | 0.751 | 0.755 | 0.757 | 0.745 | 0.757 | 0.757 |

Per timeframe and per test half (reported, not gated):
- **Side, G0:** Binance 1h 0.750, 4h 0.753; 2024 0.760, 2025 on 0.746.
- **Side, G0+all:** 0.749, 0.753, 0.759, 0.745. That is below G0 in every slice.
- **Timing, G0+all over G0:** +0.005 on 1h and +0.005 on 4h; +0.003 in 2024 and +0.006 from 2025.

## What it says

- **The side is geometry, and geometry is what a walk does.** The relative distance to H and L sorts
  the side at AUC 0.75, with extreme deciles at 0.87 and 0.15 up first, on real data and on walks
  alike. None of the six feature groups adds a side on either venue. Several make it slightly worse. This is
  the same answer [ladder.md](ladder.md) got at level touches, now at the level of swing structure.
- **The timing gain is a volatility forecast.** G1 alone carries most of it, and it is larger on GARCH
  walks (+0.0019) than on iid walks (+0.0005): volatility clustering explains part of it. The rest,
  about +0.002 AUC beyond GARCH, is the same compression-to-expansion fact
  [expansion.md](expansion.md) already ships. G2, G3, G4 and G5 clear the frozen bar on Binance timing
  with gains of 0.0004-0.001 AUC. That is real by the test's rules, but it would not change any
  decision, and with 24 group cells some passes at this size are expected from overlap and selection.
- **Real levels break less often than walk levels.** 70.5% of Binance bars see a BOS within the window,
  against 75-76% on walks (MT5 73% against 75-76%). And the geometry-only timing AUC is about 0.03
  lower on real markets. Real swings hold longer than random-path swings of the same ATR. This was
  not pre-registered and is reported as an observation only. It fits [turning-points.md](turning-points.md)
  §5, where real trends make the next extreme less often than walks.

## Verdict

**The primary fails: a break of structure cannot be called for side beyond the geometry of the two
levels.** G0+all against G0 on Binance is −0.0009 [−0.0016, −0.0001], against −0.0005 (iid) and
−0.0012 (GARCH). MT5 agrees (−0.0017). Timing passes the frozen bar for G1 (compression) on both venues,
and for G2-G5 on Binance, but the best gain is +0.004 AUC on a 0.81 base. That is a volatility fact the
desk already has, not a new one. The registered trade follow-up was not run.

## Caveats

- **Re-implementations.** G2 (Zeiierman), G3 (MarkitTick) and G4 (Neblok) are built from the
  indicators' public descriptions, not their code.
  - Weinstein's slope is measured in ATR, not %, so that arithmetic walks stay scale-free. Its flat
    band is ±0.5 sd of its own slope.
  - "MA stops rising/falling" requires that the MA rose (or fell) at some bar within the stage.
    Otherwise every breakout would fall straight to stage 3.
- **The model is linear on purpose** ([models.md](models.md)). A tree model might find interactions.
  But with every single group flat or negative on the side, and G0 already calibrated, there is little
  for it to find.
- **The rows overlap** (successive bars share H, L and their future). The day bootstrap allows for
  clustering within a day, not across days, so the intervals are somewhat narrow. That makes the
  small timing passes weaker, not stronger.
- **MT5's US SP 500, US Tech 100, Germany 40 and US Oil begin 2024-01-22**, so they are scored but
  never trained on. MT5 volume is tick volume.
- **Walk volume comes from `synth.ticks`**, so it tracks the bar's range by construction. On walks the
  volume features are a range proxy.
- **The G4 fill rate is learned per series** from resolved gaps only. Gaps that will expire resolve
  later than gaps that fill, so early rates lean toward fills. That is causal but biased.

## Re-running

On the lab:

    OUT=... MT5BT_DB=... MODE=run python research/ideas/bos_predict.py    # about 15 min, 10 workers
    OUT=... MODE=plot python research/ideas/bos_predict.py
    SMOKE=binance:BTC:4h:garch python research/ideas/bos_predict.py       # one series

Outputs:
- tables: `bos_auc.csv` (every venue × source × target × set: AUC, gain, interval, per timeframe,
  per half), `bos_verdict.csv` and `bos_calibration.csv`;
- data: `bos_rows.pkl.gz` and `bos_preds.pkl.gz`;
- plots: `bos_gain.png` (gain by group, real against walks, both targets and venues),
  `bos_calibration.png` and `bos_gallery.png` (held-out Binance 4h examples, three from the model's
  most bullish decile and three from its most bearish; the H and L lines are drawn across the whole
  window, but they are the levels live at the purple bar).
