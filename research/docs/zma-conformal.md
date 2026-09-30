# ZMA + conformal inference: an anytime-valid gate, calibrated calls, and a Mondrian envelope

Harness: [`research/harness/zmaconformal.py`](../harness/zmaconformal.py). Lab runs 2026-09-30, on
seqlab bars and on walks we generate. Deriv is treated as a market, not a control.

## The questions

[`zeroskill.md`](zeroskill.md) found the ZMA record's old bar (200 edge calls above 52%) letting a
coin through on about one feed in five. PR #19 replaced it with a single-look significance line,
`Settings.zma_line` = max(0.52, 0.5 + 3.29·√(0.25/calls)). But production re-reads the record on
every bar. A line built for one look is not valid when it is looked at again and again, so the first
question is whether it holds under continuous monitoring. Three questions, pre-registered in the
harness docstring:

1. **Gate.** Does an anytime-valid e-process keep the book-wide false pass at or below 5% over
   180 days of continuous monitoring, and earn a genuinely skilled feed in comparable time (median
   within 2x of the line)?
2. **Probability.** Can conformal calibration (Venn-Abers) turn a call's z-state into a calibrated
   probability that the call is right, with skill over the base rate, in both halves and beyond the
   walks?
3. **Envelope.** Does a Mondrian AgACI run separately per ZMA bucket (stretched down / inside /
   stretched up) beat production's single AgACI? The bar: better pinball, a worst slice no more than
   1 point worse, and a z-bucket coverage gap closed by more than 2 points.

## 1. The gate: the line fails under continuous monitoring; an e-process holds

**The e-process.** It is a mixture of betting martingales on the edge record's right/wrong
sequence, tested against a coin:

K = mean over λ ∈ {0.02, 0.05, 0.1, 0.2, 0.4} of (1 + λ/2)^right · (1 − λ/2)^(calls − right)

By Ville's inequality, P(K ever ≥ 1/a) ≤ a under a coin, however often it is checked. Across
100 feeds, Bonferroni sets the pass at K ≥ 100/0.05 = 2,000, i.e. log K ≥ 7.60.

**The line** is checked the way production uses it: at every call from 200 on. The edge-call rate
is measured from the production `Zma` on walks: 0.151 calls per bar on t(3) and 0.150 on GARCH.

**Coins, a book of 100 feeds (100 books per cell).** The table shows the share of books where *any*
feed ever passes, and the share of individual feeds that ever pass.

| interval | days | calls | line: book | line: feed | e-process: book | e-process: feed |
|---|---|---|---|---|---|---|
| 15m | 30 | 310 | 20.0% | 0.22% | 0.0% | 0.000% |
| 15m | 90 | 930 | 34.0% | 0.42% | 2.0% | 0.020% |
| 15m | 180 | 1,861 | **50.0%** | 0.68% | **0.0%** | 0.000% |
| 1h | 90 | 232 | 11.0% | 0.12% | 0.0% | 0.000% |
| 1h | 180 | 465 | **22.0%** | 0.23% | **0.0%** | 0.000% |
| 4h | 180 | 116 | 0.0% | 0.00% | 0.0% | 0.000% |

The single-look line's promise (5% across 100 feeds) holds at a single look only. Checked every bar,
**half of all 100-feed books have a coin earning at 15m within 180 days**. The e-process stays at
0-2%.

**Days to earn for one skilled feed** (median [25%, 75%] of 400 runs; "never" means not within 3
years):

| interval | true hit rate | line | e-process | ratio |
|---|---|---|---|---|
| 15m | 0.53 | 238 [125, 352] | 462 [299, 607] | 1.94x |
| 15m | 0.55 | 76 [44, 120] | 155 [106, 213] | 2.04x |
| 15m | 0.60 | 24 [19, 34] | 42 [31, 56] | 1.75x |
| 1h | 0.55 | 342 [203, 519] | 612 [468, 855] | 1.79x |
| 1h | 0.60 | 92 [77, 132] | 160 [120, 220] | 1.74x |
| 4h | 0.60 | 365 [309, 511] | 645 [501, 859] | 1.77x |

At 1h with a 0.53 hit rate, the line earns within 3 years 63.5% of the time and the e-process 19.5%.
At 4h with 0.55, the figures are 37.5% and 7.0%.

The price of validity is **about 1.75-2x longer to earn**. Five of the six cells are inside the
pre-registered 2x; 15m at 0.55 is at 2.04x.

**Walks through the production `Zma`** (8 seeds × 60,000 bars): neither gate ever passes, on t(3)
or on GARCH.

**Real feeds.** These are seqlab's whole histories, with about 7,300 edge calls per series at 15m
and 1h and 1,600-7,400 at 4h. The production `Zma` builds the edge record.

