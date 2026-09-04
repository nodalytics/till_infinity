"""One decision, several accounts - copy mode.

The correctness point is that **risk** is replicated and **lots** are not:
0.05 lots sized for a 10,000-unit account is a quarter percent of it and one
and a quarter percent of a 2,000-unit one - five times the authorised risk, on
the account least able to carry it.
"""

from till_infinity.trading.config import Settings
from till_infinity.trading.models import (
    Intent,
    Order,
    OrderResult,
    Side,
    SymbolSpec,
)
from till_infinity.trading.venues import replicate as rp

GOLD = SymbolSpec(
    symbol="XAUUSD",
    digits=2,
    point=0.01,
    tick_size=0.01,
    tick_value=1.0,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
    contract_size=100.0,
)


def intent(**over):
    made = {
        "feed": "gold",
        "symbol": "XAUUSD",
        "side": Side.BUY,
        "volume": 0.05,
        "entry": 4400.0,
        "stop": 4390.0,
        "target": 4420.0,
        "reason": "a level held",
    }
    made.update(over)
    return Intent(**made)


class FakeBroker:
    """Records what it was asked to send."""

    def __init__(self, ok=True, detail="", raises=None):
        self.sent: list[Order] = []
        self.ok = ok
        self.detail = detail
        self.raises = raises

    async def send(self, order: Order) -> OrderResult:
        self.sent.append(order)
        if self.raises is not None:
            raise self.raises
        return OrderResult(ok=self.ok, ticket=99, price=4400.0, volume=order.volume)


def follower(equity: float, *, broker=None, carries=True) -> rp.Follower:
    made = rp.Follower(name="second", broker=broker or FakeBroker())
    made.equity = equity
    made.specs = {"gold": GOLD} if carries else {}
    made.ready = True
    return made


async def test_lots_are_re_derived_not_copied():
    """The whole point. A smaller account takes a smaller position for the same
    decision, so the risk is the same fraction rather than the same lots."""
    # Both large enough to trade at all; 2,000 is refused outright and that is
    # its own test below.
    big, small = follower(10_000.0), follower(4_000.0)
    for f in (big, small):
        await f.copy(intent(), risk_fraction=0.0025, magic=777_701)

    took_big = big.broker.sent[0].volume
    took_small = small.broker.sent[0].volume
    assert took_small < took_big
    # Neither is the volume that travelled on the intent.
    assert took_big != 0.05
    assert took_small != 0.05


async def test_the_decision_and_its_levels_do_travel():
    f = follower(10_000.0)
    await f.copy(intent(), risk_fraction=0.0025, magic=777_701)
    sent = f.broker.sent[0]
    assert sent.stop == 4390.0
    assert sent.target == 4420.0
    assert sent.side is Side.BUY


async def test_the_magic_base_is_the_same_on_every_account():
    """Magic marks these as ours on that terminal, and every account should
    mark them identically. Split mode is where this answer inverts."""
    f = follower(10_000.0)
    await f.copy(intent(), risk_fraction=0.0025, magic=777_715)
    assert f.broker.sent[0].magic == 777_715


async def test_an_account_that_does_not_carry_it_is_refused_not_guessed():
    """No new mechanism - just not sharing one resolved map."""
    f = follower(10_000.0, carries=False)
    got = await f.copy(intent(), risk_fraction=0.0025, magic=777_701)
    assert got.ok is False
    assert "not carried" in got.detail
    assert f.broker.sent == []


async def test_an_account_too_small_for_its_minimum_lot_is_refused():
    """Refused rather than rounded up, which is the `min_stop_vol` argument in
    a different variable."""
    f = follower(5.0)
    got = await f.copy(intent(), risk_fraction=0.0025, magic=777_701)
    assert got.ok is False
    assert f.broker.sent == []


async def test_accounts_are_allowed_to_diverge():
    """Unwinding the filled one to stay symmetric turns a broker's problem into
    a realised loss on an account that did nothing wrong."""
    good = follower(10_000.0)
    bad = follower(10_000.0, broker=FakeBroker(ok=False, detail="no margin"))
    bad.name = "third"
    made = await rp.Replicator([good, bad]).copy(intent(), risk_fraction=0.0025, magic=777_701)

    assert made.diverged is True
    assert len(made.filled) == 1
    assert len(made.refused) == 1
    assert len(made.results) == 2


async def test_a_raising_follower_cannot_break_the_primary():
    boom = follower(10_000.0, broker=FakeBroker(raises=RuntimeError("terminal gone")))
    made = await rp.Replicator([boom]).copy(intent(), risk_fraction=0.0025, magic=777_701)
    assert made.results[0].ok is False
    assert "terminal gone" in made.results[0].detail


async def test_a_follower_that_never_started_takes_nothing():
    f = rp.Follower(name="cold", broker=FakeBroker())
    got = await f.copy(intent(), risk_fraction=0.0025, magic=777_701)
    assert got.ok is False
    assert f.broker.sent == []


def test_no_summary_can_be_mistaken_for_a_single_fill():
    """One decision with two fills and a refusal is three facts."""
    made = rp.Replication(
        (
            rp.Copied("a", True, volume=0.05, ticket=1),
            rp.Copied("b", True, volume=0.01, ticket=2),
            rp.Copied("c", False, "no margin"),
        )
    )
    shown = str(made)
    assert "a" in shown
    assert "b" in shown
    assert "c" in shown
    assert made.diverged is True


def test_followers_are_parsed_from_settings():
    made = rp.from_settings(
        Settings(followers=("second=http://a:8000|key1", "third=http://b:8000"))
    )
    assert [f.name for f in made.followers] == ["second", "third"]


def test_a_malformed_follower_is_dropped_not_raised():
    """A typo must not stop the primary account trading - that is the account
    the decision was made for."""
    made = rp.from_settings(Settings(followers=("nonsense", "=http://a:8000", "ok=http://b")))
    assert [f.name for f in made.followers] == ["ok"]


def test_no_followers_is_the_ordinary_case():
    made = rp.from_settings(Settings())
    assert made.followers == []
    assert made.live == []
