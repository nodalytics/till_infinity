"""The alert transports: one message, two wire formats, and no shared fate.

An alert is how a person finds out the desk is broken, so this path is read on
the worst day and on no other. **Measured on one of those: `notify` opened
every channel in a single `AsyncExitStack`, which enters its contexts in
sequence - so a notifier that raised on `__aenter__` meant nothing after it was
even attempted.** The order is `DEFAULT_TARGETS`, Telegram first, so a sick
Telegram session took Discord down with it, on the day both the broker and the
terminal were already unreachable. Each channel opens its own session now.

The rest of the file is the two translations and the ways a provider says no.
Telegram wants escaped HTML in one string and answers `{"ok": false}` with HTTP
200; Discord wants an embed and answers 204 with no body at all, so neither
status code nor emptiness can decide success. Both rate-limit with a number
worth keeping and both report a dead credential as something a retry cannot
fix - and a retry loop that cannot tell transient from permanent either gives
up on a working channel or hammers a revoked one.

The credential itself is the quiet constraint: a Telegram token lives in the
URL and a Discord webhook *is* the URL, so anything that logs or renders a
channel has to mask it. `truncate` and the field caps exist because a provider
rejects an oversized payload outright, which turns a long alert into no alert.
"""

import httpx
import pytest

from till_infinity.notifications import (
    Channel,
    DiscordNotifier,
    Level,
    Notification,
    Settings,
    TelegramNotifier,
    build_notifiers,
    notify,
    parse_channels,
    send_one,
    truncate,
)
from till_infinity.notifications.config import DISCORD_DESCRIPTION_LIMIT, TELEGRAM_TEXT_LIMIT
from till_infinity.notifications.notifier import (
    NotConfiguredError,
    PermanentError,
    TransientError,
)

OPS = Channel("telegram", "-100999", "ops")
HOOK = Channel("discord", "https://discord.com/api/webhooks/1/abc", "alerts")

FULL = Settings(
    telegram_token="123:AA-secret",
    telegram_chats=(OPS,),
    discord_webhooks=(HOOK,),
    retries=2,
)


def mock(notifier, handler):
    """Give a notifier a transport instead of the network."""
    notifier._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return notifier


def alert(**kw) -> Notification:
    return Notification(
        title=kw.pop("title", "Gold spread blew out"),
        body=kw.pop("body", "OANDA 4.2bps vs Pepperstone 0.2bps"),
        **kw,
    )


# ---------------------------------------------------------------- the message


def test_a_level_arrives_as_a_word_or_an_ordinal_and_nonsense_raises():
    """`shared/contracts/bus/alerts.json` allows either encoding, and a
    publisher sending `2` where `"critical"` was expected is how the critical
    bypass was once filtered like a topic preference."""
    assert Level.parse("warning") is Level.WARNING
    assert Level.parse("CRITICAL") is Level.CRITICAL
    assert Level.parse(None) is Level.INFO
    assert Level.parse(2) is Level.CRITICAL
    with pytest.raises(ValueError, match="unknown level"):
        Level.parse("shouty")


def test_an_alert_carries_the_instrument_symbol_beside_the_shape():
    """Two questions, two marks: what happened, and to what.

    A phone notification is read at a glance, and "📈 ₿" separates from "📈 €"
    before a single word of the title has been.
    """
    from till_infinity.notifications.models import Notification

    up_btc = Notification(
        title="BTC 3m - up", fields={"shape": "level", "instrument": "btc", "direction": "up"}
    )
    down_gold = Notification(
        title="GOLD 3m - down", fields={"shape": "level", "instrument": "gold", "direction": "down"}
    )
    assert up_btc.mark == "📈 ₿"
    assert down_gold.mark == "📉 🥇"
    assert up_btc.as_text().startswith("📈 ₿ BTC")


def test_the_symbol_shows_on_findings_that_have_no_direction():
    """A stale feed is still about an instrument."""
    from till_infinity.notifications.models import Notification

    stale = Notification(
        title="OANDA gold feed stale", fields={"shape": "stale", "instrument": "gold"}
    )
    assert stale.mark == "💤 🥇"


