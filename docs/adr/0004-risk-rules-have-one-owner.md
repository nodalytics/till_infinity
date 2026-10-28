# 0004. Risk rules have one owner, and a proposal carries measurements rather than decisions

- **Status:** Accepted (2026-10-28)
- **Date:** 2026-10-28
- **Depends on:** 0002, 0003

## Context

`statespace/proposing.py` publishes a payload that mixes two kinds of thing:

| field | what it is |
| --- | --- |
| `surprise`, `vol_bps`, `log_variance`, `spread`, `band_coverage` | **measurements** - what the model saw |
| `stop_vol: 2.0`, `target_r: 2.0`, `probability` | **decisions** - what to risk |

While one Python process owns both, that mixing is harmless: the strategy reads
them, `risk.Guard` checks them, and a bug anywhere is a bug in one test suite.

It stops being harmless the moment the producer is a different service in a
different language. A `stop_vol` taken on trust from another runtime is a real
position sized by code the trading service never tested. This desk's own record
says that is the likely failure and not a hypothetical one: `risk_vol` was
mistaken for a stop distance when it is a structures feature about a level, and
`probability_up` carried a 0.6365 that was overlapping touches and became
0.5092 once de-overlapped, with edge inheriting the error.

The reference architecture this was drawn from states the same rule for a
different domain: security rules have one owner, and the other language "never
takes a hospital or user from a payload; it takes them only from the verified
token."

## Decision

- **One service owns risk.** Gates, stop distance, target distance and size are
  derived in the trading service. No other service decides them.
- **A proposal carries measurements, not decisions.** A producer publishes what
  it measured and how sure it is. It does not publish what to risk.
- **Trading does not trust a risk field it did not derive.** Where a payload
  carries one today, trading re-derives it, and the payload's copy is recorded
  for comparison rather than used.
- **A model service carries no gates of its own**, with one exception that is
  not a gate on risk: a producer may decline to publish at all, which is what
  `TRIGGER` does in `proposing.py`. Declining to speak is not sizing a trade.

## Consequences

- `proposing.py` loses `stop_vol` and `target_r` from its payload, and
  `strategies/dispersing.py` keeps them as its own constants - which is where
  they already are (`stop_vol = 2.0`, `target_r = 2.0`, `reward_floor = 1.70`,
  measured against a 1.625 breakeven). The payload's versions were duplication
  waiting to diverge.
- `probability` stays, because it is a measurement - a *touch* probability from
  the readout's own barrier, not a win rate. Its name should say so.
- A contract test belongs on this: a proposal payload asserting that no risk
  field is present. Without one the rule decays the first time a producer finds
  it convenient to add a field.
