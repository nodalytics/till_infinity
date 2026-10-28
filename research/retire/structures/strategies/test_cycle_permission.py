"""The cycle strategies' earned-record permission, as it passed when they retired.

Moved out of `tests/test_invariants.py` on 2026-10-28 with `stretching.py` and
`strategies/turning.py`. It asserted that `cycle-turn` and `cycle-turn-scalp` would
not act on a feed whose record had not earned a say - two hundred settled calls -
which is why `cycle-turn` had never traded.
"""

@given(calls=st.floats(0.0, 5000.0), rate=st.floats(0.0, 1.0))
def test_a_cycle_permission_needs_an_earned_record(calls, rate):
    from till_infinity.trading.strategies.stretching import CycleTurnScalp
    from till_infinity.trading.strategies.turning import CycleTurn

    s = Settings()
    right = calls * rate
    base = {
        "level": 100.0,
        "vol_bps": 100.0,
        "zma_agrees": 1.0,
        "zma_stretched": 1.0,
        "zma_z": -2.0,
        "zma_strong": 1.0,
        "break_side": 1.0,
        "break_price": 99.0,
        "break_age": 600.0,
    }
    turn = {**base, "zma_anchor_edge_calls": calls, "zma_anchor_edge_right": right}
    scalp = {**base, "zma_edge_calls": calls, "zma_edge_right": right}
    if not s.zma_earned(calls, right):
        assert (
            CycleTurn(settings=s).accept(
                {"direction": "up", "feed": "v75", "interval": "15m", "confluence": ["1h", "4h"]},
                turn,
            )
            is not None
        )
        assert (
            CycleTurnScalp(settings=s).accept(
                {"direction": "up", "feed": "v75", "interval": "1m", "confluence": ["30m", "1h"]},
                scalp,
            )
            is not None
        )
