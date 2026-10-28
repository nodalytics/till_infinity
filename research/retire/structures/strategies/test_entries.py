"""The second ledger: which strategy's entry is worth taking on a family.

`Policy` keys its arms by *shape*, on purpose, so two strategies with the same
exit pool their evidence. That is right for choosing geometry and it makes the
per-strategy question unaskable. `Entries` asks it, records only, and is
deliberately coarser so its cells are not noise with a ranking printed over them.
"""

from __future__ import annotations

from till_infinity.bus import Bus
from till_infinity.trading import Settings
from till_infinity.trading.service import Trader
from till_infinity.trading.strategies.policy import Entries, context_of, family_of


class TestItRecordsTheStrategyRatherThanTheShape:
    """**`level-scalp` and `sweep-aware` are one arm in the shape ledger.**

    Its docstring says so: crediting them separately "would split one arm's
    evidence in half". Correct for geometry, and it is why nothing the shape
    ledger has learned differs by a strategy name.
    """

    def test_two_strategies_sharing_an_exit_stay_separate_here(self):
        book = Entries()
        for _ in range(40):
            book.observe("gold", "level-scalp", -0.5)
            book.observe("gold", "sweep-aware", +0.4)

        arms = book.ledger.arms("metals/oil")
        assert set(arms) == {"level-scalp", "sweep-aware"}, set(arms)
        assert arms["sweep-aware"].mean > arms["level-scalp"].mean

    def test_it_keys_on_the_family_not_the_instrument(self):
        """Seven families by seventeen strategies is 119 cells. Per instrument it
        would be 700, and per instrument and interval several thousand."""
        book = Entries()
        for _ in range(20):
            book.observe("gold", "snap", 0.2)
            book.observe("silver", "snap", 0.2)

        assert book.ledger.arms("metals/oil")["snap"].seen == 40

    def test_it_does_not_split_by_interval(self):
        """The shape ledger splits by interval and pays for it: 241 cells at 9.7
        observations each. This one cannot afford to."""
        book = Entries()
        for _ in range(30):
            book.observe("eurusd", "thesis-only", 0.1)

        keys = {ctx for ctx, _arm in book.ledger.cells}
        assert keys == {"fx"}, keys


class TestItRefusesToRankOnTooLittle:
    def test_a_cold_cell_reports_nothing(self):
        book = Entries()
        for _ in range(Entries.MIN_SEEN - 1):
            book.observe("btc", "runner", 3.0)

        assert book.ranking("btc") == []
        assert book.ranking("btc", warm_only=False) != []

    def test_it_ranks_once_warm(self):
        book = Entries()
        for _ in range(Entries.MIN_SEEN):
            book.observe("btc", "runner", -0.3)
            book.observe("btc", "ride", +0.6)

        order = [name for name, _ in book.ranking("btc")]
        assert order == ["ride", "runner"], order

    def test_the_readout_says_when_nothing_is_warm(self):
        book = Entries()
        book.observe("gold", "snap", 1.0)
        said = book.describe()
        assert "warm yet" in said, said
        assert "snap" not in said.split("warm yet")[0].split("-")[-1]


class TestTheServiceFeedsAndKeepsIt:
    def test_the_trader_builds_one(self):
        trader = Trader(Bus(), settings=Settings(live=False))
        assert isinstance(trader.entries, Entries)

    def test_crediting_a_strategy_reaches_both_ledgers(self):
        """`_credit` files the shape *and* the strategy. The shape ledger pools
        strategies that share an exit, so without this the per-strategy question
        has no record at all."""
        trader = Trader(Bus(), settings=Settings(live=False))
        trader._credit("sweep-aware", "gold", "15m", 0.75)

        assert trader.entries.ledger.arms("metals/oil")["sweep-aware"].seen == 1
        # And the shape ledger still got it, keyed by geometry rather than name.
        shaped = trader.policy.ledger.arms("metals/oil")
        assert shaped, "the shape ledger should still be credited"
        assert "sweep-aware" not in shaped, sorted(shaped)

    def test_it_survives_the_state_round_trip(self):
        """Learned state, so a deploy must not reset it - the reason `policy` is
        persisted and `pressure` is not."""
        from till_infinity import structures, trading
        from till_infinity.structures.codec import pack, registry, unpack

        book = Entries()
        for _ in range(Entries.MIN_SEEN):
            book.observe("gold", "sweep-aware", 0.4)

        known = {**registry(structures), **registry(trading)}
        back = unpack(pack(book), known)

        assert type(back).__name__ == "Entries", type(back).__name__
        assert back.ledger.arms("metals/oil")["sweep-aware"].seen == Entries.MIN_SEEN


class TestNothingActsOnItYet:
    """**Recording only, and that is the design, not an omission.**

    Whether the strategy-by-instrument interaction exists is unmeasured: 904
    closed trades over 13 strategies and 33 instruments is 2.1 per cell. This
    exists so the question can be settled on evidence.
    """

    def test_no_production_code_reads_the_ranking(self):
        import pathlib

        root = pathlib.Path("till_infinity")
        readers = [
            f"{path}:{n}"
            for path in root.rglob("*.py")
            for n, line in enumerate(path.read_text().splitlines(), 1)
            # `describe` is a readout and may be called; `ranking` is the one
            # that would make a decision.
            if "entries.ranking" in line and "policy.py" not in str(path)
        ]
        assert not readers, f"something now acts on Entries: {readers}"


def test_the_family_refactor_left_the_context_keys_alone():
    """`context_of` was split so both ledgers share one definition of a family.
    The shape policy's keys must be byte-identical or its whole ledger orphans."""
    assert context_of("gold", "15m") == ("metals/oil|15m", "metals/oil", "")
    assert context_of("volatility_25_index", "1m") == ("volatility|1m", "volatility", "")
    for feed, want in (
        ("gold", "metals/oil"),
        ("eurusd", "fx"),
        ("btc", "crypto"),
        ("crash_1000_index", "crash"),
        ("boom_500_index", "boom"),
        ("step_index", "volatility"),
        ("us100", "index"),
    ):
        assert family_of(feed) == want, (feed, family_of(feed))
