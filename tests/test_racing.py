"""Which wall price reaches first, and the label that has to exist first."""

import pytest

from till_infinity.structures.learning import racing
from till_infinity.structures.learning.racing import MIN_SEEN, Races


def band(position=0.5, up=2.0, down=2.0, width=4.0):
    return {
        "range_position": position,
        "room_up_vol": up,
        "room_down_vol": down,
        "range_width_vol": width,
    }


def test_a_race_resolves_on_the_bound_price_reaches():
    race = Races()
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())

    assert race.step("gold", 4330.0) is None  # still between them
    assert race.step("gold", 4341.0) == "upper"
    assert race.model.seen == 1


def test_the_floor_resolves_the_other_way():
    race = Races()
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())

    assert race.step("gold", 4319.5) == "lower"
    assert "gold" not in race.open


def test_a_resolved_race_is_not_resolved_twice():
    """It is removed on resolution, so the next tick is not a second
    observation of the same event."""
    race = Races()
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())
    race.step("gold", 4341.0)

    assert race.step("gold", 4342.0) is None
    assert race.model.seen == 1


def test_a_newer_channel_supersedes_the_one_open_on_that_feed():
    """Two races on one instrument would resolve on the same tick and enter the
    same observation twice."""
    race = Races()
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())
    race.watch("gold", upper=4350.0, lower=4330.0, features=band())

    assert len(race.open) == 1
    # The old ceiling is inside the new channel, so it must not resolve.
    assert race.step("gold", 4341.0) is None
    assert race.step("gold", 4351.0) == "upper"


def test_a_one_sided_channel_is_not_a_race():
    """With no ceiling there is nothing for the floor to beat, and opening one
    would put a resolution in the record the model could never have
    predicted."""
    race = Races()
    race.watch("gold", upper=0.0, lower=4320.0, features=band())

    assert race.open == {}


def test_an_inverted_channel_is_refused():
    race = Races()
    race.watch("gold", upper=4320.0, lower=4340.0, features=band())

    assert race.open == {}


def test_a_stale_race_is_dropped_rather_than_resolved():
    """A channel this old was drawn against levels that have since moved.
    Letting it resolve would credit the model for a prediction about a picture
    that no longer exists."""
    race = Races()
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())
    opened = race.open["gold"].opened

    got = race.step("gold", 4341.0, now=opened + racing.STALE_SECONDS + 1)

    assert got is None
    assert race.open == {}
    assert race.model.seen == 0


def test_it_says_nothing_until_it_has_seen_enough():
    """`None` rather than 0.5 - "no opinion" and "an even chance" are different
    claims, and a consumer that cannot tell them apart will act on the second
    when it was given the first."""
    race = Races()

    assert race.predict(band()) is None
    assert race.reading(band()) == {}
    assert race.warm is False


def test_a_warm_model_reports_a_probability_and_its_sample():
    race = Races()
    for i in range(int(MIN_SEEN) + 5):
        race.watch("gold", upper=4340.0, lower=4320.0, features=band(up=1.0, down=3.0))
        race.step("gold", 4341.0 if i % 2 else 4319.0)

    got = race.reading(band(up=1.0, down=3.0))

    assert race.warm
    assert 0.0 <= got["up_first"] <= 1.0
    # `seen` is a decayed count, not a tally, and `reading` rounds it - so
    # this compares against the rounded value rather than the raw one.
    assert got["up_first_seen"] == pytest.approx(round(race.model.seen, 1))


def test_a_warm_model_still_declines_a_one_sided_channel():
    """The reading is about two distances. With one missing there is no race,
    whatever the weights say."""
    race = Races()
    for i in range(int(MIN_SEEN) + 5):
        race.watch("gold", upper=4340.0, lower=4320.0, features=band())
        race.step("gold", 4341.0 if i % 2 else 4319.0)

    assert race.warm
    assert race.predict(band(up=0.0)) is None
    assert race.predict(band(down=0.0)) is None


def test_it_learns_the_side_it_is_shown():
    """The cheapest possible check that the label reaches the weights: feed it
    channels that always resolve upward and it must lean upward."""
    race = Races()
    for _ in range(int(MIN_SEEN) + 40):
        race.watch(
            "gold", upper=4340.0, lower=4320.0, features=band(position=0.9, up=0.5, down=3.5)
        )
        race.step("gold", 4341.0)

    assert race.predict(band(position=0.9, up=0.5, down=3.5)) > 0.5


def test_changing_the_recipe_drops_what_was_learned_under_the_old_one():
    """Statistics gathered under a different meaning of the inputs are not
    carried. `slowing` is why this exists - see breaking.py."""
    race = Races()
    for i in range(int(MIN_SEEN) + 5):
        race.watch("gold", upper=4340.0, lower=4320.0, features=band())
        race.step("gold", 4341.0 if i % 2 else 4319.0)
    assert race.warm

    race.recipe = "something else"
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())

    assert race.model.seen == 0
    assert race.warm is False


def test_forgetting_a_feed_leaves_no_race_behind():
    race = Races()
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())
    race.forget("gold")

    assert race.step("gold", 4341.0) is None


# ------------------------------------------------- the control, which travels


def test_the_geometric_rule_is_scored_on_the_same_races():
    """84.1% accuracy over 252 live races is the *expected* result of learning
    nothing but the geometry - the nearer bound usually wins - and is
    indistinguishable from a real edge without this. The number that means
    something is the gap."""
    race = Races()
    # Price near the ceiling, and the ceiling wins: the rule is right.
    race.watch("gold", upper=4340.0, lower=4320.0, features=band(position=0.9))
    race.step("gold", 4341.0)
    # Price near the ceiling, and the floor wins: the rule is wrong.
    race.watch("gold", upper=4340.0, lower=4320.0, features=band(position=0.9))
    race.step("gold", 4319.0)

    assert race.naive_seen == 2
    assert race.naive_right == 1
    assert race.naive == pytest.approx(0.5)


def test_the_edge_is_the_model_against_the_rule_and_can_be_negative():
    """A model that has learned the geometry and nothing else scores zero here
    however high its accuracy reads."""
    race = Races()
    for i in range(int(MIN_SEEN) + 5):
        race.watch("gold", upper=4340.0, lower=4320.0, features=band(position=0.9))
        race.step("gold", 4341.0 if i % 2 else 4319.0)

    assert race.naive is not None
    assert race.edge == pytest.approx(race.model.accuracy - race.naive)


def test_the_control_says_nothing_before_a_race_resolves():
    race = Races()

    assert race.naive is None
    assert race.edge is None


def test_the_control_is_dropped_with_the_rest_on_a_recipe_change():
    """Statistics gathered under a different meaning of the inputs are not
    carried, and a control carried across a reset would be scored against a
    model that no longer shares its sample."""
    race = Races()
    race.watch("gold", upper=4340.0, lower=4320.0, features=band(position=0.9))
    race.step("gold", 4341.0)
    assert race.naive_seen == 1

    race.recipe = "something else"
    race.watch("gold", upper=4340.0, lower=4320.0, features=band())

    assert race.naive_seen == 0
    assert race.naive is None