def test_an_instrument_without_a_symbol_keeps_the_plain_icon():
    """No placeholder standing in for an answer we do not have."""
    from till_infinity.notifications.models import Notification

    odd = Notification(title="something", fields={"shape": "level", "instrument": "platinum"})
    assert odd.mark == "📊"


# **`test_every_tracked_instrument_has_a_symbol` left with its subject.**
# It checked `notifications.models.INSTRUMENTS` against
# `prices.DEFAULT_SYMBOLS`, and `prices/` is retired to `research/retire/`.
# The instrument list now comes from the terminal itself through
# `adapters/mt5/providers.py`, which builds each one from its own `digits` and
# `volume_step` - so the assertion worth having is that the provider and the
# map agree, and it belongs beside the provider once the alert path is ported.


def test_symbols_tell_the_instruments_apart():
    """A shared sign is worse than none - ¥ on both yen and yuan reads as one."""
    from till_infinity.notifications.models import INSTRUMENTS

    assert len(set(INSTRUMENTS.values())) == len(INSTRUMENTS)


def test_a_headline_containing_markup_does_not_break_the_parse():
    """A symbol like EUR<USD or an & in a headline must not break the parse."""
    text = alert(title="EUR<USD & gold", body="a > b").as_text(escape=True)
    assert "EUR&lt;USD &amp; gold" in text
    assert "a &gt; b" in text
    assert "<b>" in text  # our own markup survives


def test_the_fields_and_the_link_reach_the_reader():
    """The link is what a reader opens to see the chart, and dropping it leaves
    an alert that can only be acted on from memory."""
    text = alert(fields={"spread_bps": "4.2"}, url="https://example.com").as_text()
    assert "spread_bps: 4.2" in text
    assert "https://example.com" in text


def test_the_fields_the_filter_routes_on_are_not_also_printed():
    """`instrument: gold` under a headline containing "gold" is noise."""
    text = alert(fields={"instrument": "gold", "shape": "level"}).as_text()
    assert "instrument: gold" not in text
    assert "shape: level" not in text


def test_a_cut_message_says_it_was_cut():
    """Silent truncation reads as a complete sentence, which is the same trap
    `utils/logging` hit with rich's 80-column fallback eating a scoreboard."""
    assert truncate("abc", 10) == "abc"
    cut = truncate("x" * 100, 20)
    assert len(cut) == 20
    assert cut.endswith("[…]")
    assert truncate("abc", 0) == "abc"  # no limit means no cut


# --------------------------------------------------------------------- payload


def test_an_oversized_telegram_message_is_cut_rather_than_rejected():
    """Telegram refuses the whole request past its limit, so an alert long
    enough to matter would be the one that never arrives."""
    notifier = TelegramNotifier(FULL, OPS)
    payload = notifier.payload(alert(body="y" * 9000))
    assert payload["chat_id"] == "-100999"
    assert payload["parse_mode"] == "HTML"
    assert len(payload["text"]) <= TELEGRAM_TEXT_LIMIT


def test_the_telegram_token_lives_in_the_url_not_the_payload():
    notifier = TelegramNotifier(FULL, OPS)
    assert "123:AA-secret" in notifier.api("sendMessage")
    assert "secret" not in str(notifier.payload(alert()))


def test_a_discord_embed_carries_the_level_as_its_colour():
    """Colour is read before any word of the title, which is the whole reason
    level exists on a message that already says what happened."""
    notifier = DiscordNotifier(FULL, HOOK)
    payload = notifier.payload(alert(level=Level.CRITICAL, fields={"instrument": "gold"}))
    (embed,) = payload["embeds"]
    assert embed["color"] == 0xD9534F
    assert embed["fields"][0] == {"name": "instrument", "value": "gold", "inline": True}


