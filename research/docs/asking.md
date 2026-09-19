# Five questions worth the compute, and what would settle each

Not findings. **An agenda**, written down so that the reasons for picking these
five survive contact with whatever the first one returns, and so a question that
gets abandoned is abandoned on the record rather than quietly.

Each entry says what the claim is, what would kill it, what it costs, and - the
part that decides the ordering - **what we learn if it comes back negative.** A
question whose negative result teaches nothing is not worth running, however
cheap it is.

The standing constraint applies to all five.
[deriving.md](deriving.md) proves `E[net] = -(c/2) x turnover` for any
predictable position on a martingale, so **none of these can become a direction
call on the generated book.** What they can be is a better conditional estimate,
which [spending.md](spending.md) says is where the desk is actually weak, or a
fact about the instruments that closes a question permanently.

---

## 1. Does a correction retrace 0.86 of its rally, and is that a market fact?

**The claim.** A cycle is a rally followed by a correction of `alpha` times it,
`alpha = 0.86`, so the cycle nets 14%.

**Why it is worth running.** It is a *specific number*, which almost nothing in
this area is. A claim precise enough to be wrong is worth more than a framework
that cannot be.

**What would kill it, and what each outcome means.** A retracement fraction is
not read off prices, it is read off **swings**, and a swing exists only once a
detector says so. Every zigzag takes a threshold `theta` and records a turn only
after a reversal of at least that much - so **every rally and every correction it
records is at least `theta`**, and the ratio of two quantities truncated from
below is not the ratio of the underlying ones. Three explanations, and the sweep
separates them:

| outcome | meaning |
| --- | --- |
| `alpha` moves with `theta` | the constant is the **instrument** |
| `alpha` equal on feed and simulated Brownian | a property of **random walks**, not markets |
| flat in `theta` **and** feed differs from simulated | the only outcome worth a second study |

The prior is against the third: [generated.md](generated.md) has the synthetics
at `H = 0.50` and textbook GBM, so a constant that shows up on *them* cannot be a
market fact - there is no market in them to be a fact about.

**Cost.** Hours. The harness is [retracing.py](harness/retracing.py); the data is
already cached.

**The negative is useful**: it retires a number that will otherwise keep being
proposed, and it calibrates how much of what a swing detector reports is the
detector.

---

## 2. Is a turn that two detectors agree on different from one only one finds?

**The claim.** Nobody's - this is the question the detector comparisons imply and
nobody asks.

**Why it is worth running.** The usual question is *which detector is better*, and
it has an answer: a zigzag confirms a turn in about one bar, a changepoint
detector in ten to twenty-two, and they agree on well under half of each other's
turns. That disagreement is normally treated as a nuisance to be resolved by
picking a winner. **It is a free conditioning variable**, and we already run both
in production - `_note_change` is live and the swing detector feeds every level.

**What would kill it.** The rejection rate on turns both detectors find, against
turns only one finds, on matched samples - with the usual controls, and with the
confirmation lag handled explicitly, because a detector that confirms in 22 bars
has seen 22 bars the other has not and would otherwise look better for a reason
that is not about turns at all.

**Cost.** Days rather than hours: it needs the two detectors aligned on one clock
before anything can be counted.

**The negative is useful**: it says the agreement carries nothing, which retires
the ensemble-of-detectors idea before somebody builds one.

---

## 3. Do polynomial critical points mark reversals?

**The claim.** Fit a polynomial of degree `n` over a window; its critical points
- `T'(t) = 0` - are nodes where price reverses.

**Why it is worth running.** It is cheap, and it is the most likely of the five
to be an artefact in an *instructive* way.

**What would kill it.** A polynomial fitted to a random walk has critical points
wherever the window puts them - their number is bounded by the degree and their
location is driven by the fit, not the process. So the control is not optional
and it is the whole study: the same detector on a phase-randomised surrogate and
on simulated GBM, with the family-wise correction, because a degree and a window
length are two free parameters and sweeping both is a lot of chances at 0.53.

