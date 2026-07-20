# Repository Guidelines

## Project Structure & Module Organization

- `main.py` and `__init__.py` expose the AstrBot plugin entry points.
- `src/` contains the application code: Bangumi/API clients in `api/` and `bangumi_client.py`, persistence in `db/`, domain services in `app/`, scheduling and environment helpers in `utils/`, and rendering in `card_renderer.py` and `templates/cards/`.
- `tests/` contains pytest tests, with shared fixtures in `tests/conftest.py`.
- `scripts/` holds preview and packaging utilities; `docs/` stores generated preview assets. Keep runtime data under `data/` out of source changes unless a fixture or migration requires it.

## Build, Test, and Development Commands

Install dependencies in a virtual environment:

```powershell
python -m pip install -r requirements.txt
pip install ruff mypy pytest pytest-asyncio types-PyYAML
```

Run the quality checks used by CI:

```powershell
python -m pytest -q
ruff check .
ruff format --check .
python -m mypy src main.py
```

Preview cards with the configured AstrBot T2I service using `python scripts\preview_t2i_cards.py` (add `--only subscriptions` for a focused preview). Package a release on Windows with `./scripts/package_plugin.ps1`.

## Coding Style & Naming Conventions

Use Python 3.12-compatible code, four-space indentation, type hints, and async APIs where the surrounding code is async. Ruff is configured for an 88-character line length and rules `E,F,I,B,UP,SIM,RUF`; run its formatter rather than hand-formatting. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and descriptive test names such as `test_subscription_retries_failed_delivery`.

## Testing Guidelines

Use pytest and pytest-asyncio. Add regression tests beside the affected behavior in `tests/`, isolate external API calls with fixtures or mocks, and keep tests deterministic. Run the full suite with `python -m pytest -q`; new behavior should include coverage for success and failure paths.

## Commit & Pull Request Guidelines

Recent commits use concise, imperative prefixes such as `feat:`, `fix:`, `docs:`, and `chore:`; retain that style and mention breaking changes with `!` when applicable. Pull requests should explain user-visible behavior, implementation impact, and verification commands. Link related issues, include card screenshots or preview output for rendering changes, and call out configuration, migration, or compatibility effects.

## Configuration & Security

Do not commit access tokens, proxy credentials, generated databases, or temporary images. Use AstrBot's configuration for Bangumi credentials and T2I endpoints, and preserve backward-compatible data migrations when changing database models.
