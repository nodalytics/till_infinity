def test_a_strenum_field_comes_back_as_its_enum():
    """`Side` is a `StrEnum`, so it serialises as a plain string and restores
    as one. Nothing complains until something asks it for a member - and what
    asked was `shade.side.sign` in the trading loop, which took the service
    down with `'str' object has no attribute 'sign'` and left it stopped."""
    import dataclasses

    from till_infinity import trading
    from till_infinity.structures.codec import pack, registry, unpack
    from till_infinity.trading import service as svc
    from till_infinity.trading.models import Side

    shade = svc.Untaken(
        feed="gold",
        by="runner",
        side=Side.SELL,
        entry=4400.0,
        stop=4410.0,
        target=4380.0,
        interval="15m",
        fill_by=0.0,
        hold=3600.0,
    )
    known = registry(trading)

    back = unpack(pack(shade), known)

    assert isinstance(back.side, Side)
    assert back.side is Side.SELL
    assert back.side.sign == Side.SELL.sign
    assert dataclasses.asdict(back) == dataclasses.asdict(shade)


def test_an_unknown_member_keeps_the_raw_value_rather_than_raising():
    """A member this build no longer has should be visible at the point of use,
    not cost the whole file."""
    from till_infinity.structures.state import restore_enum
    from till_infinity.trading import service as svc

    assert restore_enum(svc.Untaken, "side", "sideways") == "sideways"
    assert restore_enum(svc.Untaken, "feed", "gold") == "gold"


def test_a_bounded_deque_field_comes_back_bounded():
    """**A bound only the default carries is not a bound.**

    `__setstate__` assigns the stored value straight onto the field, so a state
    holding a plain `list` - which is what every state written before the field
    was bounded holds - dropped `maxlen` and the field grew for the life of the
    process while its declaration said it could not. All 21 `deque(maxlen=...)`
    fields in the codebase had this hole.
    """
    from collections import deque

    from till_infinity.structures.context.cusum import EVENTS_KEPT, Cusum

    filled = Cusum()
    filled.__setstate__({"events": list(range(EVENTS_KEPT * 4))})

    assert isinstance(filled.events, deque), type(filled.events)
    assert filled.events.maxlen == EVENTS_KEPT
    assert len(filled.events) == EVENTS_KEPT
    # A deque bounded all along would have kept the newest, so this does too.
    assert filled.events[-1] == EVENTS_KEPT * 4 - 1


def test_restoring_does_not_build_unrelated_factories():
    """Reading a `maxlen` means calling a `default_factory`, and `Learned._model`
    builds a river pipeline. Introspection must not pay for that, so the lookup
    is gated on the annotation naming a deque."""
    from till_infinity.shared.state import _deque_bounds
    from till_infinity.structures.vol.learned import Learned

    bounds = _deque_bounds(Learned)

    assert "_model" not in bounds
    assert "_anomaly" not in bounds


def test_every_bounded_deque_field_survives_a_list_state():
    """The generic guarantee, across every class that declares one."""
    import dataclasses
    from collections import deque

    from till_infinity.shared.state import _deque_bounds, restore_deque
    from till_infinity.structures.context import cusum, reach, trend
    from till_infinity.structures.vol import har, learned

    seen = 0
    for module in (cusum, reach, trend, har, learned):
        for name in dir(module):
            cls = getattr(module, name)
            if not dataclasses.is_dataclass(cls) or not isinstance(cls, type):
                continue
            for field, cap in _deque_bounds(cls).items():
                back = restore_deque(cls, field, list(range(cap * 3)))
                assert isinstance(back, deque), f"{cls.__name__}.{field}"
                assert back.maxlen == cap, f"{cls.__name__}.{field}"
                seen += 1
    assert seen >= 5, f"expected several bounded deque fields, found {seen}"


def test_a_per_instance_bound_is_not_overwritten_by_the_default():
    """`Zma._prices` is sized from `period`, so its `default_factory` reports a
    placeholder. Reading the bound from the factory resized a restored window
    from 20 back to 50 - caught by `test_zma_wiring`, and the reason a stored
    deque is now left alone: pickle already preserves its `maxlen`."""
    import pickle

    from till_infinity.structures.zma import Zma

    z = Zma(period=20)
    for i in range(300):
        z.observe(100.0 + i * 0.01)

    back = pickle.loads(pickle.dumps(z))

    assert back._prices.maxlen == 20, back._prices.maxlen


def test_an_unbounded_stored_deque_is_given_the_bound():
    """The other half: a deque pickled while the field was unbounded has
    `maxlen is None`, and that one does need the factory's cap."""
    from collections import deque

    from till_infinity.structures.context.cusum import EVENTS_KEPT, Cusum

    filled = Cusum()
    filled.__setstate__({"events": deque(range(EVENTS_KEPT * 3))})

    assert filled.events.maxlen == EVENTS_KEPT
    assert len(filled.events) == EVENTS_KEPT