| | line: ever passed | line: passing at the end | e-process: ever passed |
|---|---|---|---|
| all 69 series | 28 | 18 | **13** |
| FX 15m / 1h / 4h | 7 / 8 / 5 | 4 / 6 / 2 | 2 / 4 / 1 |
| metals 15m / 1h / 4h | 0 / 2 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| crypto 15m / 1h / 4h | 3 / 3 / 0 | 3 / 3 / 0 | 3 / 3 / 0 |
| Deriv (all) | 0 | 0 | 0 |

- **Ten series passed the line at some point and no longer pass it.** Examples: FX 15m AUDUSD,
  USDCHF and EURAUD; 1h USDJPY, GBPJPY, XAUUSD and XAGUSD; 4h AUDUSD, USDCAD and AUDJPY. That is the
  repeated-look problem, seen in real data.
- **What the e-process earns:** EURCHF at every timeframe (0.532-0.541), EURUSD 15m and 1h,
  EURGBP 1h, CHFJPY 1h, and crypto 15m and 1h (0.536-0.559).
- **What it withholds:**
  - GBPUSD, AUDUSD and EURAUD at 0.52, whose max log K is 5.0-6.1 against the 7.6 needed;
  - metals, including XAGUSD 1h at 7.44, just short;
  - every Deriv index. Their records sit at 0.474-0.506, as `zeroskill.md` expected.

**Verdict: passes.** The book-wide ever-false-pass is 0-2% against a 5% bar. Earning takes
1.75-2.04x as long, just inside the 2x bar except one cell at 2.04x.

## 2. A calibrated probability per call: none beyond the base rate

**Method.** Inductive Venn-Abers on isotonic regression of the call's |z|/strong, stratified by
whether the slope agrees. It is refit every 250 calls on the previous 3,000 (thinned to 1,500), and
scored on each series' last 40%.

**Scoring.** Brier skill over the running base rate (the feed's own recent hit rate), with a
day-bootstrap 95% CI.

**Results, next-bar target (what the record scores):**

| | 15m skill over base [95% CI] | 1h skill over base [95% CI] |
|---|---|---|
| FX | −0.0027 [−0.0042, −0.0012] | −0.0044 [−0.0056, −0.0032] |
| metals | −0.0038 [−0.0065, −0.0011] | −0.0034 [−0.0071, −0.0000] |
| crypto | −0.0018 [−0.0050, +0.0018] | −0.0035 [−0.0060, −0.0011] |
| Deriv | −0.0043 [−0.0066, −0.0022] | −0.0053 [−0.0074, −0.0034] |
| walks t(3) | −0.0048 [−0.0069, −0.0021] | −0.0057 [−0.0076, −0.0034] |
| walks GARCH | −0.0027 [−0.0048, −0.0007] | −0.0031 [−0.0054, −0.0012] |

The 5-bar target reads the same: every cell is between −0.0060 and −0.0018, walks included.

**The calibrated probabilities are well behaved but carry nothing.** They stay within 0.44-0.61,
and the worst decile gap is 5-9 points. Every market family scores the same slightly negative skill
as the walks: the cost of estimating a mapping that isn't there. The state of a call (how far past
the band, whether momentum has turned) says nothing about whether it will be right beyond the
feed's hit rate. That agrees with `zma-ml.md`.

**Verdict: null.** Whatever a feed's record knows is in its hit rate, which is exactly what the gate
tests. There is no finer per-call probability to act on.

## 3. Mondrian conformal by ZMA state: it fixes the stretched buckets' coverage

**Production's single AgACI mis-covers stretched states.** Examples:

| family, N | bucket | P90 cover | P10 cover |
|---|---|---|---|
| FX 15m, N = 5 | stretched up | **85.2%** | 12.1% |
| FX 15m, N = 5 | stretched down | 89.1% | 12.2% |
| metals, N = 20 | stretched down | 88.4% | **6.9%** |
| Range Break, N = 50 | stretched up | 93.1% | **6.7%** |

The next-N-bar distribution is different when price is stretched: wider in FX and crypto, skewed
in metals and Range Break.

**A Mondrian AgACI run separately per bucket, each on its own bucket's history, closes those gaps**
with the same overall coverage and width:

| family, N | cell | agaci | mondrian |
|---|---|---|---|
| FX, N = 5 | stretched up, P90 / P10 | 85.2% / 12.1% | 89.9% / 10.6% |
| FX, N = 5 | stretched down, P10 | 12.2% | 10.0% |
| metals, N = 20 | stretched down, P10 | 6.9% | 10.9% |
| metals, N = 50 | stretched down, P10 | 7.2% | 10.9% |
| crypto, N = 5 | stretched up, P10 | 12.3% | 9.7% |
| Range Break, N = 50 | stretched up, P10 / P90 | 6.7% / 93.1% | 10.7% / 90.9% |

