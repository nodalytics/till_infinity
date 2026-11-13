"""The dashboard against the functions the desk is judged by.

`web/api/data.py` exists to window and shape, not to score. The two places
where it repeats something `strategies.report` does - bucketing trades into
groups, and counting gate refusals - are there only because `report.build` and
`report.declines` take no time window, and this is what stops them becoming a
second scoring rule that quietly disagrees with the first.

These are cheap because the journal is written here, by the production writer,
rather than read from a machine that may or may not have one.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from till_infinity.journal import Entry, Journal, Kind
from till_infinity.strategies import report
from web.api import data

#: The repository root, which is what `web` is importable from.
ROOT = pathlib.Path(__file__).resolve().parents[1]

#: `(strategy, feed, profit, decision risk, outcome risk)`. The last row
#: carries the zero that `report.trades` has to fall back from.
ROWS = [
    ("level-scalp", "gold", 52.2, 25.2, 25.2),
    ("level-scalp", "gold", -24.8, 25.2, 25.2),
    ("sweep-aware", "us100", 40.1, 25.1, 25.1),
    ("sweep-aware", "gold", -25.0, 25.0, 25.0),
    ("fade-to-value", "btc", 13.5, 24.8, 0.0),
]

START = 1_700_000_000.0


@pytest.fixture
def journal(tmp_path):
    """A journal holding five closed trades and three refusals."""
    path = tmp_path / "journal.db"
    writer = Journal(path)
    writer.connect()

    entries: list[Entry] = []
    for index, (strategy, feed, profit, risk, closed_risk) in enumerate(ROWS):
        opened = START + index * 3600
        decision = Entry(
            title=f"live: buy {feed} #{index}",
            kind=Kind.DECISION,
            actor="trading",
            context={
                "strategy": strategy,
                "feed": feed,
                "side": "buy",
                "mode": "live",
                "risk_money": risk,
                "entry": 100.0 + index,
                "stop": 99.0 + index,
                "target": 104.0 + index,
                "interval": "5m",
            },
            time=opened,
        )
        entries.append(decision)
        entries.append(
            Entry(
                title=f"closed #{index}",
                kind=Kind.OUTCOME,
                actor="trading",
                parent=decision.id,
                context={
                    "profit": profit,
                    "risk_money": closed_risk,
                    "seconds": 120.0,
                    "exit": 101.0 + index,
                    "reason": "closed",
                    "exit_source": "broker",
                    "exit_kind": "target" if profit > 0 else "stop",
                },
                time=opened + 120,
            )
        )

    for index, gate in enumerate(("spread", "spread", "reward_to_risk")):
        entries.append(
            Entry(
                title=f"refused #{index}",
                kind=Kind.OBSERVATION,
                actor="trading",
                context={"gate": gate},
                time=START + index * 7200,
            )
        )

    writer.append(entries)
    writer.shut()
    return path


def test_grouping_matches_the_report_at_the_full_window(journal):
    """`data.groups` must bucket exactly as `report.build` does.

    Fails if either gains a key the other does not have, or if the same key
    reports a different count or mean R - which is what a divergent definition
    of "a strategy's trades" would look like from the outside. The dashboard
    would then show one set of per-strategy numbers while `report` printed
    another, and both would look authoritative.
    """
    built = report.build(journal)
    overall, by_strategy, by_feed = data.groups(report.trades(journal))

    assert overall.count == built.overall.count
    assert overall.mean_r == pytest.approx(built.overall.mean_r)
    assert overall.total_r == pytest.approx(built.overall.total_r)

    for mine, theirs in ((by_strategy, built.by_strategy), (by_feed, built.by_feed)):
        assert mine.keys() == theirs.keys()
        for name, group in mine.items():
            assert group.count == theirs[name].count
            assert group.mean_r == pytest.approx(theirs[name].mean_r)


def test_windowed_declines_match_the_report_when_the_window_is_everything(journal):
    """Counting refusals over a window must agree with counting them over all.

    `data.declines` has two paths - delegate, or count by hand over a time
    filter - and nothing else would notice if the hand-written one started
    reading a different key or missing the last entry. A window that reaches
    before the first refusal and after the last has to produce the tally
    `report.declines` produces.
    """
    assert data.declines(journal) == report.declines(journal)
    windowed = data.declines(journal, since=START - 1, until=START + 100_000)
    assert windowed == report.declines(journal)


def test_a_window_that_excludes_a_refusal_drops_exactly_that_one(journal):
    """The control for the test above: the window has to be able to exclude.

    Without this, a `declines` that ignored its window entirely would pass
    the agreement test and look correct.
    """
    narrow = data.declines(journal, since=START + 7200)
    assert narrow == {"spread": 1, "reward_to_risk": 1}


def test_a_zero_risk_outcome_keeps_the_risk_its_decision_was_sized_for(journal):
    """The fifth trade must appear, with the R its decision's risk implies.

    `report.trades` falls back to the decision's `risk_money` when the outcome
    zeroes it, because a position adopted across a restart spreads an intent
    with no sizing on top of one that had it: 839 of 1,486 closed trades in the
    live journal carried that zero. If the dashboard ever stopped going through
    `report.trades`, this trade would vanish from the page and the page would
    not say so.
    """
    found = data.overview(journal)
    assert found.overall.count == len(ROWS)
    adopted = next(trade for trade in found.trades if trade.feed == "btc")
    assert adopted.risk_money == pytest.approx(24.8)
    assert adopted.r == pytest.approx(13.5 / 24.8)


def test_geometry_only_describes_trades_the_report_accepted(journal):
    """Markers hang off trades `report` kept, and carry real prices.

    `geometry` is the one place the dashboard reads journal entries itself. It
    must not invent a trade the report dropped, and must not fill a missing
    price with zero - which on a price axis is a marker at the bottom of the
    chart rather than an absent one.
    """
    found = data.overview(journal)
    places = data.geometry(journal)
    assert len(places) == len(found.trades)
    for trade in found.trades:
        assert trade.entry_price is not None
        assert trade.exit_price is not None
        assert trade.closed is not None
        assert trade.closed > trade.opened

    marks = data.markers(found.trades, "gold", "5m")
    assert [mark.kind for mark in marks].count("entry") == 3
    assert all(mark.time % data.SECONDS["5m"] == 0 for mark in marks)


def test_the_dashboard_imports_no_adapter_and_no_node():
    """Nothing the API imports is a route to a broker.

    The service reads the journal and `strategies.report`; `strategies`
    re-exports the desks, so `Strategy` classes are in memory, but an order
    needs a node with an execution client registered. If an import under
    `adapters/` or `node/` ever appears in this service, this fails before
    anybody deploys a dashboard that can trade.

    In a subprocess because `sys.modules` in the test process holds whatever
    the rest of the suite has already imported, and asserting against that
    would pass or fail on test ordering rather than on this import graph.
    """
    probe = (
        "import sys; import web.api.main;"
        " print([m for m in sys.modules if '.adapters' in m or '.node' in m])"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if done.returncode and "fastapi" in done.stderr:
        pytest.skip("fastapi is not installed; `uv sync --extra dashboard`")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout
