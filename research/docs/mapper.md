# Mapper proposes a subpopulation that survives nine conditionings, and the per-feed split says where it lives

Asked on 2026-10-14, after persistent homology had answered no to three direct
questions in `topology.md`: *we can even use topology to find things we were not
seeing or thinking about before too.*

That is a different mode. The three arms in `topology.md` **asked** topology
specific questions. This one lets it **propose** - the mode Mapper is actually
known for, where a subpopulation nobody hypothesised shows up as a flare - and
it is also the mode where a seventeen-coordinate descriptor and a free choice of
subgroup will find something in a random walk every time.

So the protocol is the result here, not the graph.

## The protocol

1. **Discover on the earlier half** of each feed. Build the Mapper graph over
   an eccentricity lens - mean distance to every other point, which makes a
   flare visible without naming its direction first - take every node of forty
   windows or more, and rank them by how far their forward behaviour sits from
   the pooled mean. **Nothing is claimed at this step** and no p-value from it
   is reported.
2. **Carry the node as a rule.** A Mapper node is a set, not a rule, so each is
   reduced to its centroid and later-half windows are assigned by nearest
   centroid. That is what makes a proposal testable.
3. **Confirm on the later half**, by label permutation, against the **most
   extreme bin** of three dials nobody needs topology for - volatility level,
   volatility ratio, range width - and of **hour of day**, because this desk's
   seasonality is known and rediscovering it is not a discovery. The baseline
   bins are chosen to be extreme in exactly the way the node was, so the
   comparison is not rigged.
4. **Run every arm on a block-shuffled copy**, and on three synthetic arms with
   known generators. If the same pipeline proposes an equally striking node on
   surrogates, the striking node is the pipeline.

The outcomes are pointed at the one problem this desk has open. Volatility is
modelled and direction is closed, while `no-gaussian-band-is-calibrated` says
nothing beats the walk on CRPS and the **tail shape** is unsolved - so the panel
carries `tail ratio`, the adverse against favourable excursion a stop pays for,
and `band miss`, how often the walk's own two-sigma band is breached.

## Three dials, and why there are three

Each dial was added because the previous one's survivor turned out to be the
next. Conditioning on the volatility **level** left the effect flat, which
looked like a finding - until the descriptor was read: it carries `vol_ratio`,
this window's volatility over the last one's, so the node could be reading
volatility **mean reversion**, which the level does not touch and a block
shuffle preserves. Adding the ratio left it flat again - and `held` is range
containment, which `topology.md` had already measured a **ruler** predicting at
an AUC of 0.74 to 0.84 from range **width** alone, a third quantity neither dial
removes.

Three dials, three strata counts each, and the effect does not move:

| traded, all 17 | raw | within vol 5/10/20 | within ratio | within width |
| --- | ---: | --- | --- | --- |
| `vol after` | -0.3401 | -.293/-.294/-.287 | -.274/-.251/-.245 | -.338/-.340/-.337 |
| `held` | +0.1420 | +.091/+.076/+.091 | +.101/+.098/+.135 | +.144/+.151/+.148 |
| `band miss` | -0.0405 | -.041/-.041/-.038 | -.039/-.037/-.030 | -.042/-.042/-.042 |
| `size after` | -0.2415 | -.191/-.164/-.151 | -.164/-.173/-.132 | -.238/-.238/-.239 |
| `tail ratio` | -0.1180 | -.148/-.160/-.140 | -.134/-.134/-.083 | -.117/-.127/-.120 |
| `drift after` | +0.0619 | p 0.406 | - | - |

Every cell above is p 0.002 to 0.052. The width bin predicts `held` at
**-0.1190** on its own - the opposite sign to the node - so the two are close to
independent rather than one standing in for the other.

This is the opposite of what the same diagnostic did to the range arm in
`topology.md`, where a single `H1` score walked 0.4418 to 0.4650 as this dial
narrowed. The sweep is the thing that can tell those two cases apart.

## The ablation: which half of the descriptor did it

Seven coordinates come from topology - `h0_total`, `h0_max`, `b1`, `h1_total`,
`h1_max`, `h1_land` and the loop score - and ten are ordinary: `vol_ratio`,
skew, kurtosis, autocorrelation, efficiency, a volume tie, wick bias, spread
level, up share, drawdown. One descriptor pass, three coordinate spaces, same
protocol:

