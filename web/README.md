# The desk dashboard

A read-only view of what the desk traded, what it refused, and what that came
to. Two halves:

- **`web/api/`** — a thin FastAPI service that calls `till_infinity`'s own
  functions and returns JSON.
- **everything else** — a Next.js app (App Router, TypeScript) that renders it,
  with candles drawn by `lightweight-charts`.

## Why two halves

The standing rule here is that *the thing that measured it and the thing that
trades it are the same thing*, and nearly every expensive mistake on this desk
has been two implementations drifting apart. So nothing is reimplemented in
TypeScript.

`report.trades()` is the example that earns the rule. It pairs each journal
outcome to the decision it judges, and falls back to the decision's
`risk_money` when the outcome zeroes it — a position adopted across a restart
comes back with no sizing to state, and without that fallback **839 of 1,486
closed trades in the live journal were invisible to every report**. A second
pairing in TypeScript would reintroduce exactly that class of bug. The API
calls the real function; the browser renders the answer.

Two places in `web/api/data.py` look like duplication and are not, both
marked in the source: `groups` repeats the three lines `report.build` uses to
bucket trades, because `build` takes no time window and the dashboard's whole
point is a selectable one; and `declines` counts the same `context["gate"]`
key when a window is asked for. Both use the production classes, and
`tests/test_web_api.py` pins them against `report.build` and `report.declines`
at the full window.

## Running it

One command, from the repository root.

```sh
bash web/dev.sh      # or: npm run dev, from web/
```

It starts both halves, prints the two addresses and the journal it is about to
read, and takes both down together on `^C`.

**Both halves, because one of them is useless.** The page is a shell: every
figure on it is a browser read through the Next proxy to the Python service.
Start `next dev` alone and the app loads, the chrome is right, and every panel
is a 502 — which is a report this repository has had, from somebody who ran
the documented command. `web/dev.sh` is `entrypoint.sh`'s local twin and works
the same way: `wait -n` returns on whichever half exits first and the trap
takes the other down with it, so there is no state in which half of this is
running.

```sh
npm run dev:api      # the service alone, from web/ (it cd's to the root)
npm run dev:web      # the app alone
```

Those are the escape hatches, for a debugger or a profiler on one half.

**Which journal it reads is printed, every time.** `TILL_JOURNAL_DB` is left
alone if you set it; unset, the script defaults to this repository's own
`.data/journal/journal.db` and says so, with the file's modification date.
A dashboard rendering a file from three months ago looks exactly like a
dashboard rendering the desk, and the only difference on screen is a date
nobody reads unless it is put in front of them.

The defaults are closed: loopback only, no secrets to set, nothing reachable
from anywhere else. To reach it from another machine, see **Security** below —
it needs a caller secret, and the dashboard refuses to serve a widened host
list without one.

`npm run build` does not need the API running: the page is a shell and every
read happens in the browser. `npm start` does, for the same reason every
panel does.

There is no console script and no process manager. One script and `wait -n` is
the whole deployment, which is the right size for one operator and one
dashboard.

## Security

This renders a live account's positions and P&L, so the defaults are closed.
**Out of the box the dashboard is loopback-only**, and the two secrets below do
different jobs — conflating them is the mistake this section exists to prevent.

### Two credentials, two purposes

| | what it is | who holds it |
| --- | --- | --- |
| `TILL_DASHBOARD_SECRET` | what a **caller** must present to the Next proxy | the person at the browser |
| `TILL_WEB_TOKEN` / `TILL_API_TOKEN` | what the **proxy** presents to the API, one hop | the two server processes |

`TILL_API_TOKEN` is **not** what makes remote access safe. It proves the proxy
may call the API and says nothing about who called the proxy. An earlier
version attached it to every request that arrived and skipped the host check
whenever it was configured, so setting it handed the API's full authority to
anyone who could reach Next — a confused deputy, where configuring a credential
widened access. The caller is now authenticated first, with its own secret,
and only then is the API token used.

### What is enforced

- **Both halves bind to loopback.** The API's run command names
  `--host 127.0.0.1`; `package.json` passes `-H 127.0.0.1` to `next dev` and
  `next start`.
- **The API decides locality from the connection, not from `argv`.** `guard()`
  checks `request.client.host` per request. The previous version scanned
  `sys.argv` for `--host`, which is a guess about how uvicorn was started and
  fails open under a programmatic launch, gunicorn, a container entrypoint or
  a Unix socket. A request with no peer address at all is refused rather than
  assumed local, so a UDS deployment has to set a token deliberately.
- **Host allowlists are always enforced, on both tiers, whatever else is set.**
  A hostname that resolves to 127.0.0.1 reaches a loopback socket from whatever
  page the operator's browser has open. The API runs `TrustedHostMiddleware`
  over `TILL_API_HOSTS`; the proxy checks `TILL_WEB_HOSTS`. Both default to
  loopback and neither is skipped as a side effect of another setting.
