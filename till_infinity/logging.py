"""Project logging: one place that decides where debug/info/warn/error go.

Modules never configure anything — they just do::

    from till_infinity.logging import get_logger

    log = get_logger(__name__)
    log.debug("resolved %s", symbol)

The entry point (the CLI, a script, a notebook) calls :func:`setup_logging`
once. Console output goes to stderr through rich so stdout stays clean for
piped data; ``--log-file`` additionally writes newline-delimited JSON, which is
what you want when a collector has been running for a week.

Note the module name: ``import logging`` inside this package still resolves to
the standard library, since Python 3 imports are absolute.

Environment:

    TILL_LOG_LEVEL   DEBUG / INFO / WARNING / ERROR (default INFO)
    TILL_LOG_FILE    path for the JSON-lines log
    TILL_LOG_JSON    "1" to make console output JSON too
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

#: Human-facing command output (tables, summaries). Not for log records.
console = Console()
#: Log records and progress chatter, kept off stdout.
err_console = Console(stderr=True)

DEFAULT_LEVEL = "INFO"

#: Libraries that log a line per HTTP request or worse. Raised to WARNING
#: unless the caller explicitly asks for debug.
NOISY_LOGGERS: tuple[str, ...] = (
    "asyncio",
    "hpack",
    "httpcore",
    "httpx",
    "httpx_ws",
    "peewee",
    "urllib3",
    "websockets",
    "wsproto",
    "yfinance",
)

_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
    "getMessage",
}

#: Module state, held in a dict so setup/reset need no `global`.
_state = {"configured": False}


def log_level(value: str | int | None, default: str = DEFAULT_LEVEL) -> int:
    """Coerce ``"debug"`` / ``10`` / ``None`` into a logging level int."""
    if value is None:
        value = default
    if isinstance(value, int):
        return value
    resolved = logging.getLevelNamesMapping().get(str(value).upper())
    if resolved is None:
        raise ValueError(f"unknown log level {value!r}")
    return resolved


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with any ``extra=`` fields merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _RESERVED and not key.startswith("_")
            }
        )
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload, default=str).decode()


def setup_logging(
    level: str | int | None = None,
    *,
    verbose: bool = False,
    quiet: bool = False,
    log_file: str | Path | None = None,
    json_console: bool | None = None,
    force: bool = False,
) -> logging.Logger:
    """Configure the root logger. Safe to call more than once.

    `verbose` forces DEBUG, `quiet` forces WARNING; an explicit `level` beats
    both. Without any of them the ``TILL_LOG_LEVEL`` env var decides.
    """
    root = logging.getLogger()
    if _state["configured"] and not force:
        return root

    if level is not None:
        resolved = log_level(level)
    elif verbose:
        resolved = logging.DEBUG
    elif quiet:
        resolved = logging.WARNING
    else:
        resolved = log_level(os.environ.get("TILL_LOG_LEVEL"))

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    if json_console is None:
        json_console = os.environ.get("TILL_LOG_JSON", "") == "1"

    if json_console:
        console_handler: logging.Handler = logging.StreamHandler()
        console_handler.setFormatter(JsonFormatter())
    else:
        console_handler = RichHandler(
            console=err_console,
            rich_tracebacks=True,
            show_path=resolved <= logging.DEBUG,
            # Everything this project stores is UTC; the console should agree.
            log_time_format=lambda when: Text(when.astimezone(UTC).strftime("%H:%M:%S")),
        )
        console_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console_handler)

    target = log_file or os.environ.get("TILL_LOG_FILE")
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A collector runs for weeks; cap the log rather than the disk.
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=32 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)

    root.setLevel(resolved)
    quiet_noisy_loggers(logging.DEBUG if resolved <= logging.DEBUG else logging.WARNING)
    _state["configured"] = True
    return root


def quiet_noisy_loggers(level: int = logging.WARNING) -> None:
    """Stop third-party libraries from drowning out our own records."""
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)


def get_logger(name: str | None = None) -> logging.Logger:
    """The logger for a module — ``get_logger(__name__)``."""
    return logging.getLogger(name if name else "till_infinity")


def reset_logging() -> None:
    """Forget the configuration (tests, or re-configuring mid-process)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    _state["configured"] = False