| outcome | all 17 | plain 10 | topology 7 |
| --- | ---: | ---: | ---: |
| `held` | +0.1420 (.002) | +0.0496 (**.057**) | **+0.1000 (.002)** |
| `band miss` | -0.0405 (.002) | +0.0126 (**.319**) | **-0.0331 (.002)** |
| `vol after` | -0.3401 (.002) | **-0.3153 (.002)** | -0.2599 (.002) |
| `size after` | -0.2415 (.002) | +0.1252 (.002) | +0.1027 (.090) |
| `tail ratio` | -0.1180 (.037) | +0.0639 (.264) | -0.0065 (.915) |
| `drift after` | +0.0619 (.406) | -0.0009 (.993) | +0.0531 (.411) |

**Forward volatility is not a topology result.** It is the largest effect in the
study and the plain ten do it better than the topological seven. Had the
ablation not run, this would have been written up as persistent homology
predicting volatility, which it is not.

**Containment and band breaches are.** Both confirm from the topological seven
alone and fail from the plain ten, and both survive all three dials - `held` at
+0.1215/+0.1254/+0.1262 within width strata, `band miss` at -0.0330/-0.0329/
-0.0315.

## The surrogate separates them too

A block-shuffled copy of the same twelve instruments - blocks of fifty bars,
re-levelled in log space, every bar keeping its own open, high, low, volume and
spread - goes through the identical pipeline.

| topology 7, `held` | traded | block-shuffled |
| --- | ---: | ---: |
| raw | +0.1000 (.002) | +0.1031 (.002) |
| within ratio 5/10/20 | +.067/+.068/**+.086** (.005/.010/**.002**) | +.055/+.053/**+.007** (.147/.202/**.855**) |
| within width 5/10/20 | +.122/+.125/+.126 (all .002) | +.142/+.146/+.084 (.002/.002/.005) |

The surrogate reproduces `vol after` in full - stronger, at -0.6275 - and loses
`held` under the ratio dial, +0.0073 against the real series' +0.0859. That is
the asymmetry the whole design exists to find, and it is a twelvefold gap in
magnitude rather than a difference of p-values alone.

## The synthetic arms confirm nothing, which is what makes the rest readable

| arm | windows | `held` best reading |
| --- | ---: | --- |
| `Range_Break_100/200` | 3,176 | p 0.067, 0.354, 0.636 across subsets |
| `Drift_Switch_10/20/30` | 3,162 | p 1.000, 0.080, 0.372 |
| volatility and step indices | 5,608 | plain-10 p **0.015**, dies under width: -.022/-.024/-.018, p .414/.397/.641 |

Three arms, six outcomes, three subsets each, and nothing confirms under
conditioning. A discover-then-confirm protocol that finds nothing on fifty-four
synthetic cells and two things on traded is behaving like a test.

## Per feed, which is where the claim narrows

This desk has had a pooled median agree with a claim every subgroup refuted, so
the pooled number is not the claim. Topology seven, held out, by instrument:

| outcome | signs | individually significant | near zero or reversed |
| --- | --- | --- | --- |
| `vol after` | **12 of 12** negative | all twelve, p .002-.020 | none |
| `held` | 11 of 12 positive | AUDUSD +.204, USDCAD +.274, GBPJPY +.237, USDCHF +.200 | EURUSD +.033, XAUUSD +.034, EURGBP +.045; **XAGUSD -.115** |
| `band miss` | 11 of 12 negative | USDCHF .025, AUDUSD .047 | XAGUSD +.022 |

Eleven of twelve the same way is itself worth something - noise gives six - but
`held`'s pooled +0.1000 is carried by four instruments and is indistinguishable
from zero on EURUSD, gold and EURGBP. So the honest statement is **not** that
containment is predictable from the topology of the path; it is that four of
twelve instruments show it strongly, eleven of twelve lean that way, and silver
leans the other.

`band miss` is the reverse shape: small, diffuse, almost nowhere significant
alone, eleven of twelve the same way. That is what a real but even effect looks
like, and it is the outcome that bears on the open band-calibration problem.

## What is not done

- **The dials are matched one at a time.** Three marginal matchings are not a
  joint one, and the next step is a single propensity score over volatility,
  ratio and width together.
- **`held` has a base rate of 11 to 15%**, so +0.27 on USDCAD means roughly
  tripling it. An effect that large on a low-base-rate event deserves a direct
  look at those windows before it is trusted.
- **The traded-against-surrogate gap is not tested as a difference**, only read
  off two p-values that happen to differ twelvefold in effect.
- **The split is one chronological half.** Out of sample is not out of time;
  this wants a rolling split.
- **The baseline is a six-bin dial, not production.** If any of this matters it
  has to beat `statespace`'s own `Q(dt)`, which is a different and harder bar
  than the most extreme bin of realised volatility.

`drift after` is null in every subset of every arm, which is the sixth
independent arrival at the same place: direction is closed.
