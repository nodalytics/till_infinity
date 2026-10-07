# Order-block zones: an 82% return rate, a losing read, and a flip that is not yet settled

> **Corrected 2026-10-07, hours after the first version.** That version concluded the flip was
> "a standing short". It was not - the zone population it was measured on was **84% long
> because of a bug in this file's own `setups`**, and the zones themselves were 50/50 all
> along. The correction is in its own section below, and the superseded claims are struck
> through rather than deleted: a study that quietly rewrites its conclusion is worth less than
> one that shows where it went wrong.

**Measured 2026-10-07**, built to a specification the desk gave over the course of
one afternoon and run as each piece arrived. Code: [`zones.py`](../ideas/zones.py)
(`ZONES=ob`), [`test_zone_push.py`](../ideas/test_zone_push.py), plots in
`.data/zoneob/`. 4h (2018-07 to 2026-10) and 1d (2002 to 2026-10, the whole of
each in `mt5bt.db`), on twelve FX pairs, gold, silver, BTC and ETH.

> **The rule moved on the same evening.** The desk kept specifying after these
> numbers were measured: the strong push as the *gate* rather than a tag, a zone
> candle whose colour does not matter, the band drawn high to low instead of
> body-high, the line at the near edge of the body, a size test ("it is normally
> a small candle"), and a wick confirmation looser than a pinbar. The standing
> statement of the rule is [`zone-rules.md`](zone-rules.md); everything below was
> measured under the version in this section, and the sweep that re-measures it
> is [`zone_sweep.py`](../ideas/zone_sweep.py).

## The setup, as it was drawn when these numbers were taken

| part | rule |
|---|---|
| **origin** | the last candle *against* the move - for a demand zone, the last bearish one - with a body of at least `PUSH_BODY` of its range |
| **push** | `PUSH_N` consecutive candles after it, all the move's colour, each body `PUSH_BODY`+ of its range, **each** closing past the one before (its close, or its high for the strong form) |
| **imbalance** | required: a fair-value gap of 0.2 ATR+ on the leg, the first possible one being `low[p+2] > high[p]` - the hole the push leaves over the order block |
| **break of structure** | a close above the highest high of the last `OB_LOOKBACK` bars, holding 3 bars without a close back through and reaching 1 ATR past within 5. **No swing highs**: the desk asked for it without pivots, and removing them changed the hit rate by 0.4 points |
| **the level** | where the origin closed - in a continuous market, where the first push candle opened |
| **the return** | the first bar back in the band, up to 300 bars later: "the play might not happen immediately, it might happen later, even days ahead" |

## The verdict

| | |
|---|---|
| **Does price come back?** | **Yes, 82%** within 50 days. Read against [`magnet.md`](../../docs/magnet.md) first: levels are not magnets, and 50 days is long enough to wander back to most places. |
| **Does a break of structure follow a displacement?** | **No - only one in six.** 6,008 displacements at 4h produce 889 closes above the 20-bar high (14.8%), of which 515 hold (8.6%), of which 197 leave an imbalance (3.3%). 1d is 17.2 / 9.2 / 3.8%. The break is the biggest filter in the chain, not a formality. |
| **Does trading the return pay?** | **No.** 1d real **-0.259R** [-0.408, -0.100]; 4h real -0.117R [-0.340, +0.144]. Entered at market on the same fills it is worse: -0.597R and -0.462R. |
| **Does a stricter push help?** | **No, it hurts.** `PUSH_N` 3 takes 4h from +0.237 to **-0.227**. The strong form (close past the previous *high*) is worse than the weak one. `strong_leg`, the existing candle-quality filter, is worse than no filter at all (-0.275 against -0.194). Three separate ways of demanding more conviction, three times worse. |
| **Does the flip work?** | **Unsettled.** With the skew fixed it is **+0.337R** [+0.057, +0.627] on 1d and **+0.506R** [+0.192, +0.846] at 4h, positive in both directions and in all four half-samples - but each timeframe's confirmation half is weaker than its discovery half and neither is decisive alone. It is not the standing short this doc first called it. |

## The correction: an 84% long skew that was a dataclass

`setups` rebuilt each short zone **positionally**:

```python
zz = Zone(1, z.p, -z.lo, -z.hi, z.bos, -z.bos_level, z.fvg, z.live,
          -z.leg_extreme, z.clean, z.ret)
```

Adding `push`, `push_hi`, `ob` and `line` to `Zone` between `clean` and `ret`
moved `z.ret` into `push`. Every short zone therefore reached the trigger search
with `ret = -1`, found nothing, and vanished - so the **trades** came out 84%
long while the **zones** were 264 demand against 259 supply at 4h, 50/50.

It is now built by keyword, which cannot drift when a field is added, and
`test_a_mirrored_zone_keeps_its_return` pins it.

With it fixed, and the impulsive candles' body floor raised to 70% (the origin
keeps 45%, as `ORIGIN_BODY`):

