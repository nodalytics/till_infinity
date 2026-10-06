"""Pictures on notifications: Discord multipart, Telegram sendPhoto, and the fallbacks.

Backward compatible by construction - a notification without an image sends
exactly the request it always did - and an image that will not send is retried
once as text, because an alert must never be lost for its picture.
"""

from __future__ import annotations

import base64
import json

import httpx

from till_infinity.notifications import (
    Channel,
    DiscordNotifier,
    Notification,
    Settings,
    TelegramNotifier,
    from_message,
)
from till_infinity.notifications.telegram import CAPTION_LIMIT, split_caption

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 200
OPS = Channel("telegram", "-100999", "ops")
HOOK = Channel("discord", "https://discord.com/api/webhooks/1/abc", "alerts")
FULL = Settings(telegram_token="123:AA", telegram_chats=(OPS,), discord_webhooks=(HOOK,))


def mock(notifier, handler):
    notifier._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return notifier


def card(**kw) -> Notification:
    return Notification(
        title=kw.pop("title", "ARB 1d · DISPLACE_C at a 12-bar low · long"),
        body=kw.pop("body", "A violent bullish candle closed at a 12-bar low."),
        fields=kw.pop("fields", {"Entry ref": "0.41", "Stop": "0.38"}),
        **kw,
    )


def _form(request: httpx.Request) -> tuple[str, bytes]:
    return request.headers["content-type"], request.content


async def test_discord_sends_the_picture_inside_its_embed():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    n = mock(DiscordNotifier(FULL, HOOK), handler)
    delivery = await n.send(card(image=PNG, image_name="arb.png"))
    assert delivery.ok
    assert len(seen) == 1
    kind, body = _form(seen[0])
    assert kind.startswith("multipart/form-data")
    assert b'name="files[0]"; filename="arb.png"' in body
    assert PNG in body
    start = body.index(b"{")
    payload = json.loads(body[start : body.index(b"\r\n", start)])
    assert payload["embeds"][0]["image"] == {"url": "attachment://arb.png"}


async def test_discord_falls_back_to_text_when_the_picture_fails():
    seen = []

    def handler(request):
        seen.append(request)
        if request.headers["content-type"].startswith("multipart"):
            return httpx.Response(400, json={"message": "Invalid Form Body"})
        return httpx.Response(204)

    n = mock(DiscordNotifier(FULL, HOOK), handler)
    assert (await n.send(card(image=PNG, image_name="arb.png"))).ok
    assert len(seen) == 2
    text = json.loads(seen[1].content)
    assert "image" not in text["embeds"][0]


async def test_discord_without_a_picture_is_unchanged():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    n = mock(DiscordNotifier(FULL, HOOK), handler)
    note = card()
    assert (await n.send(note)).ok
    assert json.loads(seen[0].content) == n.payload(note)


async def test_telegram_sends_a_photo_with_the_text_as_its_caption():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    n = mock(TelegramNotifier(FULL, OPS), handler)
    assert (await n.send(card(image=PNG, image_name="arb.png"))).ok
    assert len(seen) == 1
    assert seen[0].url.path.endswith("/sendPhoto")
    _, body = _form(seen[0])
    assert b'name="photo"; filename="arb.png"' in body
    assert b"<b>ARB 1d" in body
    assert b'name="parse_mode"\r\n\r\nHTML' in body


async def test_a_long_caption_overflows_into_a_follow_up_message():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    fields = {f"line {i}": "x" * 60 for i in range(30)}
    n = mock(TelegramNotifier(FULL, OPS), handler)
    assert (await n.send(card(image=PNG, fields=fields))).ok
    assert [r.url.path.rsplit("/", 1)[1] for r in seen] == ["sendPhoto", "sendMessage"]
    rest = json.loads(seen[1].content)["text"]
    assert rest.startswith("line ")


async def test_telegram_falls_back_to_text_when_the_photo_fails():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/sendPhoto"):
            return httpx.Response(200, json={"ok": False, "description": "IMAGE_PROCESS_FAILED"})
        return httpx.Response(200, json={"ok": True})

    n = mock(TelegramNotifier(FULL, OPS), handler)
    assert (await n.send(card(image=PNG))).ok
    assert [r.url.path.rsplit("/", 1)[1] for r in seen] == ["sendPhoto", "sendMessage"]
    assert "ARB 1d" in json.loads(seen[1].content)["text"]


async def test_telegram_without_a_picture_is_unchanged():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    n = mock(TelegramNotifier(FULL, OPS), handler)
    note = card()
    assert (await n.send(note)).ok
    assert seen[0].url.path.endswith("/sendMessage")
    assert json.loads(seen[0].content) == n.payload(note)


def test_a_caption_is_cut_between_lines_and_never_inside_markup():
    text = "<b>title</b>\n" + "\n".join(f"a &amp; b {i:03d} " + "y" * 40 for i in range(40))
    caption, rest = split_caption(text)
    assert len(caption) <= CAPTION_LIMIT
    assert caption.startswith("<b>title</b>")
    assert caption + "\n" + rest == text
    short, none = split_caption("<b>t</b>\nshort")
    assert none == ""
    assert short == "<b>t</b>\nshort"


def test_an_alert_payload_carries_its_picture_through_the_bus():
    payload = {
        "title": "t",
        "image": {"name": "../../etc/passwd.png", "data": base64.b64encode(PNG).decode()},
    }
    note = from_message(payload)
    assert note.image == PNG
    assert note.image_name == "etc-passwd.png"
    assert note.to_dict()["image"] == {"name": "etc-passwd.png", "bytes": len(PNG)}


def test_anything_that_is_not_a_picture_is_dropped_and_the_alert_kept():
    for data in ("not base64!", base64.b64encode(b"GIF89a....").decode()):
        note = from_message({"title": "t", "image": {"name": "x.png", "data": data}})
        assert note is not None
        assert note.image is None
