"""Which rule placed an order, as a number the broker will keep.

**Here rather than in `strategies/config.py`, because two layers need it.** The
strategy layer decides which rule is placing an order; the venue adapter has to
stamp that rule's number on it and recognise it coming back. `test_service_boundaries`
forbids `adapters` from importing `strategies` - the dependency runs the other
way - and it was right to refuse: an attribution convention is not strategy
logic, it is an identifier shared by whoever writes it and whoever reads it.
`domain` is `INFRASTRUCTURE` in that test, below every service, which is where
something both layers need belongs.

The contents moved unchanged on 2026-11-20. `strategies.config` re-exports every
name, so the many callers that read it from there are unaffected.
"""

from __future__ import annotations

import hashlib

#: Stamped on every position this system opens, so `positions` and the panic
#: close can be filtered to *ours*. Any stable non-zero number would do; what
#: matters is that a hand-placed trade on the same terminal is never touched by
#: something here. Zero would mean "everything on the account", which is the
#: one value that must not be the default.
#:
#: This is the *base* of a band rather than a single number - see `MAGIC_BAND`.
DEFAULT_MAGIC = 777_701

#: How many magics one deployment occupies, starting at `Settings.magic`.
#:
#: The base itself means "ours, but we cannot say which strategy" - what a
#: position opened before per-strategy magics existed carries, and what the
#: panic close and reconciliation still have to recognise. Offsets 1 and above
#: name the strategy that asked for the trade, which is the only way to tell,
#: after a restart or from the terminal itself, which of several strategies
#: running side by side opened a given position. The order comment carries the
#: same name, but comments are advisory: brokers truncate and rewrite them,
#: and MT5 caps them at 31 characters. Magic survives.
MAGIC_BAND = 1_000

#: Strategy name to offset within the band. **Append-only.** These numbers end
#: up on positions held at a broker and in journal entries that outlive any one
#: release, so reordering this tuple would silently reattribute history: a
#: position opened by one strategy would start reading as another's. Add new
#: names at the end and never move an existing one.
#:
#: Deriving the offset from the *configured* strategy list instead would be the
#: same bug in a worse form - editing TRADING_STRATEGIES would renumber every
#: open position, and a restart mid-trade could not say who owned what.
MAGIC_ORDER: tuple[str, ...] = (
    "level-scalp",
    "confluence-scalp",
    "momentum-scalp",
    "approach-scalp",
    "swing-level",
    "sweep-aware",
    "fade-to-value",
    "council",
    # Appended, never inserted. A strategy added without a slot here still
    # trades - it stamps a hashed magic from the tail of the band - but that
    # hash has no inverse, so every position it opens reads as
    # "unattributed" on close and the strategy cannot be scored at all.
    # Both of these ran live for an hour before the missing entries were
    # noticed, and their two trades are unattributable in the record.
    "snap",
    "thesis-only",
    "runner",
    "inverse",
    # Removed 2026-08-28 as a near-duplicate of `swing-level`, which shares its
    # entries, context and higher-timeframe requirement; its resting entry and
    # horizon-scaled protection moved there. The slot stays reserved because
    # this table is append-only - a magic that has been on live orders has to
    # keep resolving to the name that placed them.
    "high-timeframe",
    "origin-swing",
    # 2026-09-02. The nine above are points in one parameter space and this is
    # the space itself; see `trading/opportunity.py`. Appended like every other
    # slot, because a magic that has been on a live order has to keep resolving
    # to the name that placed it.
    "opportunity",
    # 2026-09-03. `opportunity` with the target moved out of reach so the trail
    # decides - the measured best exit policy of six tested. See `Ride`.
    "ride",
    # 2026-09-14. Unified scalp thesis: trend context from 4h/1h and the
    # fast pullback entry from 15m/1m, with sweep-aware geometry guarding the
    # stop. Appended to preserve the strategy attribution table's append-only
    # contract.
    "cycle-scalp",
    # 2026-09-15. The cycle reading as an entry rather than a veto, gated on
    # that feed's own scored record - see `strategies/turning.py`. Appended,
    # never inserted: a magic that has been on a live order has to keep
    # resolving to the name that placed it.
    #
    # It shipped for one commit without this line, and the test below caught
    # it. Two earlier strategies did not get caught and ran live for an hour
    # each; their trades are unattributable in the record for ever.
    "cycle-turn",
    # 2026-09-16. `cycle-turn` one tier down and one condition looser: a 1h
    # mother cycle over 15m/30m, entries from 1m to 15m, gated on the
    # z-score's *displacement* rather than on displacement-plus-momentum -
    # which fires on 1.5% of calls and is why `cycle-turn` has never traded.
    # Agreement sizes the trade instead of gating it. See
    # `strategies/stretching.py`. Appended, never inserted.
    "cycle-turn-scalp",
    # 2026-10-26. The first strategy on this desk that is not level-based:
    # continuation of a bar the statespace service found surprising, stopped
    # and targeted off its band rather than off a level. See
    # `strategies/dispersing.py`. Appended before it is configured to run, not
    # after - the note above records two strategies that ran live for an hour
    # without a slot and whose trades are unattributable for ever.
    "statespace-surprise",
    # 2026-11-20. **The port's rules, which had no slots at all.** Appended
    # when `magic_for` was finally wired: until then this client stamped
    # `self._cfg.magic` - the bare base - on every order, so all 166 deals of
    # the fortnight to 2026-11-20 read `777701` and not one could be
    # attributed to a rule. A slot was worth nothing while the name never
    # reached `magic_for`, which is why these were missing for so long.
    #
    # All seven are `Profile.name` values, five of them in `TRADING_STRATEGIES`
    # today and two not. The unconfigured ones are registered **ahead** of
    # need on purpose: a rule that trades without a slot stamps a hashed
    # offset with no inverse, and the comment above records two that "ran live
    # for an hour before the missing entries were noticed" whose "trades are
    # unattributable in the record for ever". Pre-registering costs one of a
    # thousand band slots and removes that failure.
    "smc-bos-causal",
    "identity-arb",
    "vol-impulse",
    "zones",
    "smc-zones",
    "displacement-zones",
    "bands",
)


