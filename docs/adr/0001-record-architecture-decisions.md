# 0001. Record architecture decisions

- **Status:** Accepted (2026-10-28)
- **Date:** 2026-10-28

## Context

This repository already keeps its reasoning, and keeps it well: `subjects.py`
says where every parameter came from and which are placeholders, `bus.py`
records why a topic exists, and `research/docs/` holds the measurement behind
each claim including the six times an effect appeared and was not there. The
culture is **corrections kept beside the thing they correct**, not quietly
fixed.

What there is no home for is a decision about the *shape* of the system. Those
have been living in module docstrings, which works until a decision spans
services - and the one being taken now, a `services/` layout with two
languages, spans all of them. A docstring in the service that happened to be
edited first is the wrong place for it, because the next person edits a
different service.

## Decision

Architecture decisions go in `docs/adr/NNNN-title.md`, numbered in order, each
with **Status**, **Date**, and where it applies **Supersedes** and **Amends**.
A decision that changes is not edited: a new ADR supersedes it, and the old one
stays accepted-then-superseded so the reasoning survives.

Short-lived or purely mechanical choices stay where they are, in the code's own
comments. An ADR is for a decision that someone will otherwise have to
reconstruct from the diff.

## Consequences

Four decisions are recorded with this one: the `services/` layout and the bus
as the only link (0002), the language set (0003), and risk rules having one
owner (0004). `research/docs/` keeps its job - what the market does - and
`docs/specs/` keeps its own, the dated design a plan is built from.