def test_an_oversized_discord_description_is_cut_rather_than_rejected():
    notifier = DiscordNotifier(FULL, HOOK)
    (embed,) = notifier.payload(alert(body="z" * 9000))["embeds"]
    assert len(embed["description"]) <= DISCORD_DESCRIPTION_LIMIT


def test_discord_sends_no_more_fields_than_it_accepts():
    """25 is Discord's own limit on an embed; a 26th field fails the request
    and loses the alert rather than the field."""
    notifier = DiscordNotifier(FULL, HOOK)
    many = {f"k{i}": str(i) for i in range(40)}
    (embed,) = notifier.payload(alert(fields=many))["embeds"]
    assert len(embed["fields"]) == 25


# -------------------------------------------------------------------- sending


@pytest.mark.asyncio
async def test_the_telegram_token_is_in_the_path_and_not_the_body():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    notifier = mock(TelegramNotifier(FULL, OPS), handler)
    result = await notifier.send(alert())
    assert result.ok
    assert seen["url"].endswith("/bot123:AA-secret/sendMessage")


@pytest.mark.asyncio
async def test_an_ok_false_body_is_a_failure_despite_the_200():
    """Telegram reports a bad chat id this way, so a status check alone counts
    an undelivered alert as sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "chat not found"})

    result = await mock(TelegramNotifier(FULL, OPS), handler).send(alert())
    assert not result.ok
    assert "chat not found" in result.detail


@pytest.mark.asyncio
async def test_an_empty_204_is_a_success_and_not_an_empty_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    assert (await mock(DiscordNotifier(FULL, HOOK), handler).send(alert())).ok


@pytest.mark.asyncio
async def test_a_revoked_credential_is_permanent_rather_than_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"description": "Unauthorized"})

    with pytest.raises(PermanentError, match="401"):
        await mock(TelegramNotifier(FULL, OPS), handler).send(alert())


@pytest.mark.asyncio
async def test_a_rate_limit_is_transient_and_carries_the_wait():
    """Both providers say exactly how long to wait; the number is worth keeping."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"retry_after": 7})

    with pytest.raises(TransientError) as caught:
        await mock(DiscordNotifier(FULL, HOOK), handler).send(alert())
    assert caught.value.retry_after == 7.0