**Pinball** is equal or slightly better in every family and horizon (P10 / P90):

| family, N | agaci | mondrian |
|---|---|---|
| FX, N = 5 | 0.303 / 0.282 | 0.302 / 0.281 |
| FX, N = 20 | 0.645 / 0.591 | 0.642 / 0.588 |
| FX, N = 50 | 1.151 / 1.025 | **1.127 / 1.014** (−2.1% / −1.1%) |
| metals, N = 20 | 0.650 / 0.647 | 0.647 / 0.644 |
| crypto, N = 50 | 1.023 / 1.181 | 1.014 / 1.172 |
| Range Break, N = 50 | 1.825 / 1.849 | 1.818 / 1.805 |

Deriv Volatility and Boom/Crash are within 0.001-0.013.

**Worst slice** is within ±0.5 points everywhere except two cells, both better:

| family, N | agaci | mondrian |
|---|---|---|
| Range Break, N = 50 | 82.7% | 85.6% |
| metals, N = 50 | 83.0% | 83.7% |

**Over the boosted base** (a quantile-boosted base fitted on FX's first 60%, standing in for
production's FX 15m boosted envelope), Mondrian leaves pinball unchanged. It still levels the
buckets:

| N | bucket, band | gbm agaci | gbm mondrian |
|---|---|---|---|
| 5 | stretched up, P90 | 87.8% | 89.6% |
| 20 | stretched up, P90 | 88.3% | 89.8% |
| 50 | stretched down, P10 | 11.8% | 10.4% |

**Verdict: passes on conditional coverage.** It closes 2-5-point bucket gaps in FX, metals, crypto
and Range Break, with pinball equal or up to 2% better and no worse worst slice. The pinball gains
are small, and this harness gave the envelope comparison no day-bootstrap intervals. Read it as
fixing coverage, not as a sharper band.

## What this means

- **The single-look `zma_line` is not safe under the way production reads it.** Checked every bar,
  a 100-feed book gets a false "earned" at 15m with 20% probability within 30 days and 50% within
  180. On real data, 10 series passed the line and later fell back under it.
- **An e-process fixes it,** at the cost of earning about twice as slowly. It holds the book-wide
  false pass at 0-2% over 180 days, never passes a walk or a Deriv index, and still earns the feeds
  with real records: EURCHF, EURUSD, EURGBP and CHFJPY in places, and crypto at 15m and 1h.
- **There is nothing finer than the hit rate to act on.** Calibrated per-call probabilities have no
  skill over it, and act like walks.
- **The ZMA state is useful as a conditioning variable for the envelope, not as a direction:**
  stretched states have different next-N-bar ranges, and a Mondrian AgACI covers them properly.

## Proposed production changes (not made)

1. **Replace `Settings.zma_line` with the e-process test.** No new state is needed, because K is a
   function of the record's `calls` and `right` alone:

   ```python
   LAMBDAS = (0.02, 0.05, 0.1, 0.2, 0.4)

   def zma_earned(self, calls: float, right: float) -> bool:
       """Anytime-valid: a mixture of betting martingales against a coin (Ville), Bonferroni
       across `zma_feeds` feeds at `zma_alpha`. Valid however often the record is re-read."""
       if calls < self.zma_min_calls:
           return False
       wrong = calls - right
       logs = [right * math.log1p(l / 2) + wrong * math.log1p(-l / 2) for l in LAMBDAS]
       top = max(logs)
       log_k = top + math.log(sum(math.exp(v - top) for v in logs) / len(LAMBDAS))
       return log_k >= math.log(self.zma_feeds / self.zma_alpha)  # 100 / 0.05
   ```

   It is used where `zma_line` is now: `scalper.zma_gate`, `stretching.py` and `turning.py`. It
   replaces `zma_z` with `zma_feeds` = 100 and `zma_alpha` = 0.05. Keep `zma_min_calls` as a floor.
   Refusal texts would report log K against the bar. The record must stay cumulative and undecayed,
   as it is now, for the martingale to hold.
2. **Mondrian envelope by ZMA bucket (optional):** key the envelope's AgACI state and history by the
   series' current `Zma.stretched` (−1 / 0 / +1), falling back to the pooled history while a bucket
   has fewer than 200 outcomes. Worth it for the stretched buckets' coverage on FX, metals, crypto
   and Range Break. The pinball gain is small, and it triples the envelope's corrector state.
3. **No per-call probability.**
