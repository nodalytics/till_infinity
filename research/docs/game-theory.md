# Game theory for this desk: what the ideas predict, what we measured, and what is left

A synthesis, not a new experiment. Every number here is from a page already in `research/docs`,
linked where it is used. Written 2026-09-29.

## The question

Trading is a game: our orders meet other people's, and a dealer or a broker sits between. Game
theory makes specific predictions about where the other players' behaviour leaves a trace we could
use: where stops cluster, when spreads widen, when crowds unwind, and who benefits from waiting.
This desk has tested most of those predictions without calling them game theory. This page puts
the predictions next to the measurements and asks two things:

1. Which of the game-theoretic ideas has the evidence supported, refuted, or not tested?
2. What, if anything, is worth building?

The short answer: **almost everything tested was a null or too small to pay its costs.** Two
effects are real but not tradable, and one is real and has already been acted on in production.

## The scoreboard

| concept | its prediction | what we measured | verdict |
|---|---|---|---|
| Focal points (Schelling) | orders cluster at round numbers and obvious levels, so price reacts there | round numbers turn price no more than placebo levels; crossing an FX big figure carries on 56.7% vs 54.1% (walks +1.2) | **the stop-cascade half supported, too small to trade; the "levels hold" half refuted** |
| Beauty contest / higher-order beliefs | price follows what others expect others to expect; surprises against consensus move price | the release surprise sets the bar's direction (rho +0.17 to +0.32) and is fully priced within 3 minutes | **supported, but already priced** |
| Stop-hunting / liquidity-seeking | informed flow runs price through stop clusters, then it reverses | no hunt at yesterday's high/low in FX (66.2% vs 67.7%); a trap's new extreme holds worse than a random price; a wider stop saves stops but not P&L | **mostly refuted as a trade; the "swept lows get taken again" half supported** |
| Market makers (Kyle, Glosten-Milgrom) | dealers widen spreads when adverse selection or inventory risk rises | spreads blow out at the 17:00 NY rollover and the Sunday open; the rollover spike was resolving 14.7% of FX touches | **supported, and acted on (the rollover mask)** |
| Crowding / coordination failure | crowded positioning unwinds against itself | crypto crowding composite -0.030 to -0.038 on the next 8h-3d; fading it: +41.5bp then -6.9bp; CFTC predicts nothing | **weakly supported in crypto, refuted in FX; nothing trades** |
| Winner's curse | the trades you win are the ones everyone else passed on | nothing the desk knows at order time separates winners from losers beyond noise | **not directly tested** |
| Second-mover / patience advantage | waiting for confirmation lets you trade after the uninformed are flushed | no lagging indicator beats entering at the touch or a random wait; MA/MACD waits cost 0.07-0.13 vol on FX 15m | **refuted for indicator-timed waiting so far; stop-hunt and confirmation tests running** |
| Mixed strategies / own predictability | predictable orders get exploited; randomising protects them | stops fill where placed except Boom/Crash's designed spikes; no evidence anyone trades against the desk | **not tested, and probably irrelevant at our size** |
| House vs player (Deriv) | where the broker sets the game, the house takes its margin and no predictable rule beats it | E[net] = -(c/2) x turnover, proven and verified 23 ways; binary margin 2.41%; Drift Switch is predictable but does not clear its spread | **supported: the only edge is structure the generator itself leaves, and it doesn't pay** |

## Each concept, against the evidence

### 1. Focal points (Schelling)

