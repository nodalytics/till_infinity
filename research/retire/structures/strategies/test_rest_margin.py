"""The take-vs-wait margin, as it passed on the level geometry.

Moved out of `tests/test_trading.py` on 2026-10-28 with `scalper.py`. The service
decision it tests is still live - `_park` takes the fill when it is already within
`pullback_min_gain` of the rest - but the **margin** came from `LevelStrategy`'s
entry refinement: a quote of 4380.5 against a rest of 4379.4 is `better_by` of
exactly 0.25, which is the default gain, so which side of the boundary it lands on
depends on how the entry was adjusted.

Retired rather than re-based, because nudging the test vehicle until a borderline
assertion flipped would be the same thing as tuning the fixture until an unrelated
gate opens - which `tests/mechanics.py` refuses to do for `statespace-surprise`.
Reviving it means reviving a strategy whose entry sits where this expects.
"""

async def test_a_fill_already_better_than_the_rest_is_taken():
    """On a fast move there is nothing to improve, and waiting would only risk
    the trade."""
    trader = Trader(Bus(), settings=settings(entry_edge_vol=0.25, pullback_fraction=0.0))
    await trader.start()
    # The quote is far below the level, so the buy is already better off.
    await trader.handle(
        Message(topic=QUOTES, payload={"feed": "gold", "bid": 4380.0, "ask": 4380.5})
    )
    got = await trader.on_signal(signal())
    assert not (isinstance(got, Refusal) and got.gate == "waiting")