| | 1d | 4h |
|---|---|---|
| population | 63% long / 37% short | **45% long / 55% short** |
| real | -0.283R [-0.447, -0.091] | -0.182R [-0.393, +0.048] |
| straight (same side, at market) | **-0.592R** [-0.732, -0.435] | **-0.519R** [-0.693, -0.315] |
| flip | **+0.337R** [+0.057, +0.627] | **+0.506R** [+0.192, +0.846] |
| flip, long leg | +0.056R | **+0.388R** |
| flip, short leg | +0.501R | +0.652R |

**The flip is positive in both directions**, which is what kills the standing-short
explanation: on the broken population the long leg was -0.41 and -0.44.

The split, with nothing chosen on the confirmation half:

| | discovery | confirmation |
|---|---|---|
| 1d flip | +0.275 [-0.112, +0.673] | **+0.397 [+0.014, +0.838]** |
| 4h flip | **+0.747 [+0.263, +1.280]** | +0.267 [-0.102, +0.657] |

Positive in all four, excluding zero in two, and `straight` significantly
negative in all four.

**What is claimed and what is not.** The durable finding is that *the real side
loses*: `straight` is -0.52 to -0.59 with intervals excluding zero everywhere.
Its opposite being positive follows arithmetically. That the flip is a
*tradeable* edge is **not** claimed here - each confirmation half is weaker than
its discovery half, and the rule has now been through enough variants that the
only honest next step is a frozen forward test on instruments it was never
developed on.

## ~~The flip, and why it is not an edge~~ (superseded - measured on the skewed population)

[`walks-and-edge.md`](walks-and-edge.md) names this case: when real sits below
its null, "the market punishes the chart reader's view ... the opposite trade
then becomes its own frozen test". The real side loses, so the flip was run.

It looked decisive - 1d **+0.740R**, 4h **+0.882R**, every interval excluding
zero in every half. Three things took it apart.

**1. The entry was not the same.** `R.coin` and the flip enter *at market*; a
real zone trade enters on a limit at the zone. "Real against flip" therefore
mixed the side with the entry style. A `straight` arm - same side, at market -
settled it, and the gap got *wider*, so this one survived.

**2. The zones were 100% long on daily.** `zones_ob` passes an already-mirrored
frame for the short side, exactly as `zones` does, so `side` is a tag and the
predicates inside must stay long-logic - which is why `strong_leg` takes no side
argument at all. Threading `side` into `strong_origin` and `sequential_push`
made them hunt a *bearish* origin and a *bearish* push on an already-negated
chart: wrong direction twice, and the supply side vanished. Every "flip" number
was therefore a standing short.

**3. A fast break made the imbalance unfindable.** The gap search ran
`range(p + 2, b + 1)`. When the break lands on the first push bar, `b = p + 1`
and that range is **empty** - so any setup that broke quickly was dropped in
silence, whatever it did. `long_zones` has the same line and does not hit it,
because its leg out of a pivot low takes longer to break.

With both fixed the population is 82-86% long rather than 96-100%, and the flip
separates:

| timeframe | flip ends up | n | mean R | win |
|---|---|---|---|---|
| 1d | **short** (a demand zone reversed) | 524 | **+0.564** | 42.7% |
| 1d | **long** (a supply zone reversed) | 83 | **-0.406** | 20.5% |
| 4h | **short** | 1,099 | **+0.588** | 34.5% |
| 4h | **long** | 235 | **-0.435** | 15.3% |

~~**The flip pays only when it ends up short.**~~ **This was the bug.** On the
corrected population the flip is positive both ways (+0.388R on the long leg at
4h, against -0.435R here). Everything in this section was measured on a trade
set that was 84% long because short zones had lost their `ret`.

The split finishes it. At 4h the flip goes from **+0.990R** [+0.570, +1.438] in
discovery to **-0.174R** [-0.401, +0.073] in confirmation. At 1d it holds
(+0.396 then +0.467) and 86% of it is short.

## What was already known, and is confirmed again

[`origin-zones.md`](origin-zones.md) asked the attribute question exhaustively -
BOS penetration, displacement, speed, efficiency, volatility surprise, force
against a random walk, structure crossed, gap size, the leg *into* the origin,
freshness, SMT, order flow, anchors, CUSUM, FOCuS. Its finding:

> **The force does not matter.** Every formation dimension ... is flat across
> its quartiles, in both periods. A model on formation alone scores AUC 0.548
> fitted and **0.510** on 2023-2026.

Nothing here contradicts that, and the three "stricter push" results above are
the same finding reached independently.

## What is still open

- **A break of structure *before* the zone.** "Structure crossed" in
  `origin-zones.md` is the break the displacement makes; a prior break
  establishing context does not appear in any fingerprint tested.
- ~~Why the zones are 82-86% long~~ **- answered: a positional `Zone` rebuild in
  `setups`. See the correction above.**
- **A frozen forward test of the flip**, on instruments the rule was never
  developed on - indices, energy, crypto alts, Deriv - and then on new bars.

## On the search

`PUSH_BODY` was run at 0.50 and 0.45, `PUSH_N` at 2 and 3, with and without
pivots, at two timeframes, four exits, five arms. That is a real search and the
count belongs beside the result: **no variant put the real side above its coin
twin**, and the one arm that looked like an edge was a bug and a direction.