- **Widening the allowlist without a caller secret fails closed.** If
  `TILL_WEB_HOSTS` names anything off this machine and `TILL_DASHBOARD_SECRET`
  is unset, every proxied request is a 503 that says so. There is no
  configuration in which the proxy lends its API token to an unauthenticated
  caller.
- **Signing in.** With `TILL_DASHBOARD_SECRET` set, the page shows a sign-in;
  `POST /session` compares the secret with `crypto.timingSafeEqual` over
  SHA-256 digests (equal lengths, so the comparison cannot leak one) and sets
  an `httpOnly`, `SameSite=Strict` cookie, `Secure` over https. `DELETE
  /session` signs out. A client bearer works too, for `curl`.
- **The browser only ever talks to Next.** `app/api/[...path]/route.ts`
  exports `GET` and nothing else, so a POST to `/api/anything` is a 405 before
  it leaves the Node process: the read-only promise is in the route table, not
  in a comment.
- **No credential is in the dashboard's half.** The one process that talks to
  a terminal is `web/api/snapshot.py`, started by hand on the host that
  already has the key.
- **No account identifiers are served.** The snapshot writer reads the login,
  the server and the broker name and writes none of them. Balance, equity,
  margin and currency are written, because the exposure panel is arithmetic on
  them.

### What this is not

One shared secret is not a user system. There are no accounts, no rotation, no
lockout and no rate limiting; a stolen cookie is a stolen secret until it
expires after a day. That is the limit of a shared secret and it is written
down rather than implied. Anything beyond one operator wants a real identity
provider in front of this, not a longer string.

**The `Host` allowlist is not a locality check.** `Host` is whatever the caller
typed, so a request from anywhere carrying `Host: 127.0.0.1` satisfies it. It
is a DNS-rebinding defence and nothing more. What decides whether a caller
secret is required is configuration the operator sets and the caller cannot:
`TILL_WEB_HOSTS`, and `TILL_WEB_BIND`, which `npm run dev`, `npm start` and the
image all set to the address they bind. **Start the server off loopback by some
other route without setting `TILL_WEB_BIND` and nothing here will notice** -
that is the one gap left, and the fix is to set it.

The API behind the proxy does not share this limitation: it reads the peer
address off the socket, which no header can forge.

- **Nothing in `web/` imports a module that can place an order.** Importing
  `web.api.main` pulls 92 `till_infinity` modules and none is under
  `adapters/` or `node/`. `tests/test_web_api.py` asserts that in a
  subprocess, so it fails before anybody deploys a dashboard that can trade.

## Environment

Every setting is read from the environment. Nothing is read from `.secrets/`.

| Variable | Default | What it does |
| --- | --- | --- |
| `TILL_JOURNAL_DB` | `journal.store.DEFAULT_DB` (`.data/journal/journal.db`) | The journal to score. Relative paths resolve against the repository root. |
| `TILL_PRICES_DB` | `.data/prices/prices.db` | The sqlite bar store. |
| `CORPUS_DIR` | `~/till-data/catalog` | The 15-minute parquet catalogue. Same variable `node/backtest.catalogue()` reads. |
| `TILL_MT5_CATALOG` | `~/till-data/mt5` | The 5-minute parquet catalogue. |
| `TILL_BOOK_SNAPSHOT` | `.data/live/book.json` | Where `snapshot.py` writes and the API reads. |
| `TILL_MEASURED_JSON` | *(unset)* | Research figures for the live-against-measured panel. |
| `TILL_DASHBOARD_SECRET` | *(unset)* | What a **caller** must present to the proxy. Unset means loopback-only. |
| `TILL_WEB_BIND` | set by the scripts and the image | The address the server bound to. Off loopback makes a caller secret mandatory. |
| `TILL_WEB_HOSTS` | `127.0.0.1,localhost,::1,[::1]` | Host headers the **proxy** answers to. |
| `TILL_API_HOSTS` | `127.0.0.1,localhost,::1` | Host headers the **API** answers to. |
| `TILL_WEB_TOKEN` | *(unset)* | The proxy-to-API hop, as the API reads it. |
| `TILL_API_TOKEN` | *(unset)* | The same hop, as the proxy reads it. Never a caller credential. |
| `TILL_WEB_ORIGINS` | `http://localhost:3000` | CORS origins, only used if a browser talks to the API directly. |
| `TILL_API_URL` | `http://127.0.0.1:8787` | Where the Next proxy forwards. |
| `TRADING_MT5_URL`, `TRADING_MT5_API_KEY`, `TRADING_MT5_API_PATH` | — | Read by `snapshot.py` only, on the desk's host. |

## The broker snapshot

Open positions have to come from the broker — *judge the desk on the broker,
not the journal* — but the dashboard must not hold a credential. So the job is
split:

```sh
# on the host that runs the desk, where the credential already is
uv run python -m web.api.snapshot --every 30
```

