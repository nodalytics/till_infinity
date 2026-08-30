"""What each level made or lost, and the identity that makes it addable.

The bug this exists for was not missing data. Every closed trade already
journalled its profit and the price it was trading; what was missing was a
**name**, because a level's price moves under its filter. Grouped by price, one
level traded twice reads as two levels with one trade each - and that is
exactly what the record said when it was asked: 117 levels, 119 trades, one
traded more than once.
"""

import json
import sqlite3

import pytest

from till_infinity.journal.ledger import ledger, outcomes, report, totals
from till_infinity.structures.levels import Kalman, Level, Side, agree, dedupe, merge
from till_infinity.structures.volatility import Volatility


def warm(base=4400.0, noise=4.0, bars=400, seed=1):
    import random

    random.seed(seed)
    vol = Volatility()
    for _ in range(bars):
        vol.update(base + random.gauss(0, noise))
    return vol


def level(price, feed="gold", interval="5m", origin="pip"):
    return Level(feed=feed, interval=interval, filter=Kalman(price, 1.0), origin=origin)


# ----------------------------------------------------- the identity itself


def test_two_levels_at_one_price_are_different_levels():
    assert level(4400.0).id != level(4400.0).id


def test_an_id_survives_the_price_moving():
    """The whole point. The filter moves the price whenever the level learns."""
    one = level(4400.0)
    name, before = one.id, one.price
    one.filter.update(4408.0, 4.0, 0.0)
    assert one.price != before
    assert one.id == name


def test_a_merge_keeps_the_surviving_level_s_name():
    """A rediscovered level is evidence about an old one, not a new one - so
    the record has to carry on accumulating under the same name."""
    vol = warm()
    existing = level(4400.0)
    name = existing.id
    found = [level(4400.2)]
    kept = merge([existing], found, vol)
    assert len(kept) == 1
    assert kept[0].id == name


def test_a_dedupe_keeps_one_name_rather_than_inventing_a_third():
    vol = warm()
    a, b = level(4400.0), level(4400.1)
    a.stats(Side.ABOVE).touches = 5.0
    kept = dedupe([a, b], vol)
    assert len(kept) == 1
    assert kept[0].id in {a.id, b.id}


def test_the_pass_that_drew_it_is_still_recorded_separately():
    """`origin` says which formations found it and `id` says which level it is.
    They answer different questions and conflating them would lose one."""
    one = level(4400.0, origin="pip")
    one.origin = agree(one.origin, "run")
    assert one.origin == "pip+run"
    assert one.id != one.origin


# --------------------------------------------------------------- the ledger


def test_two_trades_on_one_level_are_one_record():
    rows = [
        {"profit": 10.0, "level_id": "abc", "feed": "gold", "level": 4400.0, "interval": "5m"},
        {"profit": -4.0, "level_id": "abc", "feed": "gold", "level": 4401.2, "interval": "5m"},
    ]
    got = ledger(rows)
    assert len(got) == 1
    assert got[0].trades == 2
    assert got[0].net == pytest.approx(6.0)
    assert got[0].wins == 1


def test_grouping_by_price_would_have_split_them():
    """Stated as a test because it is the mistake, not a hypothetical: the two
    rows above are one level at two prices."""
    rows = [
        {"profit": 10.0, "level_id": "abc", "feed": "gold", "level": 4400.0},
        {"profit": -4.0, "level_id": "abc", "feed": "gold", "level": 4401.2},
    ]
    by_price = {f"{r['feed']} {r['level']}" for r in rows}
    assert len(by_price) == 2
    assert len(ledger(rows)) == 1


def test_trades_from_before_the_id_existed_are_counted_but_not_merged():
    """Folding them into one enormous level would be a lie and dropping them
    would make the totals not add up."""
    rows = [
        {"profit": 5.0, "level_id": "abc", "feed": "gold"},
        {"profit": -3.0, "level_id": "", "feed": "gold"},
        {"profit": -2.0, "feed": "btc"},
    ]
    got = ledger(rows)
    counts = totals(got)
    assert counts["trades"] == 3
    assert counts["net"] == pytest.approx(0.0)
    unnamed = [r for r in got if not r.named]
    assert len(unnamed) == 1
    assert unnamed[0].trades == 2


def test_records_are_ordered_by_what_they_made():
    rows = [
        {"profit": -9.0, "level_id": "loser"},
        {"profit": 4.0, "level_id": "winner"},
    ]
    assert [r.level_id for r in ledger(rows)] == ["winner", "loser"]


def test_how_a_level_ended_is_counted():
    rows = [
        {"profit": 4.0, "level_id": "a", "exit_kind": "target"},
        {"profit": -3.0, "level_id": "a", "exit_kind": "stop"},
        {"profit": -3.0, "level_id": "a", "exit_kind": "stop"},
    ]
    assert ledger(rows)[0].endings == {"target": 1, "stop": 2}


def test_a_row_with_no_profit_is_not_a_trade():
    assert ledger([{"level_id": "a", "feed": "gold"}]) == []


def test_a_malformed_profit_is_skipped_rather_than_raised_on():
    """A reporting query must not be the thing that fails when one row is bad."""
    assert ledger([{"profit": "nonsense", "level_id": "a"}]) == []


# ------------------------------------------------------------ reading it


def journal_with(tmp_path, rows):
    path = tmp_path / "journal.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE entries (id TEXT, time REAL, kind TEXT, actor TEXT, title TEXT,"
        " rationale TEXT, context TEXT, tags TEXT, confidence REAL, parent TEXT, written REAL)"
    )
    conn.executemany(
        "INSERT INTO entries (time, kind, actor, context) VALUES (?, 'outcome', 'trading', ?)",
        [(float(i), json.dumps(row)) for i, row in enumerate(rows)],
    )
    conn.commit()
    conn.close()
    return path


def test_the_journal_is_read_and_grouped(tmp_path):
    path = journal_with(
        tmp_path,
        [
            {"profit": 10.0, "level_id": "abc", "feed": "gold", "level": 4400.0},
            {"profit": -4.0, "level_id": "abc", "feed": "gold", "level": 4402.0},
            {"profit": 7.0, "level_id": "xyz", "feed": "btc", "level": 78000.0},
        ],
    )
    got = ledger(outcomes(path))
    # xyz nets +7 and abc nets +6, richest first.
    assert [r.level_id for r in got] == ["xyz", "abc"]
    assert totals(got)["trades"] == 3


def test_only_closed_trades_are_read(tmp_path):
    path = journal_with(tmp_path, [{"level_id": "abc", "feed": "gold"}])
    assert list(outcomes(path)) == []


def test_a_report_says_so_when_there_is_nothing(tmp_path):
    path = journal_with(tmp_path, [])
    assert "no closed trades" in report(path)