#: The prefix that marks an order tag as naming the rule that placed it.
#:
#: **An order tag is how a rule name reaches the venue adapter.** `magic_for`
#: below wants a `Profile.name` like `zones`; the adapter holds only
#: `order.strategy_id`, which is `ZonesEdge-BTCUSD_E637`, and a venue client
#: must not know how to parse a strategy id or what a profile is. Nautilus
#: carries `tags` on every order into the cache, so the name travels with the
#: order.
#:
#: Prefixed because the tag list is shared: `OrderFactory.bracket` already puts
#: `ENTRY`, `STOP_LOSS` and `TAKE_PROFIT` on the legs, and an adapter that took
#: "the first tag" or "any tag that is a known rule" would be guessing.
RULE_TAG = "rule:"


def rule_from_tags(tags: object) -> str:
    """The rule a set of order tags names, or `""`.

    `""` rather than a guess or a raise: an order with no rule tag is one this
    desk did not place through a `Desk` - a manual order, a test double, or a
    leg built before this channel existed - and `magic_for("")` answers the
    base magic, which means "ours, but we cannot say which rule". That is the
    honest answer and it is the behaviour every order had before this was
    wired.
    """
    if not tags:
        return ""
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        text = str(tag)
        if text.startswith(RULE_TAG):
            return text[len(RULE_TAG) :]
    return ""


def magic_for(base: int, strategy: str) -> int:
    """The magic one strategy stamps on its orders.

    See `trading-config.md` in research/docs.
    """
    if not strategy:
        return base
    if strategy in MAGIC_ORDER:
        return base + 1 + MAGIC_ORDER.index(strategy)
    fixed = len(MAGIC_ORDER)
    digest = hashlib.blake2s(strategy.encode(), digest_size=4).digest()
    span = MAGIC_BAND - 1 - fixed
    return base + 1 + fixed + int.from_bytes(digest, "big") % span


def strategy_for(base: int, magic: int) -> str:
    """The strategy a magic names, or "" when it does not name one.

    The inverse of `magic_for` for the fixed table only. A hashed offset has no
    inverse, so a plugin strategy's positions read as ours-but-unattributed,
    which is the honest answer rather than a guessed one.
    """
    offset = magic - base
    if 1 <= offset <= len(MAGIC_ORDER):
        return MAGIC_ORDER[offset - 1]
    return ""


def ours(base: int, magic: int) -> bool:
    """Whether a position at the broker belongs to this system.

    The band, not the base, because every strategy now stamps its own number.
    A comparison against the base alone - which is what this replaced - would
    make every position opened by a named strategy look like somebody else's,
    so the trader would neither manage nor close its own trades.
    """
    return base <= magic < base + MAGIC_BAND
