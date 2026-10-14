# Weighting by realised score does not beat weighting by claimed precision

`pooling.Pooled` weights each member by its precision, which is what the member
**claims** about itself - and `statespace-river-against-members.md` showed that
claim was badly wrong, so wrong that a River tree beat the pool by 3.6x and 87%
of the gap closed by letting each member fit its own `Q`.

So the obvious correction is to stop asking and measure: a policy over the
members, rewarded by whichever one actually predicted best, never reads a
precision at all. Two prior measurements said there was room - **switching was
worth 5.3x** over holding one good member, and **blending beat winner-take-all
by only 5%**, so the selection rule was carrying nearly all of the gain.

The harness is `research/ideas/bandit_selection.py`.

## It is full information, and that is the fair version

A bandit normally learns only about the arm it pulled, but every member's
predictive density is computable at every step whether it was chosen or not.
Withholding that would handicap the policy for no reason, so every arm is
updated every step - which makes this **exponential weights on realised score**
rather than a bandit in the usual sense, and the comparison cleaner: both sides
see everything and differ only in where the weight comes from.

## The answer, with `Adapting` on

Six traded instruments, members wrapped in `Adapting` so their claims are as
good as this desk can make them.

| arm | loglike/bar | PIT | CRPS | switch % |
| --- | ---: | ---: | ---: | ---: |
| **`Pooled`, alpha 1** | 5.3570 | **10.26** | **0.000586** | - |
| `Pooled`, argmax | 5.3199 | 23.87 | 0.000625 | - |
| UCB | 5.4230 | 132.29 | 0.000592 | **0.0** |
| epsilon-greedy | 5.4104 | 122.52 | 0.000629 | 11.9 |
| Exp3 | 5.3331 | 54.04 | 0.001022 | 49.4 |
| random, the null | 5.2986 | 56.44 | 0.001126 | 66.6 |

**The blend still wins**, and on calibration it wins by a factor of thirteen:
PIT 10.26 against UCB's 132.29. On CRPS the two are a tie at 0.000586 against
0.000592, which is not a reason to replace a band that is calibrated with one
that is not.

**UCB switched 0.0% of the time.** It found one member in its first few steps
and never moved again, which makes it the `sticky` arm under a different name -
and `statespace-pooling-exponent.md` measured sticky at 5.3 times worse than
switching. That it now *ties* the blend is the interesting part, and it is a
consequence of `Adapting` rather than of the policy: once each member fits its
own process noise, there is much less to switch between.

**And more switching is worse, monotonically.** 0.0% ties, 11.9% is slightly
behind, 49.4% is nearly twice the CRPS, and the 66.6% of random selection is
worst. The 5.3x that switching was worth was switching between **differently
wrong** members; it was never a case for switching as such.

## The control says the same thing from the other side

| arm | PIT | CRPS |
| --- | ---: | ---: |
| `Pooled`, alpha 1 | 47.82 | 0.002898 |
| `Pooled`, argmax | **3.04** | **0.002611** |
| UCB | **3.04** | **0.002611** |

On the generated feeds, UCB and `argmax` are **identical to four decimal places
in all three figures**, because both collapse onto the same single member - and
on a specified process that is correct, which `statespace-pooling-exponent.md`
already recorded as the reason a blend loses there.

So the policy is behaving exactly as a selection rule should. It is just that
selection is not the thing that was broken.

## Which makes this the third time in one series

| asked | looked like | was |
| --- | --- | --- |
| do River's learners beat the members? | yes, 3.6x | 87% a mis-set `Q` |
| does a conditional band beat an unconditional one? | the first run said 26.8x worse | a scale bug in the harness |
| does realised score beat claimed precision? | there was 5.3x of room | the room closed when the claims were fixed |

Each time the apparent River result was a statement about the incumbent's
configuration rather than about River. The one exception so far is
`statespace-drift-detectors.md`, where ADWIN catches 89% of planted switches
against a CUSUM's 38% at matched false alarms, and no amount of retuning the
incumbent closes that.

**So: do not add a selection policy.** The precision weighting was not the
defect, `Adapting` was the fix, and a policy that selects correctly still gives
up the averaging that calibrates the band.
