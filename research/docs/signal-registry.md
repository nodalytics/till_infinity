# Every signal at or above 51%, and what happened to each

**Shipped 2026-09-22.** `till_infinity/structures/context/registry.py`, tested in
`tests/test_registry.py`.

The desk asked for all of it:

> *from all the stuffs we have been playing with since, take the ones whose signal strength >=51%
> and add them to production* [...] *we don't only need the strongest, we need all >=51% signal*

That is the ensemble argument - individually weak, jointly maybe not - and it is a good one. This
page is the audit behind it: every candidate in this folder measured at or above 51%, what it was
measured on, and whether it is in the registry, already live, or excluded and why.

## The bar, stated honestly before the list

**51% is below the cost line for a directional trade on this book.** A 51% hit rate at even money
earns 0.02 of a unit per trade gross; `spread_cost.py` measured 0.020 TR a leg, so 0.040 round
trip. The gross edge is half the cost. Nothing at 51% pays as a trade.

So the registry does not trade them. It **computes them, publishes them, and scores each one
live against the backtest that claimed it** - which is the thing this folder has never been
arranged to do, and the reason so many of its positives decayed unnoticed. A signal earns weight
in the ensemble from its *live* separation, not from the number below, and loses it again without
anyone editing a table.

Two of the entries clear the bar by enough to matter on their own. The rest are carried because
the desk asked for all of them.

## In the registry

`sense` is `-1` where a larger reading means the level is **less** likely to break. Three of the
seven are negative and two of those are the strongest, which is why orientation is done once
inside the registry and pinned by a test.

| signal | strength | sense | measured on | note |
| --- | ---: | :---: | --- | --- |
| **`clock`** | **0.778** | + | 312,420 journal resolutions | elapsed time. New, largest, and its input is free |
| `experience` | 0.624 | − | 312,420 | AUC 0.3764 read inverted |
| `strength` | 0.608 | − | 312,420 | AUC 0.3924 read inverted |
| `depth_vol` | 0.562 | − | 10,904 in band / 312,420 | AUC 0.4180 in band, 0.4379 unconditional |
| `slowing` | 0.543 | + | 4,078 / 224,278 | nearly orthogonal to arrival speed, r = +0.008 |
| `approach_vol` | 0.525 | + | 10,871 / 312,420 | the desk's own claim: how hard price arrives |
| `slope` | 0.505 | + | 10,869 | magnitude only, and only worth carrying **paired** with `prior_slope` |

`clock` is the one that is new. `P(break | the touch is still open at t)` runs from **14.4% at
open to 77.8% at ten bars** on 1m, monotone, and crosses even money at four to seven bars of the
level's own timeframe on every timeframe from 1m to 30m - a thirtyfold span, so the rule is
scale-free with one parameter. Full derivation and the table in
[`break-trade.md`](break-trade.md).

It is also the only entry whose input costs nothing: *"resolution took at least t"* and *"still
open at t"* are the same event, so a table built on finished touches is one a live timer can act
on. Every other conditional in this folder needs to know how the touch ended.

## Already live, and not duplicated here

| signal | strength | where |
| --- | ---: | --- |
| the joint break model | **AUC 0.658**, 0.7542 with `interval_log` | `learning/breaking.py` |
| `interval_log` | AUC 0.7396 alone | same, and see the correction below |
| trend efficiency | 1.4% break share in the top decile against 11.3% in chop, 0.34R | `context/trend.py` |

**A correction to something this folder has said twice, including in my own report.** The code
comment on `Breaks` says it *"publishes a number and decides nothing"*, and I repeated that. The
**live instance carries `TRADING_MAX_BREAK_RISK=0.35`**, so the gate is on and the model is
actively refusing level calls. The default in `config.py` is 0.0; the deployed environment is not
the default, and - exactly as with `TRADING_STOP_SLIPPAGE` - the repository's copy of the
environment is not the environment. Read it off the instance.

`interval_log`'s published ladder needs the same caution as everything else measured in the
300-1,800s band: the **level** of it is a selection effect, though the ordering survives. See
[`break-trade.md`](break-trade.md).

## Above 51% and excluded, with the reason

These are the ones a naive reading of the bar would have shipped. Each is excluded for a stated
reason rather than on taste.

