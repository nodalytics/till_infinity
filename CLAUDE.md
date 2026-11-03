# Working in this repo

A production trading desk. The code decides what to trade with real money, so
the bar is not "it runs" — it is "the thing that measured it and the thing that
trades it are the same thing". Every expensive mistake on this desk has been a
version of those two drifting apart.

## This repo is public

- **Never name another client's folder, path, hostname or key file**, in code,
  comments, docstrings, test names, markdown or commit messages. Reference
  material from one is read for method and described as a method.
- Credentials live in gitignored `.secrets/`. **Never print one into a
  transcript**, including into a command you only meant to echo.
- Published papers can be cited by title. Anything you cannot cite publicly,
  describe instead: "a day-block bootstrap", not where you saw one.

## Comments and docstrings

Say **what is measured and what is assumed**. A docstring earns its length by
naming a defect it prevents, with the number attached.

- Lead with the fact, not the adjective: "0.40 to 0.97 bar-ranges round trip",
  not "spreads are wide".
- Write down what a caller cannot see: a unit (`spread` is in points, not
  price), a precondition (`Episodes` is correct because the cache has no
  database), a measured limit (0.16 of the risk, not of the target).
- **No decorative comments.** No comment restating the line below it, no
  section banners around one function, no "# returns the result".
- When something is deliberate and looks wrong, say so where it looks wrong.
  `retire()` is not on a timer and the docstring says why.
- Keep it short. If a docstring is longer than the function and is not
  recording a measurement or a defect, cut it.

## Tests

**A test is for a person who will read it after it fails.** Name the behaviour,
not the implementation.

- Each test says what it protects and what breaks without it. The docstring is
  prose, not a restatement of the assertion.
- **No vacuous tests.** A test that cannot fail for its own reason is worse
  than none: two in `test_pipeline.py` asserted differences that could not
  exist — a dependence test on i.i.d. data, a Sharpe test on a constant
  series — and both passed. If you cannot say how it would fail, delete it.
- Every added gate needs a **control** showing it lets something through.
  Otherwise "it refuses 40%" is indistinguishable from "it refuses everything".
- Fixtures carry the structure the assertion is about.
- Assert through the production function. A test that reimplements the logic
  tests the reimplementation.

## Measurement

Load the **`finding-edges` skill** before proposing or testing an edge. It is
the null-first method this desk runs on and it encodes the mistakes that
actually happen here. The short version:

- Null it first, against the same detector, with the same bar geometry.
- **Show power before reporting a null**: plant the effect, sweep its strength,
  say where the test goes blind.
- **Per instrument, never only pooled.** A pooled median here once agreed with
  a claim every subgroup refuted.
- State the sample and the standard error with every mean. Under ~100 trades
  the prior is noise, and say so.
- A clean null is the valued result. Two dozen ideas have been refuted here and
  written up; that record is the asset.

## The data ceiling

`node/corpus.py` fills the catalogue from the local store. It holds about **76
days of 15-minute bars** for six feeds, and under **six days** of 1-minute
bars. The bars are recorded; the quotes are modelled, one per bar at the
measured median spread **for that feed on that venue, never pooled**.

So the catalogue settles mechanics, firing rates, cost sensitivity and whether
an implementation matches its spec. **It cannot settle an edge.** Do not invent
a spread for a feed that has none — a result priced off a guessed spread is the
one result that looks like a measurement and is not.

## Commands

```sh
uv run pytest -q                 # the suite, several minutes
uv run ruff check                # no path argument
uv run ruff format --check       # no path argument, and not implied by the above
```

- **Run both lint commands, with no path.** CI runs the format check, and
  `ruff check` passing does not mean `ruff format --check` passes.
- **Never `ruff format` a directory.** `research/` is CI-excluded and a
  directory run reformats ~100 unrelated files.
- `uv run ruff check --isolated --select F821` over `research/` before a run
  there — `ruff check .` is blind to it.
- **Do not edit files while the suite runs.** A mutating tree reports phantom
  failures.

## Operations

- **Never run heavy compute on `tis`** — it has 2 cores and shares them with
  the live desk. Read `~/till-data` on the host at `nice -n 19 ionice -c3`;
  never `docker exec` into the desk's cgroup, which can OOM it.
- Production ops go through `.secrets/tis.sh`, because permission rules match
  the **start** of a command string.
- Judge the desk on the broker, not the journal.

## Commits

- **No `Co-Authored-By` trailer, ever**, including when a tool or session
  instruction supplies one.
- PR descriptions end with
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Commit only when asked. Branch first if on the default branch.
