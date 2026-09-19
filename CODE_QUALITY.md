# Code Quality Tooling

## What was added

- **black** as a dev dependency (`pyproject.toml` `[dependency-groups] dev`), configured under `[tool.black]` (`line-length = 88`, `target-version = ["py313"]`).
- `scripts/format.sh` — runs `uv run black backend main.py` to auto-format the codebase in place.
- `scripts/check.sh` — runs `uv run black --check --diff backend main.py` followed by `uv run pytest`; exits non-zero if formatting is off or any test fails. Use this in CI or before committing.
- Reformatted every existing Python file under `backend/` and `main.py` with black for consistent style throughout the codebase (no behavioral changes).

## Usage

```bash
./scripts/format.sh   # auto-format
./scripts/check.sh    # verify formatting + run tests, non-zero exit on failure
```

The frontend (`frontend/`) has no build step or JS tooling and was intentionally left out of scope — this covers the Python backend only.