@pytest.mark.asyncio
async def test_the_telegram_wait_is_read_from_its_own_nesting():
    """The same number as Discord's, one level deeper. Read off the top level
    it is absent, and an absent wait becomes a default nobody measured."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"parameters": {"retry_after": 3}})

    with pytest.raises(TransientError) as caught:
        await mock(TelegramNotifier(FULL, OPS), handler).send(alert())
    assert caught.value.retry_after == 3.0


@pytest.mark.asyncio
async def test_a_providers_wait_is_capped_at_something_survivable():
    """Telegram answers with hours during a ban. Honouring it would park the
    alerting path for the rest of the outage it is meant to report."""
    settings = Settings(discord_webhooks=(HOOK,), max_retry_after=30.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "9000"})

    with pytest.raises(TransientError) as caught:
        await mock(DiscordNotifier(settings, HOOK), handler).send(alert())
    assert caught.value.retry_after == 30.0


@pytest.mark.asyncio
async def test_a_channel_that_never_recovers_is_reported_not_retried_forever():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    notifier = mock(DiscordNotifier(FULL, HOOK), handler)
    result = await send_one(notifier, alert(), FULL)
    assert not result.ok
    assert calls["n"] == FULL.retries


@pytest.mark.asyncio
async def test_a_transient_failure_that_recovers_is_delivered():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(204)

    result = await send_one(mock(DiscordNotifier(FULL, HOOK), handler), alert(), FULL)
    assert result.ok
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_sending_without_credentials_reports_rather_than_raises():
    notifier = mock(
        DiscordNotifier(Settings(), Channel("discord", "")), lambda r: httpx.Response(204)
    )
    result = await send_one(notifier, alert(), Settings())
    assert not result.ok
    assert "DISCORD_WEBHOOK_URL" in result.detail

    with pytest.raises(NotConfiguredError):
        await notifier.send(alert())


# ------------------------------------------------------------------ selection


def test_a_channel_with_no_credential_is_not_built_at_all():
    """A notifier that exists and cannot send is a delivery that fails on the
    worst day rather than a destination nobody configured."""
    assert [n.name for n in build_notifiers(None, FULL)] == ["telegram[ops]", "discord[alerts]"]
    telegram_only = Settings(telegram_token="t", telegram_chats=(OPS,))
    assert [n.name for n in build_notifiers(None, telegram_only)] == ["telegram[ops]"]
    assert build_notifiers(None, Settings()) == []


def test_one_notifier_per_channel():
    """Four chats and two webhooks are six independent deliveries."""
    settings = Settings(
        telegram_token="t",
        telegram_chats=parse_channels("a=-1,b=-2,c=-3,d=-4", "telegram"),
        discord_webhooks=parse_channels("x=https://h/1,y=https://h/2", "discord"),
    )
    names = [n.name for n in build_notifiers(None, settings)]
    assert names == [
        "telegram[a]",
        "telegram[b]",
        "telegram[c]",
        "telegram[d]",
        "discord[x]",
        "discord[y]",
    ]


def test_a_telegram_chat_without_a_token_is_not_ready():
    assert build_notifiers(("telegram",), Settings(telegram_chats=(OPS,))) == []


def test_an_unknown_target_is_refused_rather_than_ignored():
    """Ignoring it would be an alerting path with no destinations that reports
    itself as configured."""
    with pytest.raises(ValueError, match="unknown target"):
        build_notifiers(("carrier-pigeon",), FULL)


def test_a_token_with_no_chats_is_not_a_configured_destination():
    assert Settings().configured() == ()
    assert FULL.configured() == ("telegram", "discord")
    assert Settings(telegram_token="t").configured() == ()  # no chats


@pytest.mark.asyncio
async def test_an_unconfigured_desk_is_quiet_rather_than_broken():
    """Most nodes have no alerting set up, and raising here would make the
    absence of a Telegram token a reason a desk cannot run."""
    assert await notify(alert(), settings=Settings()) == []


@pytest.mark.asyncio
async def test_one_dead_destination_does_not_block_the_other(monkeypatch):
    """A partial delivery must be visible, not swallowed."""

    async def failing_send(self, notification):
        raise PermanentError("discord: HTTP 404 unknown webhook")

    monkeypatch.setattr(DiscordNotifier, "send", failing_send)

    async def ok_send(self, notification):
        from till_infinity.notifications import Delivery

        return Delivery(self.name, ok=True)

    monkeypatch.setattr(TelegramNotifier, "send", ok_send)

    results = {d.target: d for d in await notify(alert(), settings=FULL)}
    assert results["telegram[ops]"].ok
    assert not results["discord[alerts]"].ok


# ---------------------------------------------------------------- many channels


def test_a_channel_carries_its_own_label_and_its_own_floor():
    (ops, feed) = parse_channels("ops=-1001111|warning, -1002222", "telegram")
    assert (ops.label, ops.address, ops.min_level) == ("ops", "-1001111", Level.WARNING)
    # Unlabelled entries are numbered so a log line can still identify them.
    assert (feed.label, feed.address, feed.min_level) == ("2", "-1002222", Level.INFO)


def test_a_url_is_never_mistaken_for_a_label():
    """`https://…` contains an '=' only in query strings, but always a ':' and
    '/' before it - so the label pattern must not match a URL."""
    (hook,) = parse_channels("https://discord.com/api/webhooks/1/abc?x=1", "discord")
    assert hook.address == "https://discord.com/api/webhooks/1/abc?x=1"
    assert hook.label == "1"


def test_a_trailing_comma_does_not_become_an_empty_channel():
    """Hand-edited env files end in separators, and an empty address would be
    a notifier that fails every send."""
    assert parse_channels("", "telegram") == ()
    assert parse_channels(" , ,", "telegram") == ()
    assert len(parse_channels("a=-1, , b=-2", "telegram")) == 2


def test_webhooks_are_masked_but_chat_ids_are_not():
    """A webhook URL is a credential; a chat id only names a room."""
    assert HOOK.masked == "discord.com/…/abc"
    assert "webhooks/1/abc" not in HOOK.masked
    assert OPS.masked == "-100999"


def test_a_channel_only_takes_messages_at_or_above_its_level():
    quiet = Channel("telegram", "-1", "oncall", Level.CRITICAL)
    assert not quiet.accepts(alert(level=Level.INFO))
    assert not quiet.accepts(alert(level=Level.WARNING))
    assert quiet.accepts(alert(level=Level.CRITICAL))


@pytest.mark.asyncio
async def test_level_routing_picks_the_channels(monkeypatch):
    """An on-call chat and a firehose share one bot without sharing traffic."""
    sent: list[str] = []

    async def record(self, notification):
        from till_infinity.notifications import Delivery

        sent.append(self.name)
        return Delivery(self.name, ok=True)

    monkeypatch.setattr(TelegramNotifier, "send", record)
    settings = Settings(
        telegram_token="t",
        telegram_chats=parse_channels("oncall=-1|critical, feed=-2", "telegram"),
    )

    await notify(alert(level=Level.INFO), settings=settings, targets=("telegram",))
    assert sent == ["telegram[feed]"]

    sent.clear()
    await notify(alert(level=Level.CRITICAL), settings=settings, targets=("telegram",))
    assert sent == ["telegram[oncall]", "telegram[feed]"]


# ------------------------------------------------------------------- discovery


UPDATES = {
    "ok": True,
    "result": [
        {"message": {"chat": {"id": -1001111, "title": "Quants Ops", "type": "supergroup"}}},
        {"channel_post": {"chat": {"id": -1002222, "title": "Alerts", "type": "channel"}}},
        {"message": {"chat": {"id": 4242, "first_name": "Sam", "type": "private"}}},
        {"message": {"chat": {"id": -1001111, "title": "Quants Ops (renamed)"}}},
    ],
}


def test_discovery_reads_chats_out_of_get_updates():
    from till_infinity.notifications import parse_chats

    chats = parse_chats(UPDATES)
    assert [c.address for c in chats] == ["-1001111", "-1002222", "4242"]
    # A later update wins, so a renamed chat shows its current name.
    assert chats[0].label == "Quants Ops (renamed)"
    assert chats[2].label == "Sam"


def test_discovery_rejects_an_error_body():
    from till_infinity.notifications import parse_chats

    with pytest.raises(PermanentError):
        parse_chats({"ok": False, "description": "Unauthorized"})


@pytest.mark.asyncio
async def test_discover_calls_get_updates():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=UPDATES)

    notifier = mock(TelegramNotifier(FULL, Channel("telegram", "")), handler)
    chats = await notifier.discover()
    assert seen["url"].endswith("/getUpdates")
    assert len(chats) == 3


@pytest.mark.asyncio
async def test_a_registered_webhook_makes_discovery_fail_permanently():
    """Telegram answers 409 while a webhook is set - the two modes are exclusive."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"description": "Conflict: can't use getUpdates"})

    notifier = mock(TelegramNotifier(FULL, Channel("telegram", "")), handler)
    with pytest.raises(PermanentError, match="409"):
        await notifier.discover()


