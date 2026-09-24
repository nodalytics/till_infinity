# Deriv's binary payouts, measured at last: a 2.41% house edge on a martingale, and a skew that is a constant

Run: `python research/harness/payout_logger.py --out <dir> --sweeps 1`

**Measured 2026-09-24**, on the first option prices this repository has ever held. 54 quotes, 54
successes, zero errors: eight symbols, four durations, both directions.

| question | answer |
| --- | --- |
| Deriv's API was down for three days | **no - it had migrated.** The old host is retired, not broken |
| margin on the volatility indices | **2.41%**, flat across every symbol and duration |
| margin on real instruments | **12.01% to 15.63%** |
| does the skew carry a directional view | **no.** It is `-0.00054 * sigma * sqrt(T)`, a constant |
| expectancy of a rise/fall on a synthetic | **-2.25% of stake, per contract**, by theorem plus this margin |
| Boom and Crash, the two designed asymmetries | **quote nothing.** Listed as tradable, no option sold |

## The endpoint was never down, and that cost three days

`payout_logger.py` shipped on 2026-09-21 unable to collect, and recorded the reason: Deriv's
WebSocket returned **HTTP 520** from three independent hosts, on every `app_id` and on the bare
root, while `api.deriv.com` answered normally. That was read as an outage on their side.

It still returns 520 today, from a residential connection in Lagos and from an AWS instance in
Mumbai, over both IP families, with correct WebSocket upgrade headers. It is not an outage. **The
`/websockets/v3` endpoint is retired**, and the options API now lives at

    wss://api.derivws.com/trading/v1/options/ws/public

which answers a handshake immediately, needs **no authentication and no `app_id`**, and speaks the
same `echo_req`/`msg_type` protocol. One field was renamed: `symbol` became `underlying_symbol`, and
the old spelling is rejected outright rather than ignored - which is the good failure, since a
silently dropped field would have logged a quote for the wrong instrument.

**The lesson is the transferable part.** A Cloudflare 520 means "the origin did not return a valid
response", which covers *broken* and *nothing is served here any more* equally. Two checks separate
them and neither was done: a real WebSocket handshake rather than a plain `GET`, and a look at which
endpoint the current documentation recommends. Three days were spent waiting for a recovery that was
never coming.

## The margin, which is the whole answer

`implied = stake / payout` is the break-even hit rate the broker is charging for. Quoting both
directions at the same instant separates the two things in it: the **margin**,
`implied(CALL) + implied(PUT) - 1`, which is a cost and identical whichever way you bet, and the
**skew**, `implied(CALL) - implied(PUT)`, which is the only part that could carry information.

| family | margin | break-even hit rate needed |
| --- | ---: | ---: |
| volatility indices (`R_10` ... `R_100`), all durations | **2.38-2.41%** | 51.0-51.3% |
| `frxEURUSD`, `frxGBPUSD` at 15m and 60m | **12.01-12.26%** | 55.3-57.0% |
| `frxXAUUSD` at 5m, 15m, 60m | **15.01-15.63%** | 55.9-**59.7%** |

Two readings, and both are terminal for the instrument as a directional bet.

**On the synthetics the margin meets a theorem.** [`deriving.md`](deriving.md) measures these
generators to be martingales and shows the drift bound is so loose the data cannot distinguish
`sigma^2/2` from zero. So the true probability of a rise is 0.500, the broker charges 0.512, and
expectancy is arithmetic rather than opinion:

    E = 0.500 * (10 / 0.5115) - 10 = -0.225   per $10 staked, or **-2.25%**

Per contract, at every duration. A one-minute contract loses 2.25% of stake per minute of exposure.
This is the same result `deriving.md` proves for spot - a martingale minus a cost - arriving through
a different door, and it is the reason that door was worth opening: the payout is an observable the
price series cannot contain, so it had to be measured rather than derived.

**On the real instruments the margin is the finding.** 12% to 15.6% means gold at five minutes needs
to be called correctly **55.9% to 59.7%** of the time to break even. This repository's whole
directional programme - [`directional-questions.md`](directional-questions.md), a 92-view ensemble
over price, volume, VIX, the dollar, calendar, order flow, gaps and events - found **nothing**
clearing costs at 15m, 1h or 1d, and its best out-of-sample information coefficient was +0.039
inside two standard errors. A 57% hit rate is not a stretch from that; it is a different universe.

## The skew is not a forecast, and that is measurable

The hypothesis this logger was built for was that the skew forecasts `sign(m)` over the contract's
duration. It does not, and the shape of it says so cleanly. Fitting the 20 volatility-index cells
against a spread proportional to volatility over the horizon, with `sigma` read off the index's own
name and `T` in minutes:

