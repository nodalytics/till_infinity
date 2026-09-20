# Shared State

Rationale moved out of `till_infinity/shared/state.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `restore_number`

    **The same failure as `restore_enum`, one type along.** A resting `Intent`
    came back from saved state with `target` as the *string* `"1.2345"`, and
    `Intent.reward` is `abs(self.target - self.entry)` - so the first tick that
    asked whether the order had turned against itself raised `unsupported
    operand type(s) for -: 'str' and 'float'` and took the whole trading
    service down with it. On 2026-09-08 that cost hours, and the same shape had
    already done it once with `Side`.

    Coerced on the way *in* for the reason that one gives: a fix on the way out
    only helps state written after the change, and the file already on disk is
    the one crashing. A value that will not convert is left exactly as it was,
    so the fault stays visible at the point of use rather than being turned
    into a plausible zero.


## `restore_enum`

    **`Side` is a `StrEnum`, so it serialises as a plain string and comes back
    as one.** Nothing complains until something asks it for a member - and what
    asked was `shade.side.sign` in the trading loop, which took the whole
    service down with `'str' object has no attribute 'sign'` and left it
    stopped rather than degraded.

    Coercing on the way *in* rather than tagging on the way out is deliberate:
    a tag would only help state written after the change, and the file that was
    already on disk is the one that was crashing.


## `Restorable`

    `__slots__ = ()` is load-bearing. A base class without it gives every
    subclass instance a `__dict__`, which would silently undo the `slots=True`
    these classes are declared with - turning a memory fix into a memory
    regression on a box that has been OOM-killed five times.

    Not a dataclass itself, so a frozen subclass stays legal: dataclasses only
    object to a frozen class inheriting from a non-frozen *dataclass*.


## `Restorable.__init_subclass__`

        A `frozen=True, slots=True` dataclass gets a `_dataclass_setstate`
        written onto the class itself, and a method on the class beats one
        inherited from a base. So merely listing this mixin does nothing for
        every frozen value object here - `Features`, `Inference`, `Point`,
        `Approach`, `Signal` - which is most of them, and it does nothing
        *silently*, which is the failure this whole module exists to stop.

        The generated version copies what is in the state and no more, so a
        field added after the save stays missing. Replacing it keeps pickle's
        contract and adds the defaulting.

        Only the generated one is replaced. A class that writes its own is
        making a deliberate choice and keeps it.




## `restore_deque` - a bound only the default carries is not a bound

Added 2026-09-20, after `Cusum.events` was found to be the growth behind the
container's OOM kills.

`__setstate__` assigns the stored value straight onto the field. Pickle stores a
deque's *contents*, and any state written while the field was a `list` - which
is every state written before it was bounded - restores as a `list`. `maxlen` is
then gone, and the field grows for the life of the process while its declaration
says it cannot. Measured on the pre-fix source, a `deque(maxlen=22)` field
restored from a list reached **10,110 entries**.

This held for all 21 `deque(maxlen=...)` fields across 11 modules, which is why
the repair is here rather than in `Cusum`. It also invalidated a line of
reasoning used while hunting the leak: *"that field is a capped deque, so it
cannot be what grows"* was read off the declaration and was not true of the
running object. A bound is only evidence if it is checked on the live heap.

### The stored bound wins

The first version read the cap from the `default_factory` and forced it onto
whatever arrived. That resized a restored `Zma._prices` window from 20 to 50,
caught by `test_zma_wiring`, because **the bound can be per-instance**: `Zma`
sizes its window from `period`, so the factory reports the number a
default-constructed object would get and not this one's.

So a stored deque is left exactly as it is - pickle preserves `maxlen`, and that
is the instance's own answer. The factory is consulted only for a value that
arrives carrying no bound at all: a `list`, a `tuple`, or a deque with
`maxlen is None`. Reading the factory is also gated on the annotation naming a
deque, so introspection never calls an unrelated one - `Learned._model` builds a
river pipeline, and a cached field lookup has no business doing that.
