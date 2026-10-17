"""S4D-Real as a member in its own right, rather than as another member's null.

Asked for on 2026-10-17 - "promote it" - and the README has been asking for
longer: *"S4D-Real as a first-class member. It just won 3m, 15m and 30m outright
while existing only as `selective`'s nested null. Promote it: four LTI states,
spectrum `-(n+1)`, no selection, nothing input-dependent. The cheapest thing in
this list and already the best model at the fast end."*

## Why this is a subclass, which is unusual here and is the point

Every other member in this family is standalone. This one is `Selective` with
`scale` pinned at zero, because **that is what S4D-Real is**: the paper's
time-invariant diagonal state space is exactly the selective model with the
input-dependent part switched off, and `selective.py` already says so - its
`scale` docstring calls zero "the null" and names `reverting` as a nested
special case.

Writing it as a copy would make the two drift apart, and the whole value of
promoting it is that it stays **comparable**: the same retention, the same
entry weight, the same normalised-average read-out, the same `loglike`
convention and the same burn-in. A separate implementation that scored
differently would leave nobody able to say whether the difference was the model
or the code. Here the difference is one parameter, and it cannot be anything
else.

What promotion actually buys is registration. `family.members()` is the
registry every comparison harness walks and the pool draws from, and a model
that only exists as another model's null arm can be neither pooled nor scored
against the family. This one won at the fast end and could not be put in a
pool.

## The selection is refused rather than defaulted

`Selective()` already has `scale = 0.0` by default, so an unfitted instance of
the parent is numerically this member. That is not enough: a harness that fits
the parent fits `scale` too, and the thing being promoted is the model where
there is no `scale` to fit. So `__post_init__` **raises** on a non-zero
`scale`. A member that silently ignored it would be a different model than its
own name claims, which is the failure mode this package has already paid for
once in `DRIFT_VOL_PER_HOUR`.

## Why the anchored variant is not here

The README's next item is *"the zero-eigenvalue variant of it, which is
trade-off 2's one-line fix"*, and it is deliberately absent. Two measured
reasons, both already on record:

* **A true zero cannot be driven.** The entry weight is `1 - exp(delta * A)`,
  which is exactly zero at `A = 0`, so a zero eigenvalue in a deterministic
  member is a state no reading can ever reach. `swarm` gets away with it
  because its particles are corrected by the data rather than by the
  recurrence - the anchor is a random walk the weights steer.
* **A near-zero one breaks the read-out.** `_readout` is the **mean** of the
  basis, which is correct precisely because every state converges to the
  reading. Put one slow state in and the mean permanently retains `1/SIZE` of a
  stale level: `selective`'s own note measures that at **39 of 250 over 48
  hours**. The fix is a read-out of anchor-plus-deviations, and the member that
  has one is `swarm`.

So the anchored idea is not unbuilt here, it is **built elsewhere and for a
reason**. Putting a slow mode into this read-out would ship the bug that note
was written about.
"""

from __future__ import annotations

from dataclasses import dataclass

from .selective import SIZE, Selective


@dataclass(slots=True)
class Diagonal(Selective):
    """Four LTI states, spectrum `-(n+1)`, nothing input-dependent.

    The parent's `drift` still sets the step size - `INERT` means one hour of
    `delta` per hour of clock - and `gain`, `read` and `noise` are still the
    fitted parameters. What is gone is `scale`, and with it every
    input-dependent quantity: `retention` ignores its `z`, `gate` is constant,
    and the member is time-invariant in the sense the S4D papers mean.
    """

    def __post_init__(self) -> None:
        if self.scale != 0.0:
            raise ValueError(
                f"scale is {self.scale} - this member is time-invariant by "
                "construction. Use `selective.Selective` for a selective model, "
                "so that a score says which one it was."
            )

    def eigenvalues(self) -> tuple[float, ...]:
        """`A`'s diagonal, `-(n+1)` per state, in inverse hours.

        An instance method rather than the parent's static one, so that a
        member's spectrum is a property of the member and `spectrum.py` can
        read it off any of them the same way. The values are unchanged.
        """
        return tuple(-(n + 1.0) for n in range(SIZE))
