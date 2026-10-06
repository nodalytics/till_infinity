# Turn follow-ups: zones from turns, aged levels, and DISPLACE_C confirmed then traced to the market

**Measured, 2026-10-04.** These tests follow on from [turning-points.md](turning-points.md). Each rule
was frozen in a JSON committed before its run.

The results:
- **Zones built from violent turns:** no edge, whether turn-origin zones, counter-candle zones or
  long-waiting "fresh" levels, and whether or not the zone is conditioned on how price returns or on
  the higher timeframe. They trade like random walks on every asset class.
- **DISPLACE_C at a 12-bar low, with the structure exit:** passed a frozen test on 58 fresh coins,
  narrowly failed a second set of 73, and stayed positive on the daily in all three sets.
- **Where DISPLACE_C's edge lives:** a later study ([pca-residuals.md](pca-residuals.md)) found it sits
  entirely in the crypto market factor. A frozen rule that buys BTC on the alts' daily signal passed on
  two sets of coins it was not found on. It now runs forward in a paper log.

On reading the walk control, see [walks-and-edge.md](walks-and-edge.md). Matching the walks means the
trade reaches N R no more often than 1/(N+1), so its expected value is zero before costs. It does not
mean the pattern is fake.

**Correction carried from turning-points.md.** `turn_trade.ups` read the bearish BREACH_REVERT until it
was fixed today. The violent-origin flag (`SIG`) in sections 1 and 4 therefore included a wrong-side,
nearly empty T2. DISPLACE_C is unaffected.

**Re-run, 2026-10-05 ([turn-retrade.md](turn-retrade.md)).** With the corrected side, no verdict changes. The SIG
zone primary is −0.256R [−0.292, −0.221] (was −0.233), against −0.238 / −0.203 on walks. On fresh coins and SET_C,
the 4h and 1d SIG zones lose −0.14 to −0.33R. On Deriv, the corrected turns match the walks on the diffusive indices.
The gains on Boom/Crash/Jump and Range Break sit only on the side whose stop the jumps cross: bar fills miss the jumps.

## 1. The origin of a violent turn, as a zone (`ideas/turn_zones.py`, `turn_zone_rule.json`)

- **The zone:** [low, low + 0.5 ATR] at a 12-bar low.
- **Origin families:**
  - every low (ALL);
  - a violent turn bar (SIG);
  - a range shock in the top decile for its timeframe (RZ);
  - both (SIG_RZ).
- **When it goes live:** after a 3-ATR rally away from the low ("proven"), or a 1.5-ATR move ("left").
- **The trade:** first return only, a limit at the top of the zone, a stop 0.1 ATR under the low, and a
  2-ATR trail.
- **Data:** Binance and MT5, 1h/4h/1d, against iid and GARCH walks.

| primary: SIG, proven, trail, Binance | R | 90% |
|---|---|---|
| real | **−0.233** | [−0.277, −0.189] |
| every origin (ALL) | −0.241 | |
| iid / GARCH walk | −0.236 / −0.202 | |

It fails. The P(N R) curves of real data, iid walks and GARCH walks lie on top of each other on both
venues, with P(≥1R) about 0.45, P(≥4R) about 0.18 and P(≥10R) about 0.03. The best cell is MT5 SIG at
−0.125R, against −0.214R on iid walks and −0.156R on GARCH walks: still negative, and one of 48 cells.
In the gallery, losers usually return with one large bar straight through the zone.

## 2. A red candle among rising greens (`ideas/candle_zones.py`, `candle_zone_rule.json`)

- **The zone:** from the counter candle's low to its open, live after price leaves it by 1 ATR, traded
  on the first return in the run's direction.
- **Primary (K3: three greens either side, trail, Binance): −0.125R [−0.189, −0.062].** Any red candle
  gives −0.134R; the walks give −0.161R (iid) and −0.145R (GARCH). **Fails.**
- MT5 gives −0.140R and Deriv −0.091R, in line with the walks in both cases.

## 3. Fresh, long-waiting, untested levels (`aged_zones.py`, `aged_context.py`, `aged_volstop.py`, `aged_markets.py`)

The desk's idea: the market always comes back to a point it left violently, and delivers from fresh,
long-waiting, untested levels.

**The return is real, and so is it on walks.** 95–96% of proven zones are touched again within
180 days, on real data and on walks alike.

**Delivery fails.** Judged on the 58 fresh coins, 4h and 1d, with waits of up to 180 days:

| test (fresh coins, frozen primary) | real | iid / GARCH walk | baseline | verdict |
|---|---|---|---|---|
| aged: waited ≥ 10 days, trail | −0.187 [−0.246, −0.124] | −0.137 / −0.114 | wait < 2d −0.142 | fails |
| stop sized to volatility at the return (V1) | −0.180 [−0.242, −0.117] | −0.137 / −0.109 | −0.156 | fails |
| slow return, HTF aligned (v2, speed terciles) | −0.188 [−0.272, −0.103] | −0.127 / −0.064 | the rest −0.186 | fails |

- **Aged zones and the walks.** In-sample (Binance 12 and MT5), zones first tested after 10–20 days
  reached 2R at 0.36–0.38 against 0.29–0.33 on walks. On fresh coins they reach 2R slightly more often
  than walks (0.350 against 0.321), but lose more.