| symbol | 1m | 5m | 15m | 60m |
| --- | ---: | ---: | ---: | ---: |
| `R_10` | 0.0000 | 0.0000 | -0.0003 | -0.0005 |
| `R_25` | 0.0000 | -0.0003 | -0.0005 | -0.0010 |
| `R_50` | -0.0003 | -0.0005 | -0.0010 | -0.0021 |
| `R_75` | -0.0005 | -0.0010 | -0.0016 | -0.0031 |
| `R_100` | -0.0005 | -0.0010 | -0.0021 | -0.0042 |

Divide each by `sigma * sqrt(T)` and the table collapses to one number:

    k = skew / (sigma * sqrt(T)) = -0.00054   (median over 17 non-zero cells)

Twelve of the seventeen land on exactly `-0.00054` or `-0.00052`. **A directional forecast is not a
constant times `sigma * sqrt(T)`.** It is a fixed number of standard deviations - a spread, scaled
so it costs the same in risk terms on a 10-volatility index over a minute as on a 100-volatility
index over an hour.

**The scatter is quantisation, not disagreement**, and checking that matters because 42% spread
around the median would otherwise look like a real effect. Payouts are quoted to the cent on about
$19.55, so `implied` moves in steps of roughly `10 * 0.01 / 19.55**2` = 2.6e-5. A skew of 1e-4 is
four steps; a skew of 5e-5 is two, and rounds to zero. That is exactly where the zeros are - the
short durations on the low-volatility indices - and exactly where the ratio is least stable. The
cells with enough absolute skew to resolve are the ones that agree.

So the third and most interesting comparison this logger was built for is answered, negatively, from
the first sweep: **there is no directional information in the payout.** The margin was going to end
it and the skew ends it independently.

## What quotes, and what does not

Measured rather than assumed, because a request below a symbol's floor is refused and the logger
writes refusals into the data as rows - which only means something if an impossible combination is
never asked.

| symbol | quotes at |
| --- | --- |
| `R_10`, `R_25`, `R_50`, `R_75`, `R_100` | 1m, 5m, 15m, 60m, 1d |
| `frxXAUUSD` | 5m, 15m, 60m, 1d |
| `frxEURUSD`, `frxGBPUSD` | 15m, 60m, 1d |
| `BOOM1000`, `CRASH1000` | **nothing, at any duration tried** |

**Boom and Crash quoting nothing is worth recording.** They are the two synthetics with a
*designed* asymmetry, which [`susceptibility.md`](susceptibility.md) recovers at +0.136 and -0.136
through realised semivariance with zero on the symmetric indices - the cleanest positive control in
this folder. They were therefore the interesting ones to price, and the venue does not sell the
option. Listed as tradable, `exchange_is_open` true, no `CALL` at 1m, 5m, 15m, 60m or 1d.

**And one earlier claim in this session was wrong and is corrected here.** Reading
`contracts_for`'s `min_contract_duration` suggested every option on a real instrument was
`1d..365d`, which would have put the whole venue out of reach of a desk whose forecasts work at 1m
to 1h. Live proposals contradict the menu: gold quotes at five minutes. The menu was read too
confidently, and the check that settled it was asking for the quote.

## What this does and does not close

**Closed.** Rise/fall binaries, on both families, as a directional instrument. The synthetics by
theorem plus a 2.41% margin; the real instruments by a 12-15.6% margin against a directional
programme that has never cleared costs. No further data changes either, which is why this page is
short on caveats: the margin is not a small-sample estimate, it is a posted price.

**Not closed, and not touched here.**

* **`ACCU`, the accumulator.** It pays for price *staying inside a range*, so it is a bet on
  volatility being **low** rather than on direction - the one shape that matches what this desk can
  actually forecast. [`susceptibility.md`](susceptibility.md) found high `chi` predicts volatility
  **falling**, +5 to +9 points on five of seven instruments and surviving a trailing-volatility
  decile control. That is a specific pairing of a measured signal to an instrument and it is tested
  separately - see [`accumulators.md`](accumulators.md).
* **The barrier family on the volatility indices** - `ONETOUCH`, `NOTOUCH`, `EXPIRYRANGE`, `RANGE`,
  `UPORDOWN`, `TURBOS`, `VANILLA`. `deriving.md` derives a `Phi(-x)/Phi(-1.322x)` mispricing for any
  barrier product priced off a **Jump** index's name - 1.71x at one sigma - and **Deriv sells no
  barrier product on the Jumps**: `JD10` through `JD100` offer only `CALL`/`PUT` at 1d-365d,
  `DIGIT*` over 1-10 ticks, and multipliers. The volatility indices carry the whole barrier family
  and `deriving.md` measured *their* pricing as correct, at 1.007. So the mispricing and the
  instrument do not coexist, and that particular edge has no venue.
* **Whether the margin moves.** 2.41% was flat across 20 cells in one sweep. Whether it widens in a
  fast market is a question the logger answers by running, and it is the only reason to keep it
  running now that the headline is settled.
