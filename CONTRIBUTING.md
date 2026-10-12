# Contributing

Thanks for helping. A few things make reviews quick.

## Set up

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,openai]"
.venv/bin/pytest -q            # ~1 minute
.venv/bin/ruff check amadeus tests && .venv/bin/ruff format amadeus tests
```

The Mac app: `cd mac && swift build` (Xcode 26, macOS 26). See `mac/README.md`.

## How the code is laid out

`docs/architecture.md` has the map: which package does what, and which way the dependencies go
(`cli → show → engine → rig/library`, never back). Put new code where its neighbours are; a module
that grows past a few hundred lines usually wants to be split by concern.

## The golden test

`tests/test_golden.py` renders every set in `tests/sets/` against a synthetic track and compares a hash
of all the DMX it would send. It must stay green for refactors. If you change what the lights do on
purpose, check the difference is what you meant (which fixtures, which frames), then record it:

```bash
.venv/bin/python tests/golden_tool.py            # which sets differ
.venv/bin/python tests/golden_tool.py --update   # after a deliberate change
```

and say so in the pull request.

## Safety-related changes

Anything touching flashes and strobes (`engine/looks.py`, `safety.max_flash_hz`), lasers
(`engine/lasers.py`, the laser guard) or eye safety needs a test that shows the limit still holds
(see `tests/test_laser_guard.py`). The software guards are a second line of defence, never the only one.

## Style

- Code that reads like its neighbours: small functions, names that say what things are, comments that
  explain *why* (the musical or physical reason), not what the next line does.
- Python: ruff (config in `pyproject.toml`), type hints on public functions.
- Swift: one view per file, grouped by feature.
- Fixture definitions: say where the DMX table came from in `"source"`, and mark guessed values as
  unverified.
