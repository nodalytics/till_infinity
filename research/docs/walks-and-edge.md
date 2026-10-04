# What the random-walk control means, and what it does not

**A note on method, 2026-10-04.** It came from a correction by the desk. Several studies had called a
pattern's improvement "an artefact" or "geometry" because the same pattern did as well on matched
random walks. That was the wrong word.

## The lesson

"Artefact" was the wrong word. It is kept only for genuine measurement bugs (look-ahead, fill errors,
cost scaling). **Matching the walks does not make a pattern fake.** Markets are close to random walks,
so most patterns *should* look similar on both. A walk produces the same shapes: displacement, sweeps,
breaks, origins, returns. The walk is not there to call a pattern false. It is the yardstick for
whether trading the pattern can make money.

## Why the walk is still the yardstick

On a random walk, every exit rule has the same expected value: zero before costs, whatever its
reward:risk. The chance of reaching +N R before −1R is exactly 1/(N+1):

| target | P(win) on a walk | expected value |
|---|---|---|
| 1R | 50% | 0.50 × 1 − 0.50 × 1 = 0 |
| 4R | 20% | 0.20 × 4 − 0.80 × 1 = 0 |
| 10R | 9.1% | 0.091 × 10 − 0.909 × 1 = 0 |

A high-R:R rule on a walk pays for its big winners with a lower hit rate, exactly. After the spread it
is slightly negative ([deriving.md](deriving.md): `E[net] = −(c/2) × turnover`). **R:R alone cannot
make money. What makes money is beating 1/(N+1).**

So when a pattern "matches the walks", say it plainly. Its trades reach high R no more often than
randomness allows, so its expected value before costs is zero. That says nothing about whether the
pattern is real. It only says this trade on it has no edge.

## What the desk is looking for

A pattern, rare or common, whose P(≥ N R) at large N (4, 5, 10, 20) **exceeds both 1/(N+1) and the
same pattern on matched walks**, on data it was not found on. One that fires twice a month and
reaches 10R 15% of the time, against 9% on walks, is a real edge. The best strategies are often the
simple ones, and an edge in the tail is enough.

The method is built to catch exactly that. Every study reports P(N R) against 1/(N+1) and against
the walks, and leads with the tail. Examples so far:

- **DISPLACE_C at a 12-bar low** ([turning-points.md](turning-points.md), fresh coins) reached 4R
  3.7% of the time, against 1.2% on walks: three times the random rate in the tail. It is the one
  result that has survived a frozen test on unseen data. It is thin and not yet confirmed (a second
  set gave +0.032R [−0.013, +0.080]).
- **The turn trade with market exits.** Its lift over "buy every low" also showed up on walks, and
  its P(N R) curve sat on the walk's. That means zero edge before costs, not a broken pattern.

## How to report it

- **Lead with tail excess:** real P(≥ N R) minus the walk's, and against 1/(N+1), at the N the trade
  is built for.
- **Say "matches the walk: no edge before costs"**, not "artefact" or "only geometry".
- **Keep the walk null.** Without it, a 1:10 rule winning 9% of the time looks like a strategy.
- **Use walks that keep what real markets have** (GARCH for volatility clustering, the hour-of-day
  profile, the same calendar). Then any excess is about the side, not the volatility.
- **Confirm on data the pattern was not found on.** A tail picked out of many cells will look good
  by chance.
