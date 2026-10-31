"""Venue integrations, one package each.

Inside `till_infinity` because that is the distribution that installs, and
laid out inside like a Nautilus adapter crate - `config.py`, `data.py`,
`execution.py`, `factories.py`, `providers.py`, mirroring the `config.rs`,
`data.rs`, `execution.rs`, `factories.rs` their in-tree Rust adapters carry.
Their adapter work is going to Rust, so a rewrite or an upstream contribution
should be a translation rather than a redesign.
"""