**The idea.** When players must coordinate without talking, they pick the obvious choice: a round
number, yesterday's high, a line everyone can see ([Schelling 1960](https://www.hup.harvard.edu/books/9780674840317)).
In FX, Osler showed that take-profit orders cluster *at* round numbers, which should make price
bounce there, and stop-loss orders cluster *just beyond* them, which should make price run once
it crosses ([Osler 2003, J. Finance](https://onlinelibrary.wiley.com/doi/10.1111/1540-6261.00604);
[Osler 2005, JIMF 24(2)](https://ideas.repec.org/a/eee/jimfin/v24y2005i2p219-241.html)).

**What we measured** ([`focal-points.md`](focal-points.md), [`rounding.md`](rounding.md), [`volumeprofile` in
`orderflow.md`](orderflow.md)):

| test | real | placebo | walks' gap | reading |
|---|---|---|---|---|
| FX round number bounces | 51.9% | 53.1% | - | no bounce |
| FX big figure, crossing carries on | **56.7%** | 54.1% | +1.2 | about 1.4 points beyond chance, both halves |
| its value | ~0.03 of a move | | | against a 0.46 spread |
| volume-profile levels (POC, HVN, LVN) | within 1.2 points of placebo (FX) | | crypto HVN +3.9 = walks' gap | no |

**Verdict.** The half of Osler that involves *stops* shows up: crossing an FX big figure keeps going
slightly more often than chance, which is the stop cascade. The half that involves *levels holding*
does not: round numbers, volume-profile levels and yesterday's extremes bounce like random prices.
Neither pays: 0.03 of a move against a 0.46 spread.

**Next step, if any.** None as a trade. As a feature, "just crossed a big figure" could go into the
break model and be scored for AUC against the walks, with a pre-registered bar of +0.01 AUC in both
halves. It is cheap, but expect nothing.

### 2. Keynes's beauty contest and higher-order beliefs

**The idea.** A short-horizon trader cares about what others will think, not what the asset is
worth ([Keynes 1936, ch. 12](https://www.marxists.org/reference/subject/economics/keynes/general-theory/ch12.htm);
[Allen, Morris & Shin 2006, RFS 19(3)](https://academic.oup.com/rfs/article-abstract/19/3/719/1646731)).
The public forecast gets too much weight, so price reacts to the *gap* between the release and the
consensus, not to the level.

**What we measured** ([`surprise.md`](surprise.md)): on 51,354 releases, the surprise against
consensus sets the release bar's direction at rho **+0.17 / +0.21 / +0.32** (all / medium+high /
high impact). A zero-surprise print still moves 1.6x a normal bar. On 3m bars the whole reaction is
inside the first 3 minutes (+0.231), and 3-60m is -0.025.

**Verdict.** Supported: price moves on the gap between expectation and reality, exactly as the
beauty contest predicts. But the market prices it in 3 minutes, faster than this desk can act.

**Next step.** Not a trade. It is already useful as a **news gate**: do not open a trade in the
minutes around a high-impact release (`TRADING_NEWS_BEFORE_S` / `AFTER_S` exist). A test worth
running: the desk's own R on trades opened within 5 minutes of a release against matched trades
outside, on the journal, with a pre-registered -0.1R difference.

### 3. Stop-hunting as a game between informed and uninformed flow

**The idea.** Resting stops are known liquidity. A trader who needs to fill size, or who wants to
buy cheap, can push price through a stop cluster, fill against the forced sellers, and let price
come back. For the stopped traders this is the complaint "stopped out, then it went my way". The
predatory-trading model ([Brunnermeier & Pedersen 2005, J. Finance 60(4)](https://ideas.repec.org/a/bla/jfinan/v60y2005i4p1825-1863.html))
formalises the general version: when one side must trade, others trade ahead of it and profit from
the overshoot.

**What we measured**:

| test | result | doc |
|---|---|---|
| stop hunt at yesterday's high/low, FX | 66.2% vs placebo 67.7% | [`focal-points.md`](focal-points.md) |
| crypto, same | +7 points, inside the walks' +4.8 | [`focal-points.md`](focal-points.md) |
| a trap's new extreme as a level | holds *worse* than placebo (metals/crypto 1h 44.6% / 46.2% vs 53.1% / 51.5%) | [`trap-levels.md`](trap-levels.md) |
| the trap's midpoint | beats placebo in 6 of 6 real cells by 1.1-3.8 points, walks nothing, worth ~0.02-0.08 of a move | [`trap-levels.md`](trap-levels.md) |
| fading the trap at confirmation | 48.6-51.1% | [`trap-levels.md`](trap-levels.md) |
| production's stops | 20 of 27 judgeable stopped trades never reached target; 7 were stopped early | [`stops.md`](stops.md) |
| a 1.5-3x wider stop at constant risk | stopped share 45% -> 21% (barrier), price P&L flat: +0.180 at 1x, +0.177 at 3x | [`widestop.md`](widestop.md) |
| the hold label on noise | production reads 55.0% on a random walk against 49.9% symmetric; the ratcheting origin is the whole 5.1 points | [`holdlabel.md`](holdlabel.md) |

**Verdict.** The *existence* of sweeps is supported: swept lows get taken again, and the trap's
extreme is a worse level than a random price. The *profitable reversal* after a sweep is not: fading
the trap is a coin flip. The desk's own "stopped then right" complaint is real in frequency (7 of 27)
but not in money. A wider stop saves those trades and loses as much on the ones that keep going.

**Next step.** Already running: the stop-hunt study (`research/harness/stophunt.py`) tests a
sweep-and-reclaim entry and production's candle confirmation against the touch and a random wait,
on our walks too. Its pre-registered bar: lower stop-outs *and* lower stopped-then-right *and* +0.05R
net with t >= 3 in both halves.

### 4. Market makers: Kyle and Glosten-Milgrom

**The idea.** A dealer quoting to a mix of informed and uninformed traders loses to the informed,
so it widens the spread when the share of informed flow, or its own inventory risk, rises
([Glosten & Milgrom 1985, JFE 14(1)](https://doi.org/10.1016/0304-405X(85)90044-3);
[Kyle 1985, Econometrica 53(6)](https://doi.org/10.2307/1913210)). Predictions: spreads widen at
information events, and at times when liquidity is thin and positions must be rolled.

**What we measured**:

| where | what | doc |
|---|---|---|
| the 17:00 New York rollover | 14.7% of weekday FX call outcomes resolve at 21:00 UTC (2.5-6.7% in any other hour); traps 19%, breaks 1%; on FX 15m/30m 41-46% of outcomes land in 21-22 UTC | [`rollover.md`](rollover.md) |
| the Sunday open | recorded spread 0.6-7.6 bps against 0.0-0.5 on weekdays | [`gaptrade.md`](gaptrade.md) |
| FX hour of day | the only persistent pattern is 20-23 UTC, the NY close and rollover; Ranaldo's home-hours depreciation fails (-0.0073, t -1.4) | [`fxtod.md`](fxtod.md) |
| Deriv's crypto quote | lags the exchanges by +1.3 bps, and so does every exchange; the spread is 2.39 bps against Binance's 0.001 | [`lagging.md`](lagging.md) |
| what separates winning trades | the one survivor: spread as a share of the trade's own risk, +0.369R cheap-minus-expensive | [`winning.md`](winning.md) |

**Verdict.** Supported, and it is the most useful idea on this page. The dealer's spread is where
the game shows up in our data. It widens at the rollover and the weekend open, where the dealer's
risk is highest, and it decides which of our trades win. It also contaminated what the engine
learned: the rollover spike was being read as real touches.

**Already acted on.** `structures/rollover.py` masks the FX rollover, trims its wick from bars and
fades records learned before the mask. A lab replay of mask on against mask off is running. The
spread-to-risk gate in `winning.md` is the other application: gate on spread as a share of *risk*,
not reward.

**Next step.** Add a **spread-regime gate** to the confirmation layer: refuse a confirmed signal when
the current spread is above its hour-of-week median by more than a pre-registered multiple (say
2x). Test it on the journal: R of trades taken above that multiple against below, with bootstrap
over days.

### 5. Crowding and coordination failure

**The idea.** When too many traders hold the same position, any shock forces them out together.
The unwind overshoots, and positioning measures (funding, open interest, COT) should predict
reversals ([Stein 2009, J. Finance 64(4)](https://doi.org/10.1111/j.1540-6261.2009.01483.x);
[Brunnermeier & Pedersen 2005](https://ideas.repec.org/a/bla/jfinan/v60y2005i4p1825-1863.html)).

**What we measured** ([`crowding.md`](crowding.md), [`atlas.md`](atlas.md)): on 10 Binance
perpetuals, a composite of funding, long/short and OI change correlates **-0.030 to -0.038** with
the next 8h to 3 days, in both halves (about 1.5 SE). Fading its extremes for a day made **+17.4 bp**,
all in the first half (+41.5 / -6.9). The cross-sectional funding trade made 2.9 bp against 4.8 bp
of costs. CFTC positioning predicts nothing at 1-13 weeks.

**Verdict.** The sign is right in crypto and nowhere else, and it does not pay. Coordination failure
exists but is priced.

**Next step.** None as a trade. At most a **risk flag**: when the crypto composite is in its top
decile, halve size on crypto trades in the crowded direction. That needs a pre-registered R test on
the journal first, and there are few crypto trades.

### 6. The winner's curse

**The idea.** In a common-value auction the winner is the bidder who overestimated most
([Thaler 1988, JEP 2(1)](https://www.aeaweb.org/articles?id=10.1257/jep.2.1.191)). For a trader:
the limit orders that fill are disproportionately the ones better-informed traders were happy to
take the other side of. The desk's fills are selected against it.

**What we measured.** Not directly. [`winning.md`](winning.md) found nothing the desk knows at order
time separates winners from losers beyond a permutation control (largest gap 0.433 against a noise
median of 0.374). [`spending.md`](spending.md) found real-market closes at **-22.2%** of risk
deployed [-36.7%, -7.5%], with wins at 54% of their risk and losses at 78%.

**Verdict.** Untested. The losses are consistent with adverse selection but don't prove it.

**Next step.** A direct test on the journal: for limit entries (`entry_wanted` vs `entry_filled`),
compare the R of trades that filled against the *hypothetical* R of signals whose limit was never
reached, using the same stop and target on the bars. If fills do worse than misses by more than
0.1R with bootstrap over days, the curse is real, and the confirmation layer should prefer market
entries on confirmed signals.

### 7. The second mover and the value of patience

**The idea.** In limit-order markets, patient traders supply liquidity and earn the spread;
impatient ones pay it ([Foucault, Kadan & Kandel 2005, RFS 18(4)](https://academic.oup.com/rfs/article-abstract/18/4/1171/1595760);
[Parlour 1998, RFS 11(4)](https://doi.org/10.1093/rfs/11.4.789)). In the stop-hunt story,
the patient trader enters after the sweep and pays less. This is the idea behind the desk's wish
for confirmation before entry.

**What we measured** ([`indicators.md`](indicators.md)): on 44,732 real-market and 29,188 Deriv zone
touches, no lagging indicator beats entering at the touch and a path-independent random wait. Only 4
of about 170 comparisons reach |t| >= 2, one of them on our own walks. Waiting for an EMA, SMA or
MACD reclaim on FX 15m **costs** 0.07-0.13 vol per trade (t -3.0 to -4.0, both halves).

**Verdict.** Refuted so far, for indicator-timed waiting. Waiting for a reclaim means paying for the
move that confirmed it, the opposite of the patience premium. The premium in the theory comes from
*supplying* liquidity (limit orders), not from waiting to *take* it.

**Next step.** Running: `stophunt.py` and `confirm.py` test sweep-and-reclaim, production's candle
confirmation, 30+ other indicators, a learned confirmer, and higher-timeframe signals confirmed on
lower timeframes. A limit-order version is worth adding: enter with a limit at the level after a
confirmed signal instead of at the market after the confirmation, scored the same way.

### 8. Mixed strategies and the desk's own predictability

**The idea.** A player whose moves can be predicted can be exploited, so equilibrium play is often
random. Kyle's informed trader hides in the noise: it trades in proportion to its edge, so its
orders cannot be told apart from uninformed flow ([Kyle 1985](https://doi.org/10.2307/1913210)).
For a desk: stops at obvious places, entries at the same bar every time and fixed-size orders are
patterns someone else could trade against.

**What we measured.** Nothing directly. [`generators.md`](generators.md) found stops on the spike
side of Boom/Crash fill **10-19R** past where they were placed, but that is the generator's designed
jump, not someone hunting our stop. On real markets nothing suggests anyone trades against orders
of our size.

**Verdict.** Not tested, and probably irrelevant at this size. Randomising matters when your flow is
large enough to be seen.

**Next step.** None now. If size grows, a simple guard costs nothing: jitter stops by a random
0-0.25 vol beyond the structure point, and measure on the journal that it does not change R.

### 9. The house versus the player: Deriv synthetics

**The idea.** When one player writes the rules and sets the payouts, as a casino does, equilibrium
says the house prices every bet to keep its margin. The player's only hope is a flaw the house did
not price. Deriv sets both the generators and the payouts on its synthetics. They are still a real
market to trade (they are traded, and the feed is what it is), but the game is house vs player.

**What we measured**:

| finding | number | doc |
|---|---|---|
| the generators are what Deriv publishes | realised vol = the name within 0.49% on 12 of 12; Step is a fair coin, p = 0.499734 +- 0.000220 over 5.2M flips | [`generators.md`](generators.md) |
| any predictable rule on a martingale | E[net] = -(c/2) x turnover, verified 23 ways, max \|z\| 1.84 | [`deriving.md`](deriving.md) |
| the binary options margin | 2.41% on the volatility indices, flat; 12.0-15.6% on real instruments | [`deriv-payouts.md`](deriv-payouts.md) |
| the one non-martingale | Drift Switch acf1 +0.1525 (t +34.1), but an AR(1) clears only 0.103-0.692 of the spread | [`families.md`](families.md) |
| where the book's closes are | 43% on instruments `deriving.md` proves cannot pay | [`spending.md`](spending.md) |

**Verdict.** Supported, strongly. The house priced the game correctly. On the martingale indices no
entry, stop, target or filter can earn more than minus the spread. The only structure found (Drift
Switch) is real but smaller than the spread the house charges on it.

**Next step.** Keep treating Deriv as a real market in every test, with walks we generate as the
null. For trading, the result says: expect nothing from timing or entry rules on the volatility
indices. Any Deriv work should target structure the generator leaves (Drift Switch, Boom/Crash
spike timing) and must clear the spread by a pre-registered margin before it trades.

## What this means

- **Game theory predicts where the other players leave traces; the market has already priced almost
  all of them.** Focal-point stops, the beauty-contest surprise, crowding and the sweep all show up
  as real effects in our data. None is big enough, or slow enough, to pay the desk's costs.
- **The dealer is the player that matters to us.** The spread is where Glosten-Milgrom shows up. It
  widens at the rollover and the Sunday open, it decides which trades win, and it was corrupting the
  engine's level statistics. This is the one place the theory has already changed production.
- **Patience pays for liquidity providers, not for traders waiting on a lagging signal.** Our tests
  of waiting for an indicator found that it costs. Whether waiting for a *sweep* pays is being tested
  now.
- **On Deriv the house wins by construction.** That is a theorem here, not an opinion.
- **Most tests were nulls,** and the page should be read that way. The value is in knowing which
  stories not to build on.

## Applications for us

Ranked by expected value against cost:

1. **Spread-aware gates in the confirmation layer (build).** Refuse or down-size a confirmed signal
   when the spread is wide relative to the trade's *risk* (`winning.md`'s one survivor) or to its
   hour-of-week norm (rollover, Sunday open). This is the game theory the data supports.
2. **Keep the FX rollover mask, and add the Sunday-open window to it if the replay supports it
   (measure).** Same mechanism, same fix.
3. **Wait for stophunt.md and confirm.md (running).** If a sweep-and-reclaim or candle-confirmed
   entry passes its bar, it becomes the confirmation layer's entry rule. If not, the layer should be
   a *veto* (spread, news, crowding), not a timer.
4. **Winner's-curse test on limit fills (test, cheap).** It decides whether the layer should enter
   with limits or at market.
5. **News-window gate (already exists; verify).** Check the desk's R around releases on the
   journal.
6. **Crowding as a crypto size flag (test only if crypto trading grows).**
7. **Drop:** round-number and volume-profile levels as trade signals, fading traps, trading the
   release after the first minutes, crowding as a trade, randomised stops at current size, and any
   timing rule on the Deriv volatility indices.

**How this plugs into the confirmation layer.** The planned layer sits between a structures signal
(any timeframe) and the trading models. Game theory suggests it should do two jobs, in this order:

1. **A veto for bad games,** where the other player has the edge:
   - the spread is wide relative to risk, or relative to its hour-of-week norm;
   - it is the rollover or the weekend open;
   - a high-impact release is minutes away;
   - optionally, the crowd is extreme in crypto.

   These checks are cheap and grounded in what we measured.
2. **A timer,** only if `stophunt.md` or `confirm.md` finds one that passes its bar: the
   sweep-and-reclaim, a candle confirmation, or a higher-timeframe signal confirmed on a lower one.
   Until then, the models' own entry plans should stay.

## References

- Schelling, T. (1960). *The Strategy of Conflict.* Harvard University Press.
- Osler, C. (2003). Currency orders and exchange rate dynamics: an explanation for the predictive
  success of technical analysis. *Journal of Finance* 58(5).
- Osler, C. (2005). [Stop-loss orders and price cascades in currency markets](https://ideas.repec.org/a/eee/jimfin/v24y2005i2p219-241.html).
  *Journal of International Money and Finance* 24(2), 219-241.
- Keynes, J. M. (1936). *The General Theory of Employment, Interest and Money*, ch. 12.
- Allen, F., Morris, S. & Shin, H. S. (2006). [Beauty contests and iterated expectations in asset
  markets](https://academic.oup.com/rfs/article-abstract/19/3/719/1646731). *Review of Financial
  Studies* 19(3), 719-752.
- Brunnermeier, M. & Pedersen, L. (2005). [Predatory trading](https://ideas.repec.org/a/bla/jfinan/v60y2005i4p1825-1863.html).
  *Journal of Finance* 60(4), 1825-1863.
- Glosten, L. & Milgrom, P. (1985). Bid, ask and transaction prices in a specialist market with
  heterogeneously informed traders. *Journal of Financial Economics* 14(1), 71-100.
- Kyle, A. (1985). Continuous auctions and insider trading. *Econometrica* 53(6), 1315-1335.
- Stein, J. (2009). Presidential address: sophisticated investors and market efficiency. *Journal
  of Finance* 64(4), 1517-1548.
- Thaler, R. (1988). Anomalies: the winner's curse. *Journal of Economic Perspectives* 2(1), 191-202.
- Parlour, C. (1998). Price dynamics in limit order markets. *Review of Financial Studies* 11(4),
  789-816.
- Foucault, T., Kadan, O. & Kandel, E. (2005). [Limit order book as a market for liquidity](https://academic.oup.com/rfs/article-abstract/18/4/1171/1595760).
  *Review of Financial Studies* 18(4), 1171-1217.
- Breedon, F. & Ranaldo, A. (2013). [Intraday patterns in FX returns and order flow](https://econpapers.repec.org/article/mcbjmoncb/v_3a45_3ay_3a2013_3ai_3a5_3ap_3a953-965.htm).
  *Journal of Money, Credit and Banking* 45(5), 953-965.
