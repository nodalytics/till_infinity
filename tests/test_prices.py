# ------------------------------------- a broker feed nothing else can reach


def test_a_broker_symbol_is_remembered_as_broker_only(monkeypatch):
    """So a caller can ask which feeds exist *only* because the broker carries
    them - which nothing could ask, and which is why eleven of them were
    registered and polled by nothing."""
    from till_infinity import prices as px

    monkeypatch.setenv("PRICES_BROKER_SYMBOLS", "Jump 10 Index,Volatility 25 (1s) Index")
    px.Settings.from_env()
    names = px.broker_feed_names()
    assert "jump_10_index" in names
    assert "volatility_25_1s_index" in names


def test_registering_the_same_symbol_twice_still_reports_it(monkeypatch):
    """A second call adds no new feed, and must still say it is broker-only -
    otherwise a restart forgets which feeds nothing else can reach."""
    from till_infinity import prices as px

    monkeypatch.setenv("PRICES_BROKER_SYMBOLS", "Jump 25 Index")
    px.Settings.from_env()
    px.Settings.from_env()
    assert "jump_25_index" in px.broker_feed_names()


def test_resolve_symbols_stays_narrow(monkeypatch):
    """A one-off `prices bars --symbols gold` should get gold, not the whole
    synthetic book. The union belongs to the running deployment, where the two
    lists describe one intent - not to this function."""
    from till_infinity import prices as px

    monkeypatch.setenv("PRICES_BROKER_SYMBOLS", "Jump 50 Index")
    px.Settings.from_env()
    assert [f.name for f in px.resolve_symbols(["gold"])] == ["gold"]


def test_the_stack_carries_broker_feeds_that_symbols_does_not_name():
    """The handover, and the only test that would have caught this: naming a
    broker symbol registered it, made it tradable and gave it an exposure leg,
    and `SYMBOLS` decided what was actually polled. Zero quotes, zero bars -
    the same silence as a feed that does not exist."""
    import inspect

    from till_infinity import stack

    source = inspect.getsource(stack.Stack._run_prices)
    assert "broker_feed_names()" in source
