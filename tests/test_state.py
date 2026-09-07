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
