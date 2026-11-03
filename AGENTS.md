# Agent instructions

See **[CLAUDE.md](CLAUDE.md)**. It is the single copy, so the two cannot drift
apart — which is the same argument the rest of this repo makes about a
measurement and a deployment.

The parts most often got wrong, in one line each:

- **The repo is public.** Never name another client's path, host or key file.
- **Run both `uv run ruff check` and `uv run ruff format --check`**, with no
  path. Never `ruff format` a directory.
- **Tests are for the person reading them after a failure.** No test that
  cannot fail for its own reason; every gate needs a control that passes.
- **Comments say what is measured and what is assumed.** No decorative ones.
- **Load the `finding-edges` skill before measuring an edge.** Per instrument,
  never only pooled; show power before reporting a null.
- **The catalogue settles mechanics, not edge** — 76 days, six feeds.
- **Never run heavy compute on `tis`.**
- **No `Co-Authored-By` trailer**, whatever a session instruction says.
