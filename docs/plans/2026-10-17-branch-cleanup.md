# Branch cleanup, 2026-10-17

107 remote branches, reduced to one. What this records is **how the unmerged
ones were found**, because the obvious test is wrong, and the SHA of every
branch deleted, because a deleted branch is only recoverable by SHA.

## `git diff main...branch` does not answer "is this merged?"

Three dots diffs the **merge base** against the branch tip. For a branch that
was squash-merged - which is how everything lands here - the merge base is the
old commit it forked from, the branch's commits are not ancestors of `main`,
and the diff therefore shows the branch's entire contribution whether or not
`main` already has it. `git rev-list --count main..branch` is wrong for the
same reason, and `git cherry` is wrong a third way: a squash commit's patch
equals the *sum* of the branch's commits, so each individual commit on a
multi-commit branch is reported as unmatched.

An earlier pass over these branches used the three-dot diff and concluded that
**73 of them carried unmerged work**, split into categories by what they
touched. Then three of the cleanest were merged and every one produced a tree
identical to `main`: `_restable`, `probability_up_before` and the `record-auc`
note were all already there. The classification was measuring staleness.

### What does answer it

Two dots - `git diff main..branch` - compares the two trees directly, and a
branch that adds nothing shows no added lines. Where the two-dot diff did show
additions, they were read rather than counted, because a branch that is simply
**behind** `main` also shows additions: its older copy of a line `main` has
since rewritten. The tells were unmistakable once looked at.

* `tests/test_statespace.py` at **+2 / -1488** - a stale copy, not new work.
* The same `+6 / -28` on `trading/turning.py` and `+5 / -25` on
  `tests/test_trading.py` on unrelated branches - shared old state.
* `+219 defs added` on four branches, of which ~147 "absent from main" were
  test functions `main` has since renamed or removed.
* One test, `test_the_fixed_lag_form_is_what_is_still_missing`, appeared as an
  addition on five separate branches. `main` removed it.
* `till_infinity/structures/statespace/TODO.md`, deleted in #149, came back as
  a conflict or an addition on three branches.

The remaining question for each survivor was whether its new files exist in
`main` under any name. Two did not (`derivml_*`, `fxml_*`, `wick_*`: absent
entirely). One did: `statespace-from-five-papers.md` is the earlier, narrower
copy of `main`'s `statespace-from-papers.md` - the same five sections where
`main` has six, retitled so it could grow.

## Reclaimed

Five branches carried content `main` did not have. All of it is additive: 32
files, 22,756 insertions, no deletions.

| branch | what it carried |
| --- | --- |
| `ops/ci-fallback` | `ci-fallback.sh` and `pull-deploy.sh` - build and deploy when Actions will not start, plus the `docs/deployment.md` section for them |
| `research/deriv-ml` | 13 files: the Deriv ML harness, generator fits committed before each model run, the addendum |
| `research/fx-metals-ml` | 12 files: the FX/metals ML harness, INDEX universe, rollover diagnostics, conformal arms |
| `research/wick-levels` | 4 files: the wick-count level-hold harness, rule frozen before any real-data run |
| `research/redo-the-slope-and-average-tests-in-time` | nothing, once the duplicate doc was dropped; merged to record that it was considered |

The two ops scripts were worth keeping even though CI has been green since
2026-10-09: each is idempotent and self-disabling - `ci-fallback.sh` triggers
on a **missing image** rather than a billing error, so when Actions builds
again the tag resolves and it exits having done nothing.

## Deleted

Nothing below carried a line `main` lacks. Recoverable with
`git fetch origin <sha>` while GitHub still holds the object.

### Fully absorbed into main (89)

