"""Every service the stack names must actually be reachable."""

from __future__ import annotations

import pytest

from till_infinity import stack as st


@pytest.mark.parametrize("name", st.ORDER)
def test_every_service_in_the_order_has_a_runner(name):
    assert hasattr(st.Stack(st.Plan()), f"_run_{name}")


def test_the_entry_points_each_service_calls_exist():
    """`notifications` died on start for three deploys because `nt.listen` was
    written, tested, and never exported — the stack referenced a name the
    package did not have, and only a running container said so."""
    from till_infinity import agents as ag
    from till_infinity import journal as jr
    from till_infinity import news as nw
    from till_infinity import notifications as nt
    from till_infinity import prices as px
    from till_infinity import structures as sx

    assert callable(nt.listen)
    assert callable(jr.listen)
    assert callable(ag.watch)
    assert callable(sx.Watcher)
    assert callable(px.collect)
    assert callable(nw.collect)
