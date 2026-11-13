"""The read-only HTTP face of the desk's record.

GET only, every route reading local files.

**No route to a broker.** Importing this module pulls 92 `till_infinity`
modules and **none of them is under `adapters/` or `node/`** - measured, not
assumed, and pinned by `tests/test_web_api.py`. `strategies/__init__`
re-exports the desks, so the `Strategy` classes are in memory; nothing here
constructs one, and an order needs a node with an execution client registered,
which is `node/live`'s job and `node/live._arm`'s to halt. The service is
separate from the node for that reason rather than for deployment's.

**Bound to loopback unless somebody says otherwise.** The run command names
`--host 127.0.0.1`, and reaching it from another machine is a deliberate act:

    uv run --extra dashboard uvicorn web.api.main:app --host 127.0.0.1 --port 8787

**The bind is not the check, though.** `guard` reads the peer address off
every request, so a service that ends up reachable - started programmatically,
under gunicorn, from a container entrypoint - still refuses a non-local
connection. Without `TILL_WEB_TOKEN` only local connections are served; with
it, every request must carry `Authorization: Bearer <token>` wherever it came
from.

**And a loopback bind is not a boundary on its own.** A name that resolves to
127.0.0.1 reaches a loopback socket from whatever page the operator's browser
has open, so `TrustedHostMiddleware` checks the `Host` header too, always.

**`TILL_WEB_TOKEN` authenticates one hop and nothing else.** It says the proxy
in front may call this service; it says nothing about who called the proxy.
That is the proxy's own question, answered with its own secret in
`web/lib/gate.ts` - a proxy that attaches a credential on behalf of an
unauthenticated caller is a confused deputy, and this pair used to be one.

Reads are cached against the journal file's modification time. Entries are
append-only and there is no update path, so a file that has not been written to
cannot have a different answer in it; a dashboard left open re-reads a hundred
thousand entries only when the desk has actually written something.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
import sys
import time
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from . import book as book_module
from . import data

DAY = 86400.0

#: Peer addresses that mean "this machine".
#:
#: **Not `""` and not `"localhost"`.** A peer address is never a hostname, and
#: an empty one means the connection has no address at all - a Unix socket, or
#: a transport that did not report one. Both were in this set and both made
#: `_local` return True, so a UDS deployment with no token would have served
#: everything to anyone who could reach the socket. `::ffff:127.0.0.1` is here
#: because that is how a local connection arrives on a dual-stack listener.
LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

#: The shared secret, if the operator set one. Compared with `hmac.compare_digest`
#: so a wrong token takes the same time to reject as a right one.
TOKEN = os.environ.get("TILL_WEB_TOKEN", "").strip()


def _bound() -> None:
    """Warn at start-up where the command line shows an off-loopback bind.

    **Advisory only, and it used to be the whole defence.** It reads
    `sys.argv` because uvicorn owns the socket and this module never sees it -
    which means it is blind to every launch that is not that command line:
    uvicorn called programmatically, gunicorn, a container whose entrypoint
    differs, a unix socket. A check that fails open on four ordinary ways of
    starting a server is not a check, so the real one is per-connection in
    `guard` below and this stays as an early, louder version of it.
    """
    if TOKEN:
        return
    argv = sys.argv
    hosts = [argv[index + 1] for index, word in enumerate(argv[:-1]) if word == "--host"]
    named = os.environ.get("TILL_WEB_HOST", "").strip()
    if named:
        hosts.append(named)
    if [host for host in hosts if host not in LOOPBACK]:
        raise RuntimeError(
            "This service shows a live account's activity. Binding it off loopback "
            "needs TILL_WEB_TOKEN set to a shared secret; without one it serves "
            "127.0.0.1 only."
        )


def _local(request: Request) -> bool:
    """Is this connection from this machine? Asked of the socket, not of a header.

    `request.client.host` is the peer address the server accepted, which no
    header can forge - unlike `Host`, which is whatever the caller typed, and
    unlike `X-Forwarded-For`, which is deliberately not consulted here. A
    reverse proxy in front of this would make every request look local, which
    is exactly why putting one there has to be a deliberate act that brings a
    token with it.
    """
    peer = (request.client.host if request.client else "") or ""
    if not peer:
        # No peer address: a Unix socket, or a transport that did not report
        # one. Refused rather than assumed local, so such a deployment has to
        # set a token deliberately.
        return False
    return peer in LOOPBACK or peer.startswith("127.")


def guard(request: Request) -> None:
    """Every route depends on this.

    With a token, the token decides. Without one, **the connection must be
    local** - checked here per request rather than inferred from `sys.argv` at
    start-up, because the argv check cannot see a programmatic uvicorn, a
    gunicorn worker or a container entrypoint, and fails open on all three.
    """
    if not TOKEN:
        if not _local(request):
            raise HTTPException(
                status_code=403,
                detail=(
                    "This service shows a live account's activity and answers "
                    "non-local connections only when TILL_WEB_TOKEN is set."
                ),
            )
        return
    header = request.headers.get("authorization", "")
    offered = header[7:] if header.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(offered, TOKEN):
        raise HTTPException(status_code=401, detail="bad or missing bearer token")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Check the bind, then warm the bar-store listing off the request path.

    Grouping `.data/prices/prices.db` by feed, interval and venue is a full
    scan of a 300MB table and takes about six seconds on a cold cache. It is a
    file a retired collector wrote, so the answer does not change; doing it at
    start-up means the first person to open the feed picker does not wait.
    """
    _bound()
    warm = asyncio.create_task(asyncio.to_thread(data.series))
    try:
        yield
    finally:
        warm.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await warm