def test_auto_chats_makes_telegram_ready_without_a_chat_list():
    settings = Settings(telegram_token="t", telegram_auto_chats=True)
    assert settings.telegram_ready
    assert Settings(telegram_token="t").telegram_ready is False


# ------------------------------------------------------- when it happened


def test_an_alert_read_an_hour_later_still_says_when_it_fired():
    """An alert read an hour later should say what it was about, and when."""
    note = Notification(title="btc level", at=1787059920.0)
    said = note.as_text()
    assert "2026-08-18" in said
    assert "13:32" in said
    assert "UTC" in said


def test_the_time_is_utc_and_says_so():
    """Every other time in this project is UTC - bars, touches, the journal.

    An alert rendering local time would be the one place they disagreed, read
    by somebody comparing it against a chart.
    """
    assert Notification(title="x", at=1787059920.0).when.endswith("UTC")


def test_the_clock_comes_after_the_instrument():
    """Context, not content: the reader wants the instrument before the clock."""
    note = Notification(
        title="btc level", body="down from below", fields={"probability": "89%"}, at=1787059920.0
    )
    lines = note.as_text().splitlines()
    assert lines[-1] == note.when
    assert "btc level" in lines[0]


def test_a_notification_stamps_itself():
    """A caller that says nothing still gets a timestamp."""
    import time as _time

    before = _time.time()
    note = Notification(title="x")
    assert before <= note.at <= _time.time()


