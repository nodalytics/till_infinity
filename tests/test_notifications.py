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


def test_level_parsing():
    assert Level.parse("warning") is Level.WARNING
    assert Level.parse("CRITICAL") is Level.CRITICAL
    assert Level.parse(None) is Level.INFO
    assert Level.parse(2) is Level.CRITICAL
    with pytest.raises(ValueError, match="unknown level"):
        Level.parse("shouty")


def test_text_rendering_escapes_html():
    """A symbol like EUR<USD or an & in a headline must not break the parse."""
    text = alert(title="EUR<USD & gold", body="a > b").as_text(escape=True)
    assert "EUR&lt;USD &amp; gold" in text
    assert "a &gt; b" in text
    assert "<b>" in text  # our own markup survives


def test_text_rendering_includes_fields_and_url():
    text = alert(fields={"spread_bps": "4.2"}, url="https://example.com").as_text()
    assert "spread_bps: 4.2" in text
    assert "https://example.com" in text


def test_text_rendering_omits_the_fields_the_filter_routes_on():
    """`instrument: gold` under a headline containing "gold" is noise."""
    text = alert(fields={"instrument": "gold", "shape": "level"}).as_text()
    assert "instrument: gold" not in text
    assert "shape: level" not in text


def test_truncate_marks_the_cut():
    assert truncate("abc", 10) == "abc"
    cut = truncate("x" * 100, 20)
    assert len(cut) == 20
    assert cut.endswith("[…]")
    assert truncate("abc", 0) == "abc"  # no limit means no cut


# --------------------------------------------------------------------- payload


def test_telegram_payload_is_escaped_html_within_the_limit():
    notifier = TelegramNotifier(FULL, OPS)
    payload = notifier.payload(alert(body="y" * 9000))
    assert payload["chat_id"] == "-100999"
    assert payload["parse_mode"] == "HTML"
    assert len(payload["text"]) <= TELEGRAM_TEXT_LIMIT


def test_the_telegram_token_lives_in_the_url_not_the_payload():
    notifier = TelegramNotifier(FULL, OPS)
    assert "123:AA-secret" in notifier.api("sendMessage")
    assert "secret" not in str(notifier.payload(alert()))


def test_discord_payload_is_an_embed_coloured_by_level():
    notifier = DiscordNotifier(FULL, HOOK)
    payload = notifier.payload(alert(level=Level.CRITICAL, fields={"instrument": "gold"}))
    (embed,) = payload["embeds"]
    assert embed["color"] == 0xD9534F
    assert embed["fields"][0] == {"name": "instrument", "value": "gold", "inline": True}


def test_discord_embed_respects_the_description_limit():
    notifier = DiscordNotifier(FULL, HOOK)
    (embed,) = notifier.payload(alert(body="z" * 9000))["embeds"]
    assert len(embed["description"]) <= DISCORD_DESCRIPTION_LIMIT


def test_discord_caps_the_field_count():
    notifier = DiscordNotifier(FULL, HOOK)
    many = {f"k{i}": str(i) for i in range(40)}
    (embed,) = notifier.payload(alert(fields=many))["embeds"]
    assert len(embed["fields"]) == 25


# -------------------------------------------------------------------- sending


@pytest.mark.asyncio
async def test_telegram_send_posts_to_send_message():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    notifier = mock(TelegramNotifier(FULL, OPS), handler)
    result = await notifier.send(alert())
    assert result.ok
    assert seen["url"].endswith("/bot123:AA-secret/sendMessage")


@pytest.mark.asyncio
async def test_telegram_ok_false_is_a_failure_despite_http_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "chat not found"})

    result = await mock(TelegramNotifier(FULL, OPS), handler).send(alert())
    assert not result.ok
    assert "chat not found" in result.detail


@pytest.mark.asyncio
async def test_discord_accepts_the_empty_204():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    assert (await mock(DiscordNotifier(FULL, HOOK), handler).send(alert())).ok


@pytest.mark.asyncio
async def test_a_bad_token_is_permanent():
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
async def test_telegram_rate_limit_is_read_from_parameters():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"parameters": {"retry_after": 3}})

    with pytest.raises(TransientError) as caught:
        await mock(TelegramNotifier(FULL, OPS), handler).send(alert())
    assert caught.value.retry_after == 3.0


@pytest.mark.asyncio
async def test_retry_after_is_capped():
    settings = Settings(discord_webhooks=(HOOK,), max_retry_after=30.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "9000"})

    with pytest.raises(TransientError) as caught:
        await mock(DiscordNotifier(settings, HOOK), handler).send(alert())
    assert caught.value.retry_after == 30.0


@pytest.mark.asyncio
async def test_a_5xx_is_retried_then_reported():
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


def test_only_configured_channels_are_built():
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


def test_unknown_target_is_rejected():
    with pytest.raises(ValueError, match="unknown target"):
        build_notifiers(("carrier-pigeon",), FULL)


def test_configured_lists_what_is_ready():
    assert Settings().configured() == ()
    assert FULL.configured() == ("telegram", "discord")
    assert Settings(telegram_token="t").configured() == ()  # no chats


@pytest.mark.asyncio
async def test_notify_returns_nothing_when_no_target_is_set():
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


def test_channel_parsing_handles_labels_levels_and_urls():
    (ops, feed) = parse_channels("ops=-1001111|warning, -1002222", "telegram")
    assert (ops.label, ops.address, ops.min_level) == ("ops", "-1001111", Level.WARNING)
    # Unlabelled entries are numbered so a log line can still identify them.
    assert (feed.label, feed.address, feed.min_level) == ("2", "-1002222", Level.INFO)


def test_a_url_is_never_mistaken_for_a_label():
    """`https://…` contains an '=' only in query strings, but always a ':' and
    '/' before it — so the label pattern must not match a URL."""
    (hook,) = parse_channels("https://discord.com/api/webhooks/1/abc?x=1", "discord")
    assert hook.address == "https://discord.com/api/webhooks/1/abc?x=1"
    assert hook.label == "1"


def test_channel_parsing_ignores_blanks():
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
    """Telegram answers 409 while a webhook is set — the two modes are exclusive."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"description": "Conflict: can't use getUpdates"})

    notifier = mock(TelegramNotifier(FULL, Channel("telegram", "")), handler)
    with pytest.raises(PermanentError, match="409"):
        await notifier.discover()


def test_auto_chats_makes_telegram_ready_without_a_chat_list():
    settings = Settings(telegram_token="t", telegram_auto_chats=True)
    assert settings.telegram_ready
    assert Settings(telegram_token="t").telegram_ready is False