app = FastAPI(
    title="till_infinity desk",
    summary="Read-only views of the journal, the report and the bar catalogues.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
    dependencies=[Depends(guard)],
)

#: Host headers this service answers to, **always enforced**. A loopback bind
#: is not a boundary on its own: a name that resolves to 127.0.0.1 reaches a
#: loopback socket from whatever page the operator's browser has open, and
#: this one renders a live account's positions. Starlette strips the port
#: before matching, so a host is named without one.
#:
#: Named `TILL_API_HOSTS` and not `TILL_WEB_HOSTS`: the proxy in front has its
#: own allowlist, they are different tiers, and one variable for both reads as
#: one boundary when there are two.
HOSTS = [h.strip() for h in os.environ.get("TILL_API_HOSTS", "").split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=HOSTS or ["127.0.0.1", "localhost", "::1"])

#: Where the browser talks to this service from. Only needed when it does so
#: directly: `web/app/api/[...path]/route.ts` proxies through Next by default,
#: and then the only origin in play is the app's own.
ORIGINS = [o.strip() for o in os.environ.get("TILL_WEB_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS or ["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _stamp() -> float:
    """The journal's modification time, or 0 when there is no journal."""
    path = data.journal_path()
    return path.stat().st_mtime if path.exists() else 0.0


@lru_cache(maxsize=32)
def _overview(
    stamp: float,
    mode: str,
    strategy: str,
    feed: str,
    since: float | None,
    until: float | None,
    days: int | None,
) -> data.Overview:
    del stamp
    return data.overview(
        mode=mode, strategy=strategy, feed=feed, since=since, until=until, days=days
    )


@lru_cache(maxsize=4)
def _levels(stamp: float) -> data.Levels:
    del stamp
    return data.levels()


def _window(days: int | None, since: float | None) -> float | None:
    """`days` is shorthand for "since this many days before now"."""
    if days and since is None:
        return time.time() - days * DAY
    return since


@app.get("/api/health", response_model=data.Health)
def health() -> data.Health:
    """Which sources this machine has, and what the journal actually holds."""
    return data.health()


@app.get("/api/overview", response_model=data.Overview)
def overview(
    mode: Annotated[str, Query(description="paper or live; both together when empty")] = "",
    strategy: str = "",
    feed: str = "",
    days: Annotated[int | None, Query(ge=1, le=3650)] = None,
    since: float | None = None,
    until: float | None = None,
) -> data.Overview:
    """Header figures, equity curve, breakdowns, gate refusals and trades."""
    return _overview(_stamp(), mode, strategy, feed, _window(days, since), until, days)


@app.get("/api/activity", response_model=data.Activity)
def activity(hours: Annotated[float, Query(gt=0, le=8760)] = 6.0) -> data.Activity:
    """What each strategy has taken and been refused lately, and how stale that is.

    Not cached: this is the endpoint whose whole job is to be current, and it
    reads one indexed time range out of a local sqlite file.
    """
    return data.activity(hours=hours)


@app.get("/api/book", response_model=book_module.Book)
def book() -> book_module.Book:
    """Open positions from the snapshot, reconciled against the journal.

    Not cached. The whole value of this endpoint is its age, and a cache keyed
    on the journal would hold a stale book across a snapshot the writer had
    already replaced.
    """
    return book_module.book()


@app.get("/api/levels", response_model=data.Levels)
def levels() -> data.Levels:
    """What each level made or lost, from `journal.ledger`."""
    return _levels(_stamp())


@app.get("/api/series", response_model=list[data.SeriesView])
def series() -> list[data.SeriesView]:
    """Every chartable feed and interval, with the source and venue named."""
    return data.series()


@app.get("/api/chart", response_model=data.Chart)
def chart(
    feed: str,
    interval: str = "15m",
    source: str = "",
    venue: str = "",
    mode: str = "",
    strategy: str = "",
    days: Annotated[int | None, Query(ge=1, le=3650)] = None,
    since: float | None = None,
    until: float | None = None,
) -> data.Chart:
    """Candles for one feed, with the trades and the refusals taken on it.

    The trade filters are the ones the rest of the page is using, so the
    markers are the trades the tables are showing rather than a different set.
    The feed filter is deliberately not applied: the chart's own feed decides
    which markers are drawn.
    """
    found = _overview(_stamp(), mode, strategy, "", _window(days, since), until, days)
    return data.chart(feed, interval, source=source, venue=venue, shown=found.trades)
