"""Does a replay resemble the desk it claims to describe.

`sweepstops.py` reported that **98.8%** of `sweep-aware`'s trades end on the
stop. The live desk running that policy ends **13%** of them on the stop and 66%
on the hold timeout - and the mean R figures agreed, +0.032 replayed against
+0.134 live. The number everyone looks at matched while the mechanics did not.
"""

from till_infinity.shared.crosscheck import MIN_LIVE, agree, fingerprint


def closes(mix: dict[str, int], *, seconds: float = 300.0, best: float = 0.4):
    """Closes with a given exit mix, everything else held constant."""
    return [
        {"exit_kind": kind, "seconds": seconds, "best_r": best}
        for kind, count in mix.items()
        for _ in range(count)
    ]


def test_the_observed_case_does_not_reproduce():
    """98.8% stop replayed against 13% live, which is the case this exists for."""
    replayed = fingerprint(closes({"stop": 988, "target": 12}, seconds=1800.0))
    live = fingerprint(closes({"hold": 55, "stop": 11, "target": 6, "stale": 11}))

    got = agree(replayed, live)

    assert got.judged is True
    assert got.reproduces is False
    assert "exit mix" in got.render()
    assert "does NOT reproduce" in got.render()


def test_a_matching_mix_reproduces():
    replayed = fingerprint(closes({"hold": 60, "stop": 25, "target": 15}))
    live = fingerprint(closes({"hold": 55, "stop": 28, "target": 17}))

    got = agree(replayed, live)

    assert got.reproduces is True
    assert "does NOT" not in got.render()


def test_mean_r_may_differ_wildly_while_the_structure_matches():
    """The thing the check exists to ignore. A replay walks every published call
    and `risk.py` refuses the expensive ones, so the desk pays a median 0.081R of
    spread where the replayed population averages 0.363R. Those means *should*
    differ, and a check that fired on it would fire on every healthy replay."""
    replayed = fingerprint(closes({"hold": 60, "stop": 40}, best=2.5))
    live = fingerprint(closes({"hold": 58, "stop": 42}, best=0.2))

    assert agree(replayed, live).reproduces is True


def test_a_small_live_sample_gets_no_verdict():
    """`confluence-scalp` at n=11 is exactly where a threshold fires on noise.
    Report, do not judge - the same resolution `strata.min_n` reached."""
    replayed = fingerprint(closes({"stop": 900, "hold": 100}))
    live = fingerprint(closes({"hold": 6, "stop": 4}))

    got = agree(replayed, live)

    assert got.judged is False
    assert got.reproduces is None
    assert "too few live closes" in got.render()
    assert "10" in got.render(), "the counts are still shown"


def test_an_exit_kind_the_replay_cannot_produce_is_structural():
    """`stale` is 12% of `thesis-only` and the replay has no concept of it. A
    simulation with three possible endings being compared to a desk with four is
    mismatched before a single bar is walked, and reporting that as a percentage
    gap would understate it."""
    replayed = fingerprint(closes({"stop": 50, "hold": 50}))
    live = fingerprint(closes({"stop": 45, "hold": 43, "stale": 12}))

    got = agree(replayed, live)

    assert "stale" in got.structural
    assert got.reproduces is False
    assert "cannot produce" in got.render()


def test_a_missing_exit_kind_is_counted_not_folded_in():
    """`exit_kind` is simply absent on 8% of `sweep-aware` closes and 20% of
    `fade-to-value`. That is a liveness problem in the field this check depends
    on, and treating unknown as a fourth category would hide it."""
    got = fingerprint(
        [{"exit_kind": "stop", "seconds": 1.0}, {"seconds": 1.0}, {"exit_kind": None}]
    )

    assert got.unknown == 2
    assert got.n == 1, "only the closes that said how they ended"
    assert "unknown" not in got.mix


def test_hold_duration_is_checked_on_its_own():
    """The underlying error was a harness holding 1,440 bars where the desk holds
    30 - a 48-fold difference that the exit mix alone would not have named."""
    replayed = fingerprint(closes({"hold": 60, "stop": 40}, seconds=1800.0))
    live = fingerprint(closes({"hold": 58, "stop": 42}, seconds=381.0))

    got = agree(replayed, live)

    assert got.reproduces is False
    assert "hold secs" in got.render()


def test_an_empty_side_is_not_a_verdict():
    """A replay that produced nothing and a desk that has traded nothing are both
    absences, and an absence is not agreement."""
    assert agree(fingerprint([]), fingerprint(closes({"stop": 100}))).judged is False
    assert agree(fingerprint(closes({"stop": 100})), fingerprint([])).judged is False


def test_the_threshold_is_the_one_the_observed_case_justifies():
    """25 points on any kind, against an observed 86. Pinned so that loosening it
    has to be a decision somebody makes and defends."""
    from till_infinity.shared import crosscheck

    assert crosscheck.MIX_POINTS == 0.25
    assert crosscheck.HOLD_RATIO == 2.0
    assert MIN_LIVE == 30
