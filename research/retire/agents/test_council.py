"""The council's own tests, as they passed on 2026-10-28 when it was retired.

Moved out of `tests/test_trading.py` with the strategy. `research/retire/README.md`:
the claim "it worked when it was removed" stays checkable, but out of the suite
that gates CI. These import `till_infinity.trading.strategies.council`, which now
lives beside this file, so they do not run as they stand.
"""

# ------------------------------------------------------------- the council


def opinion(side="buy", conviction=0.7, stop=1.0, target=1.6, because="because"):
    from till_infinity.trading.strategies.council import Opinion

    return Opinion(
        side=side, conviction=conviction, stop_vol=stop, target_vol=target, because=because
    )


def council(**over):
    from till_infinity.trading.strategies.council import Council

    return Council(**over)


def test_abstaining_is_removed_from_the_count_not_counted_against():
    """A panel that cannot say 'I don't know' will always find a trade."""
    got = council(quorum=2).resolve(
        {
            "trend": opinion("buy", 0.8),
            "contrarian": opinion("abstain", 0.0),
            "quant": opinion("buy", 0.7),
            "skeptic": opinion("abstain", 0.0),
        }
    )
    side, _stop, _target, why = got
    assert side is Side.BUY
    assert "2-0" in why


def test_every_voice_abstaining_is_no_trade():
    side, _, _, why = council().resolve({"trend": opinion("abstain"), "quant": opinion("abstain")})
    assert side is None
    assert "abstain" in why


def test_a_split_desk_does_not_trade():
    side, _, _, why = council(quorum=2).resolve(
        {
            "trend": opinion("buy", 0.9),
            "quant": opinion("buy", 0.6),
            "contrarian": opinion("sell", 0.9),
            "skeptic": opinion("sell", 0.8),
        }
    )
    assert side is None
    assert "split" in why


def test_a_lone_voice_does_not_meet_quorum():
    side, _, _, why = council(quorum=2).resolve({"trend": opinion("buy", 0.99)})
    assert side is None
    assert "quorum" in why


def test_weak_conviction_is_not_worth_the_spread():
    side, _, _, why = council(quorum=2, min_conviction=0.55).resolve(
        {"trend": opinion("buy", 0.3), "quant": opinion("buy", 0.4)}
    )
    assert side is None
    assert "conviction" in why


def test_an_absurd_stop_is_clamped_rather_than_obeyed():
    """A model asking for a forty-unit stop is failing, not being bold."""
    from till_infinity.trading.strategies.council import MAX_STOP_VOL, MAX_TARGET_VOL, MIN_STOP_VOL

    side, stop, target, _ = council(quorum=2).resolve(
        {
            "trend": opinion("buy", 0.9, stop=40.0, target=500.0),
            "quant": opinion("buy", 0.9, stop=40.0, target=500.0),
        }
    )
    assert side is Side.BUY
    assert stop == MAX_STOP_VOL
    assert target == MAX_TARGET_VOL

    _, tiny, _, _ = council(quorum=2).resolve(
        {"trend": opinion("buy", 0.9, stop=0.001), "quant": opinion("buy", 0.9, stop=0.001)}
    )
    assert tiny == MIN_STOP_VOL


def test_the_evidence_pack_is_the_same_for_every_voice_and_carries_no_free_text():
    """Deterministic, and nothing for a headline to smuggle an instruction through."""
    from till_infinity.trading.strategies.council import evidence

    pack = evidence(signal(), Tick("XAUUSD", bid=4399.5, ask=4400.5), GOLD, "gold")
    assert "gold (XAUUSD)" in pack
    assert "against a 47% unconditional rate" in pack
    assert "abstaining is a valid answer" in pack.lower()
    # The level model is offered as an input, not as an instruction.
    assert "not obliged to agree" in pack


async def test_a_voice_that_fails_reads_as_an_abstention():
    """A model that timed out has not made a case for a trade.

    Exercises the real `_ask`, by breaking the agent underneath it. An earlier
    version of this test replaced `_ask` itself, which bypassed the very
    try/except it was meant to prove - and passed for the wrong reason until
    the exception escaped `deliberate`.
    """
    from till_infinity.trading.strategies.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"), Voice("b", "y")), quorum=1, discuss=False)

    class Broken:
        async def run(self, prompt):
            raise RuntimeError("no credential")

    panel._agent = lambda voice: Broken()
    opinions, minutes = await panel.deliberate("brief")
    assert opinions == {}
    assert "nobody answered" in minutes


async def test_a_voice_that_times_out_reads_as_an_abstention():
    import asyncio as aio

    from till_infinity.trading.strategies.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"),), quorum=1, discuss=False, timeout=0.05)

    class Slow:
        async def run(self, prompt):
            await aio.sleep(5)

    panel._agent = lambda voice: Slow()
    opinions, _ = await panel.deliberate("brief")
    assert opinions == {}


async def test_the_desk_discusses_once_and_may_change_its_mind():
    from till_infinity.trading.strategies.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"), Voice("b", "y")), quorum=1, discuss=True)
    seen = []

    async def answering(voice, prompt):
        seen.append((voice.name, "desk has now spoken" in prompt))
        # First round buys; after seeing the table, one voice abstains.
        if "desk has now spoken" in prompt and voice.name == "b":
            return opinion("abstain", 0.0)
        return opinion("buy", 0.8)

    panel._ask = answering
    opinions, minutes = await panel.deliberate("brief")
    # Two voices, two rounds each.
    assert len(seen) == 4
    assert sum(1 for _, second in seen if second) == 2
    assert opinions["b"].side == "abstain"
    assert "after discussion" in minutes


async def test_a_voice_failing_the_second_round_keeps_its_first_answer():
    """A timeout is not a retraction."""
    from till_infinity.trading.strategies.council import Council, Voice

    panel = Council(voices=(Voice("a", "x"),), quorum=1, discuss=True)
    calls = []

    async def flaky(voice, prompt):
        calls.append(prompt)
        return None if "desk has now spoken" in prompt else opinion("buy", 0.9)

    panel._ask = flaky
    opinions, _ = await panel.deliberate("brief")
    assert len(calls) == 2
    assert opinions["a"].side == "buy"


async def test_the_council_produces_a_sized_intent():
    from till_infinity.trading.strategies.council import CouncilStrategy

    engine = CouncilStrategy(settings(strategies=("council",)))

    async def agreeing(brief):
        return {"trend": opinion("buy", 0.8), "quant": opinion("buy", 0.7)}, "minutes"

    engine.council.deliberate = agreeing
    got = await engine.consider_async(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Intent)
    assert got.side is Side.BUY
    assert got.volume > 0
    assert got.hold == CouncilStrategy.hold_seconds


async def test_the_council_respects_its_daily_call_ceiling():
    from till_infinity.trading.strategies.council import CouncilStrategy

    engine = CouncilStrategy(settings(council_daily_calls=4))
    engine.calls = 4
    got = await engine.consider_async(
        signal(), spec=GOLD, tick=Tick("XAUUSD", bid=4399.5, ask=4400.5), equity=10_000.0
    )
    assert isinstance(got, Refusal)
    assert got.gate == "budget"




# From tests/test_trading.py: the LLM valuer in `trading/valuation.py`, which had
# no caller in production and was removed with `agents`.

async def test_a_failing_analyst_produces_no_valuation():
    """Timeout, no credential, a malformed reply: all read as no answer."""
    from till_infinity.trading import valuation

    assert await valuation.ask("gold", "brief", timeout=0.01) is None
