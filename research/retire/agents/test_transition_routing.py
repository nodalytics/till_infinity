"""How `agents` routed `statespace.signals`, as it passed when agents was retired.

Moved out of `tests/test_statespace.py::TestTheTransitionTopic`. It asserted that a
statespace transition notice competed with a level call through the same loudest
rule rather than a parallel one, instead of through a path of its own. Its subject
is `agents.service.Window`, which now lives beside this file, so it does not run as
it stands.

The topic still exists and `statespace` can still publish it, but the setting is off
by default now - this was its only consumer.
"""

def test_agents_routes_it_through_the_same_loudest_rule():
    """A notice competes with a level call for the same attention, so it
    goes through the same rule rather than a parallel one - and the Trigger
    is tagged with the topic it came from, not with `SIGNALS`."""
    from till_infinity.agents.service import TOPICS, Settings, Window
    from till_infinity.bus import STATESPACE_SIGNALS

    assert STATESPACE_SIGNALS in TOPICS

    analyst = Window(settings=Settings())
    analyst._signal(
        {"feed": "gold", "score": 4.2, "detail": "break at +4.20", "venue": "deriv"},
        topic=STATESPACE_SIGNALS,
    )
    score, trigger = analyst.loudest["gold"]
    assert score == 4.2
    assert trigger.topic == STATESPACE_SIGNALS
    assert "break at +4.20" in trigger.reason

    # And a louder level call still wins the feed, which is the point of
    # sharing the rule.
    analyst._signal({"feed": "gold", "score": 9.0, "detail": "level swept"})
    assert analyst.loudest["gold"][0] == 9.0