- **The volatility-at-return stop.** The idea was that volatility drifts while a zone waits. It
  doesn't: median ATR at the return is 0.87–0.91× the turn's ATR.
- **How the return arrives (`aged_context`).** The first frozen version used absolute speed cut-offs.
  A smoke test showed those labelled 90% of returns FAST and almost none SLOW. That version ran as
  frozen and failed on 742 trades (−0.174R [−0.42, +0.10]). Version 2 split speed into thirds and was
  frozen before its run.
- **The same three tests on FX, metals and Deriv (`aged_markets_rule.json`).** All nine judged
  verdicts fail, and real data sits on the walks:
  - FX, 9 unseen pairs: −0.162 / −0.184 / −0.155;
  - metals: −0.147 / −0.394 (424 trades) / −0.175;
  - Deriv diffusive: −0.098 / −0.270 / −0.109.

## 4. Violent turns on Deriv synthetics (`deriv_turns.py`)

- **The signature lifts by the same amount on real Deriv as on its walks:** DISPLACE_C at a low makes a
  major turn about 2.9× likelier on both.
- The turn trade and the turn-origin zones match the walks too.
- The jumpy indices show +0.27R on every low. That is the bar fills missing the jumps
  ([deriving.md](deriving.md)), not an edge.

## 5. DISPLACE_C at a 12-bar low, structure exit, on unseen coins (`turn_confirm.py`)

| frozen test | 4h+1d (primary) | 1d | 4h | walks (iid / GARCH) | every low |
|---|---|---|---|---|---|
| 58 fresh coins (`turn_confirm_rule.json`) | **+0.049 [+0.003, +0.100] passes** | +0.142 [+0.015, +0.280] | +0.036 | −0.019 / −0.005 | −0.115 |
| 73 more coins (`turn_confirm2_rule.json`) | +0.032 [−0.013, +0.080] fails | +0.112 [+0.003, +0.216] | +0.021 | −0.019 / −0.009 | −0.111 |

- **The original 12 coins on 1d:** +0.169R over 200 trades. **MT5 1d:** −0.035R, against −0.122R on its
  walks.
- **The tail is where the edge is.** On the fresh coins, P(≥4R) is 0.037 against 0.012 on walks.
- **Long and short:** both sides are positive, but longs are stronger. On 1d, longs make +0.24R and
  shorts +0.06R.

## 6. The edge is the market: buy BTC on the alts' daily signal (`market_mirror.py`, `market_mirror_rule.json`)

[pca-residuals.md](pca-residuals.md) split DISPLACE_C's return on the fresh coins:

| | R |
|---|---|
| total | +0.041 |
| market part | +0.056 |
| coin residual | −0.016 [−0.025, −0.006] |

The market part is positive on both sides, so the signal times turns of the whole crypto market.
Traded on the market instead, daily longs made +275 bps net on BTC [+26, +532]. That was read after
the run, so a rule was frozen:

- **M1:** when any alt completes DISPLACE_C up at a 12-bar low on the daily, buy BTC at the next open,
  and exit when the alt's own frozen trade exits.
- **M2:** the same on an equal-weight basket.
- **B:** on days when 3 or more coins signal, buy BTC and hold for 5 days.

**Historical check, on the 12 original coins as signal sources:**
- M1 makes **+371 bps net a trade [+32, +706]**: 97 trades on 53 days, +583 before 2024 and +240
  after.
- The same holds entered on random days make +54 (the 95th percentile is +169).
- **It passes.**
- B makes +141 bps over 12 days.

**Caveats:**
- The sample is small, and signals cluster because alts turn together.
- ETH's 5 signals carry part of the mean.

**Second check, on 274 Binance perpetuals no study had used** (SET_D, an addendum frozen before its
run; mostly younger listings):
- M1 makes **+281 bps net a trade [+75, +530]**: 991 trades on 288 days, +427 and +127 in the two
  halves of its own signal dates.
- The random-day twin makes +55 (the 95th percentile is +96).
- **It passes.**
- B makes +136 bps over 71 days.

Two independent sets of signal sources now agree: daily violent bullish turns on alts time BTC.
BTC's own drift is in the twin, so the excess over it is the signal. Every signal still trades the same
BTC path, so the forward log remains the test that matters.

## 7. Paper logs (lab)

- **`paper_displace.py`** logs every DISPLACE_C signal on the live fresh coins, 4h and 1d.
  - Price source: Binance spot through its public market-data mirror, with an OKX perpetual fallback.
    The lab cannot reach Bybit or Binance's main API.
  - `MODE=score` grades the alt trades. `MODE=market` grades M1, M2 and B forward.
  - The frozen forward bar is M1 net above 0 after at least 100 signals.
- **`paper_gapfade.py`** (from [mean-reversion.md](mean-reversion.md)) logs the FX weekend reopen. The
  gap fade is dead at tick level, so it now records real reopen spreads.

## Re-running

On the lab, with `OUT` and `MT5BT_DB` set:
- `turn_zones.py`, `candle_zones.py` and `deriv_turns.py` take `MODE=run|plot`.
- `turn_confirm.py` takes `MODE=fetch|run`. Set `SET=C` for the second replication.
- `aged_zones.py`, then `aged_context.py`, `aged_volstop.py` and `aged_markets.py`.
- `market_mirror.py`; use `SET=D CACHE=... MODE=fetch|run` for the unseen-coin check.