**Cost.** Hours.

**The negative is useful**: it is the clearest available demonstration that a
method which *looks* like it is finding structure is reading its own parameters,
and this folder can point at it the next time one arrives.

---

## 4. Why did the multi-timeframe refinement not replicate?

**The claim.** Hierarchical refinement of levels improved the rejection rate on
15 of 15 cells of a deep panel, and did nothing on an independent later panel.

**Why it is worth running.** 15 of 15 is not noise, and neither is a flat
replication. Both being true means something specific happened, and there are
only two candidates.

**What separates them.** **Overfitting degrades smoothly with sample and has no
date; a regime change has a date and does not care about sample.** Cut the deep
panel by era and by size independently: if the effect decays as the fit shrinks,
it was fitted; if it survives every size but dies at a point in time, something
changed and the date names it.

**Cost.** Hours, on data already held.

**The negative is useful** either way, because the two answers call for opposite
responses - one retires the method, the other dates a regime and keeps it.

---

## 5. Does sizing on forecast volatility beat sizing on realised?

**The claim.** A stop sized for the next thirty minutes should use the volatility
expected over them rather than the volatility just observed.

**Why it is worth running.** It is the one place the volatility work pays out in
position sizing rather than in description, and it is now **sharper than it was**:
since `har.published` landed, the forecast on the twenty named feeds is a
*constant*, so the question reduces to something clean - does knowing sigma in
advance beat measuring it afterwards, on a process where sigma genuinely does not
move?

**What would kill it.** Replay with both sizings on identical entries. The trap
is that a better-sized book takes *different trades*, so the comparison has to
hold entries fixed and vary only the size, or it measures selection rather than
sizing.

**Cost.** Days, and it should wait. The deferral has been live for minutes rather
than days, and `consensus_vol` scores its members continuously - so the honest
order is to let it accumulate a scored record first and build sizing on a member
that has earned its weight, not on one that was argued into place.

---

## Outstanding, as of 2026-09-15

Carried here rather than in a head, because three of these are one command each
and the reason they are not done is infrastructure rather than thought.

**Blocked on the lab's `sshd`** - the box is up and its MT5 terminal is still
serving the live desk through its tunnel, but SSH refuses from every source, so
the filesystem is unreachable:

1. **Which feature carries the reversal edge.** `reversing.py`'s drop-one
   harness is written and has run; the log could not be read. The question that
   matters is whether it is `band_pos`, which would make
   [families.md](families.md)'s Range Break result - AUC 0.6627, conditional on
   position in a band - reappear on real markets and be a much larger finding
   than 3.5 points of AUC.
2. **Detector agreement.** [agreeing2.py](harness/agreeing2.py) is written and
   unrun.
3. **The ESN arm.** `seqesn.py` and a 299-line `reservoirs.md` are on disk from
   an agent that died on a rate limit mid-write and never reported. Uncommitted,
   because nothing has vouched for them.

**Not blocked, and more important than any of the above:**

4. **Does the reversal edge clear the spread?** An AUC is not money.
   [policies.md](policies.md) priced that distinction on this book: a 0.619
   filter cleared **0.103 to 0.692** of the quoted spread and lost money in every
   cell. This needs replay, not the lab.
5. **Is the `+0.019` refinement residual worth anything after costs?** Same
   question, same reason, and it is now established rather than suspected.
6. **`inert: []` is ambiguous** between "everything fired" and "nothing was
   declared" - opposite states that read identically. `shared/effects.py` should
   report the declared count beside the list. Two lines.

## The order, and why

**1, then 3, then 4, then 2, then 5.**

The first three are hours each and all three have useful negatives, which is the
cheapest kind of progress this folder makes. 4 needs no new data. 2 is the most
novel and the most expensive, which is the wrong combination to start with. 5 is
last because it is the only one that would change a live position's risk, and it
is waiting on evidence that is currently three hours old.