| candidate | strength | why not |
| --- | ---: | --- |
| constructed cross-venue spread | **AUC 0.70** | **unreachable.** Needs an account at each venue; this desk has one broker. And the deviation has a **sub-second half-life** |
| `turns.md` trend exhaustion | AUC 0.595 [0.540, 0.654] | **real but unbuilt, and on the wrong clock.** Daily bars, horizon of weeks, against a desk that now trades 1m-1h. The audit also notes `vol` alone at 0.604 is the top of a ten-signal scan and **two of fourteen instruments score below 0.5** |
| `strength.md` same-side record | **+32.8 points on the corrected code** | not excluded on the denominator - **corrected 2026-09-23, see below.** It is in the *direction* model and not in `Breaks`, and the two disagree about it |
| `strength.md` `Level.strength` itself | +6.1 points corrected, flat until the top quartile | the blend is much weaker than the record inside it. `strength` is now in `Breaks` on a *separate* measurement (AUC 0.6076 unconditional) rather than on this one |
| sequence models on the Volatility family | AUC 0.5310, 0.5801 | **provably null.** `deriving.md` proves `E[net] = -(c/2) x turnover` on a martingale and a Volatility index is GBM at a published constant sigma, so anything above 0.50 on direction is first a bug. The one positive symbol was the mirror of the one that could not be pulled |
| echo state networks, same family | 0.5743 | same reason - "highest AUC in the family" on a constant-sigma synthetic |
| `controls.md` AUC deviation | 0.5889 | that number **is** the null calibration spread, not a signal |
| `families.md` next-bar sign | 0.5143-0.5506 | measured on a **positive control** - a simulation at fitted parameters where the true regime path is known. It is the method's ceiling, not a reading of any market |
| banded "is a move coming" | AUC 0.573 | **not direction.** It forecasts whether a move is large enough to pay, which buys sizing and not a filter - filtering a coin flip leaves a coin flip. And 86.0% of 1m calls never clear a 4bp band |
| analogue / similarity twins | 50.0-50.6% | **below the bar.** Four distance metrics within 0.8 points of each other; the envelope is wider than a trailing sigma at equal coverage |
| `losing.md` 52% | — | an identity: hit rate falls exactly as fast as payoff rises |

## A correction to this page, 2026-09-23

An earlier version of the table above excluded `strength.md`'s +32.8 points as *"measured with a
broken denominator"*. **That was wrong and the direction was backwards.**

`strength.md` already carries a corrected-code run - same six instruments, 2,864 decisive
interactions on the fixed `vol.bps` - and **+32.8 is the corrected number.** The pre-fix figure was
+15.6. The same-side record signal *survives and strengthens* through the fix; what the fix
**weakens** is everything else on that page:

| signal | pre-fix | corrected |
| --- | ---: | ---: |
| same-side record, worst to best bucket | +15.6 | **+32.8** |
| `experience`, q1 to q4 | +14.9 | +5.8, flat until the top |
| `Level.strength`, q1 to q4 | +12.2 | +6.1, flat until the top |
| instrument spread | 19.0 points | 7.0 points |
| origin ordering | pip best | **inverts** - run-only best |

So the denominator caveat belongs on the *weak* rows, not on the strong one. What remains genuinely
open is the sample: 2,864 decisive interactions over 800 bars, against the 320,811 resolutions the
journal now holds.

### And a contradiction the correction exposes

`strength.md` says the **same-side record** separates hold from break by **32.8 points**.
`breaking.py` says `up_rate` - which *is* the same-side record - predicts a break at **AUC 0.4892**,
and excludes it on that basis.

Both cannot be right, and they are measured on different samples with different labels. Resolving it
is the first thing to run on the journal rather than on stored history.

## The one live defect this audit turned up

`winning.md` pre-registered a survivor and it is still mis-wired. **Spread as a share of the
trade's own risk** was worth +0.369R cheap-minus-expensive, p<0.001 permuted within feed, 9 of 9
strata - and the gate that ships measures spread against the **reward** instead. 49 trades passed
that gate and lost **0.471R each**.

That is realised money and a one-line fix, and it is worth more than anything in the table above.
It is not in the registry because it is not a signal to score - it is a bug to fix.

## What the registry does not do

It does not size, gate, or refuse anything. The ensemble returns `None` until a signal has 500
live resolutions behind it and has separated by at least two AUC-equivalent points, so after a
fresh deploy it says nothing for a long while - which is correct, and is the same shape as
handlers arming after backfill rather than a fault.

Promoting it to a decision needs the shadow counterfactual `bandits.md` argues for: run it live,
record what it would have overruled, and price that on real fills. The arithmetic it has to clear
is `paying.md`'s, and at 0.040 TR round trip the bar is a long way above 51%.