It reads two GET routes (`/terminal/account/info` and `/positions/`), writes an
atomic JSON file, and nothing else. A failed read leaves the previous file
alone rather than writing an empty book, because an empty book over a real one
reads as *everything closed*, which is the one wrong answer that panel must
never give. The API reads the file and shows its age; past five minutes the UI
calls it stale rather than rendering it as the book now. With no file at all
the panel is empty and says why — it never falls back to journal positions and
presents them as broker truth.

A `WS /stream` exists on the bridge and is deliberately not used: a polled file
keeps the credential boundary to one process, which is worth more here than
sub-second positions.

## What each panel reads

| Panel | Source |
| --- | --- |
| Alarm strip (above the chart) | `book.py` — unprotected positions, broker-vs-engine disagreements, snapshot age, journal age, any binding cap |
| Chart | `ParquetDataCatalog` over `~/till-data/mt5` and `~/till-data/catalog`, or the `bars` table in `.data/prices/prices.db` |
| Chart markers | `report.trades()`, with entry and exit prices attached from the journal entries by decision time |
| Chart refusal squares | `journal.read(actor="trading", kind="observation")`, the only record of a trade that was never placed |
| Chart level lines | `context["level"]` on the trades and refusals for that feed |
| Watchlist | `report.build().by_feed`, plus every feed the catalogues hold |
| Activity | `journal.read(..., since=)` over decisions, outcomes and gate observations |
| Performance | `report.build()` — overall, per rule, per exit reason, per `exit_source`; equity from `Trade.r` in close order |
| Trades | `report.trades()` |
| Refusals | `report.declines()` |
| Positions | the broker snapshot, reconciled against journal decisions with no outcome; caps from `Settings.from_env()` |
| Levels | `journal.ledger.outcomes/ledger/totals` |

**If a source is missing, the panel says so and shows nothing.** A fabricated
trading figure is worse than a blank panel, and a blank panel that names the
file it could not read is better than both.

## The chart

`lightweight-charts` 5.x, the Apache-2.0 library, not the hosted widget — the
data is local and never leaves the machine.

- **Overlays**: trade entries and exits, gate refusals, and the levels the desk
  traded or was refused at. Everything derived is labelled: a desk level is a
  dotted line titled `desk`, a line you placed is solid and titled `drawn`.
- **Indicators**, computed in the browser from the candles already loaded:
  means over 20 and 50 bars, a 20-bar mean with a 2× ATR cushion, and realised
  volatility in bps a bar on its own scale. All three are bar-count measures,
  so the same number means different things at 5m and 4h.
- **Crosshair readout** — OHLC, the bar's time in UTC, and whatever the desk
  did on that candle, named in full. Markers carry no text of their own:
  twenty-four of them in one pane overlap into a smear.
- **Measure**: shift-drag for price delta, percent and bar count.
- **Drawing**: one tool, a horizontal line, persisted per feed in
  `localStorage` with every read and write wrapped. Two tools that work beat
  six that glitch, and the library has no drawing layer to build the others on.

## Themes

Light and dark, both designed rather than inverted. The colours are measured
from the charting site's own custom properties — `#089981` up, `#f23645` down,
`#2962ff` accent, identical in both themes — with the chart product's
`#131722 / #1e222d / #2a2e39 / #d1d4dc` family for dark and
`#ebebeb / #ffffff / #f9f9f9 / #e0e3eb` for light, and the library's own
defaults for the grid, scale border and crosshair.

The candle green is **not** used for text: `#089981` is 3.2:1 on white and
`#f23645` is 3.9:1, both under the 4.5:1 a figure in a table needs, so each
theme carries a separate `--up-ink` / `--down-ink` at 5.3:1 and 5.0:1 on
white. The candles keep the measured values, which is where they belong.

The choice is stored in `localStorage` and applied by a small script in
`<head>` before first paint, so there is no flash of the wrong theme. Every
storage call is wrapped: in a private window the accessor throws, and the page
has to render anyway. With no stored choice the page follows
`prefers-color-scheme` and keeps following it while the viewer has not chosen.
The charts re-read the tokens on a theme change rather than keeping the
library's defaults.

## Layout

Chart-dominant, framed by chrome: a 38px toolbar, a thin left rail of layer
toggles, a watchlist on the right and a tabbed panel below, both draggable and
both collapsible from the rail. Hairline borders, no elevation, radius only on
buttons and inputs, tabular figures everywhere. Readable from about 820px
wide, below which the rail and the watchlist fold away.

## Tests and lint

`tests/test_web_api.py` runs in the repository's own suite. It writes its own
journal with the production `Journal` writer, so it needs no live data, no
server, no network and no catalogue.

```sh
uv run pytest -q tests/test_web_api.py
uv run ruff check                 # no path argument
uv run ruff format --check        # no path argument, and not implied by the above
npm run typecheck                 # from web/
```

`pyproject.toml` gains one optional group, `dashboard`
(`fastapi`, `uvicorn`), and `pythonpath = ["."]` under pytest so the suite can
import `web.api` — `web/` is a folder, not a distribution.