@pytest.mark.asyncio
async def test_a_delivery_delayed_by_a_retry_is_not_stamped_with_the_retry():
    """The stamp is when it happened, not when it got through.

    A 429 with a long wait can put minutes between the event and the message,
    and an alert that dates itself to its own delivery is one a reader
    correlates against the wrong bars. So the assertion is made on the request
    that actually succeeded, after a failure, rather than on the object - where
    `at` is a plain field and nothing could move it.
    """
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(503) if len(bodies) == 1 else httpx.Response(204)

    notifier = mock(DiscordNotifier(FULL, HOOK), handler)
    result = await send_one(notifier, Notification(title="x", at=1787059920.0), FULL)
    assert result.ok
    assert len(bodies) == 2, "the first attempt was meant to fail"

    import json

    delivered = json.loads(bodies[1])["embeds"][0]
    assert delivered["timestamp"].startswith("2026-08-18T13:32")


def test_an_unstamped_alert_renders_no_time_rather_than_the_epoch():
    """A rendered `1970-01-01` is a reader working out whether the alert is
    stale or the stamp is missing."""
    note = Notification(title="x", at=0.0)
    assert note.when == ""
    assert note.as_text().splitlines() == [note.mark + " x"]


def test_discord_is_given_the_instant_rather_than_our_rendering_of_it():
    """Discord renders the time itself, in the reader's own timezone.

    So the embed carries ISO-8601 rather than the string `as_text` builds for
    Telegram - the same instant, in the form each destination can use.
    """
    payload = DiscordNotifier(FULL, HOOK).payload(Notification(title="x", at=1787059920.0))
    stamp = payload["embeds"][0]["timestamp"]
    assert stamp.startswith("2026-08-18T13:32")


@pytest.mark.asyncio
async def test_a_channel_that_cannot_open_does_not_suppress_the_others(monkeypatch):
    """**Measured: the first channel's session failure cost every later one.**

    `notify` opened all the channels in one `AsyncExitStack`, and a stack
    enters its contexts in sequence - so a notifier that raised on
    `__aenter__` meant nothing after it was even attempted. The order is
    `DEFAULT_TARGETS`, telegram first, which makes the suppressed one Discord;
    reverse the fault and it suppressed Telegram. Each channel opens its own
    session now.

    This is the worst day: the broker is down, the terminal is unreachable,
    and one of the two transports is sick as well. The other one has to carry
    the message.
    """

    async def refuse(self):
        raise RuntimeError("no socket")

    async def ok_send(self):
        from till_infinity.notifications import Delivery

        return Delivery(self.name, ok=True)

    monkeypatch.setattr(TelegramNotifier, "__aenter__", refuse)
    monkeypatch.setattr(DiscordNotifier, "send", lambda self, note: ok_send(self))

    results = {d.target: d for d in await notify(alert(), settings=FULL)}
    assert results["discord[alerts]"].ok, "a Telegram session failure took Discord with it"
    assert not results["telegram[ops]"].ok
    assert "no socket" in results["telegram[ops]"].detail