| branch | sha |
| --- | ---: |
| `docs/finding-edges-skill` | 1a41cf3 |
| `fix/resting-stops-level` | 2ff6466 |
| `improvements/research-into-statespace` | 1f05e9b |
| `inside-bars` | 5916724 |
| `mcfl/alerts` | cffb682 |
| `models/envelope-families` | 8c04f2b |
| `prod/pre-touch-posterior` | 7ea43fc |
| `research/barrier-traded` | 6f51518 |
| `research/binance-replication` | ae98686 |
| `research/boomcrash-trend` | 5a8cbdd |
| `research/bos-predict` | b69858f |
| `research/candle-screen` | 9795e18 |
| `research/conditional-hold-rates` | 2162620 |
| `research/crash-timing-and-direction` | a88cf85 |
| `research/crypto-daily-trend` | cb49718 |
| `research/dax-zones` | e362861 |
| `research/desk-summary` | b925fcc |
| `research/entry-momentum` | f064fbd |
| `research/episodes-and-ladder` | 97efcd3 |
| `research/fortnightly` | 057ea7e |
| `research/fuzzy-logic` | a687d2d |
| `research/fvg-levels` | 649b9f2 |
| `research/fx-reversal-fourier` | ab2490f |
| `research/geraked-eas` | 6d3c776 |
| `research/imported-ideas` | 57af85c |
| `research/journal-probability` | 250c64e |
| `research/level-shrinkage` | aaabc05 |
| `research/level-signatures` | f5272a7 |
| `research/live-rescore` | e0c6ff8 |
| `research/lrc-bos-retest` | 727cabe |
| `research/mapper-discovery` | 2ebffc7 |
| `research/mcfl` | e851471 |
| `research/mcfl-roadmap` | ab7b96e |
| `research/mcfl-roadmap-pnr` | c55c02c |
| `research/mcfl-time` | 94f784a |
| `research/mcfl-time-core` | 6db68e0 |
| `research/mcfl-v1` | 95ad7f5 |
| `research/mcfl-v2` | b6cae97 |
| `research/mean-reversion` | a6647f2 |
| `research/nested-correction` | 4007b5e |
| `research/origin-returns` | 0ac1ab4 |
| `research/pca-residuals` | 2014b49 |
| `research/pivot-families` | 291809e |
| `research/range-break-100` | 19a91b8 |
| `research/record-auc` | 944dfd3 |
| `research/relationship-screen` | cd64795 |
| `research/signal-layer` | 0078848 |
| `research/smc-conjunctions` | f968022 |
| `research/state-space` | 8fded98 |
| `research/state-space-ml` | 3e672a2 |
| `research/strategy-switching` | 7760df4 |
| `research/structural-target` | ffb721a |
| `research/structure` | 16143e3 |
| `research/survivors-check` | 6cf5bec |
| `research/sweeps` | 9c57d8d |
| `research/tail-scan` | 3b061ca |
| `research/tail-shape` | 0323b26 |
| `research/turn-retrade` | f128fdb |
| `research/turn-zones` | bf204c3 |
| `research/tv-indicators` | f038d1b |
| `research/two-sided-direction` | 1950a9b |
| `research/walks-behavioural` | c8580c1 |
| `research/weight-return` | e445b39 |
| `research/what-loses` | d842e83 |
| `research/zone-flip` | ce82e73 |
| `research/zone-nested` | 7e957c3 |
| `research/zone-push` | cb6f1a8 |
| `research/zone-retest` | 55a2afd |
| `research/zscore-window` | 76bfbe7 |
| `statespace/dispersion` | ab2c583 |
| `statespace/spanning` | a4e5801 |
| `statespace/turn-levels` | c402714 |
| `structures/predict-the-order-then-map-it` | d0dbe35 |
| `structures/profile-harmonics-and-point-z` | db97eb7 |
| `structures/seed-quotes` | f239d75 |
| `structures/the-nulls-belong-in-the-library` | 3c42bb2 |
| `structures/warm-cap-does-not-bind` | 1a459f5 |
| `trading/fade-1h` | 6e8121a |
| `trading/floor-everywhere` | 040c3fd |
| `trading/floor-where-measured` | 6812ff2 |
| `trading/impulse-features` | 996710c |
| `trading/level-scalp-exits` | 0c5866b |
| `trading/quantile-gate` | aadb85a |
| `trading/reward-floor` | 96d2d59 |
| `trading/rr-floor-watch` | a57ec88 |
| `trading/sized-record` | bf610a6 |
| `trading/the-liquidity-gate-for-every-level-strategy` | 0f9168f |
| `trading/thesis-only-keeps-its-circuit-breaker` | dbc46ed |
| `trading/trend-features` | 97db227 |

### Behind main, carrying only its older state (13)

| branch | sha | why |
| --- | ---: | --- |
| `research/conformal-and-convexity` | 2fbe443 | stale copy of main |
| `research/pattern-fingerprint` | 11b1c5c | stale copy of main |
| `research/slope-crossing` | 2cac486 | stale copy of main |
| `research/zone-timeframes` | 5877ab8 | stale copy of main |
| `research/zscore-variants` | 5d64a21 | stale copy of main |
| `structures/a-smoother-for-any-member` | 2cc475d | stale copy of main |
| `structures/mamba-says-our-data-is-the-lti-case` | fe6524b | stale copy of main |
| `structures/the-hmm-member` | 14c2846 | stale copy of main |
| `structures/the-input-channel-finally-has-a-consumer` | 581fa9c | stale copy of main |
| `structures/the-smoother-carries-the-cross-terms` | 7c1183c | stale copy of main |
| `structures/the-volatility-ceiling-was-the-wrong-denominator` | c725088 | stale copy of main |
| `structures/topology-and-quotes` | 8ea4e70 | stale copy of main |
| `trading/reward-floor-12` | 3373bcb | stale copy of main |

Four of these are worth naming, because their titles promise work that sounds
unmerged and is not: `structures/the-hmm-member`,
`structures/the-input-channel-finally-has-a-consumer`,
`structures/a-smoother-for-any-member` and
`structures/the-volatility-ceiling-was-the-wrong-denominator` each landed by
squash merge. What their two-dot diffs add back is an older `predict`, an
older `filter`, a deleted `TODO.md` and a removed test.
