# Logging

`till_infinity.utils.logging` owns configuration. Modules never configure
anything - they ask for a logger and use it:

```python
from till_infinity.utils.logging import get_logger

log = get_logger(__name__)
log.debug("resolved %s", symbol)
log.warning("skipping %s: %s", symbol, reason)
```

Twenty-one modules do that. An entry point is meant to configure once:

```python
from till_infinity.utils.logging import setup_logging

setup_logging(verbose=True, log_file="logs/till.log")
```

**Nothing in the package calls `setup_logging` any more.** The CLI was its only
caller and the CLI retired; `node/live.py` configures Nautilus's own logger
through `LoggingConfig` instead, which covers the engine's records and not
these. So on a running node the twenty-one loggers above fall back to the root
logger's defaults, and the JSON file handler described below is reached only
by a script or a test that asks for it. That is a gap rather than a decision.

## Where records go

Console records go to **stderr** through rich, so stdout stays clean for piped
data - a script that prints a table is unaffected by log output.

`log_file=` (or `TILL_LOG_FILE`) adds a second handler writing
**newline-delimited JSON**, rotated at 32 MB with 5 backups. That is the
format worth having when something has been running for a week:

```json
{"ts":"2026-08-12T18:04:11.204+00:00","level":"INFO","logger":"till_infinity.adapters.mt5.data","msg":"fetched 42 bars","symbol":"OANDA:XAUUSD"}
```

Anything passed as `extra=` is merged into the object, so
`log.info("fetched %d bars", n, extra={"symbol": symbol.full})` gives you a
field you can filter on rather than a string you have to parse.

## Levels

| | |
|---|---|
| `setup_logging()` | INFO |
| `setup_logging(verbose=True)` | DEBUG |
| `setup_logging(quiet=True)` | WARNING |
| `setup_logging("ERROR")` | explicit level wins over both flags |
| `TILL_LOG_LEVEL=DEBUG` | used when nothing else is passed |

`setup_logging()` is idempotent - calling it again is a no-op unless you pass
`force=True`. `reset_logging()` tears the configuration down, which is what the
tests use.

## Noisy libraries

httpx logs a line per request, and yfinance is worse. Those loggers
(`httpx`, `httpcore`, `websockets`, `wsproto`, `yfinance`, `urllib3`, …) are
pinned to WARNING so they cannot drown out our own records - except under
`-v`, where you presumably want to see them.

## Environment

| | |
|---|---|
| `TILL_LOG_LEVEL` | DEBUG / INFO / WARNING / ERROR |
| `TILL_LOG_FILE` | path for the JSON-lines log |
| `TILL_LOG_JSON` | `1` makes console output JSON too |

## On the module name

The file is `till_infinity/utils/logging.py`, which looks like it should shadow
the standard library. It does not: Python 3 imports are absolute, so `import
logging` anywhere in this package still resolves to the stdlib.
`test_our_logging_module_does_not_shadow_the_stdlib_inside_the_package` pins
that.
