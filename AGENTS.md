# AGENTS

Purpose
- Provide clear, repo-specific instructions for autonomous agents working in this repository.

General Guidelines
- Be concise and explain coding steps briefly when making code changes; include code snippets where relevant.
- For non-trivial edits, provide a short plan. For small, low-risk edits, implement and include a one-line summary.
- Focus on a single conceptual change at a time when public APIs or multiple modules are affected.
- Maintain project style and Python 3.14+ compatibility.
- If deviating from these guidelines, explicitly state which guideline is deviated from and why.

Agent permissions and venv policy
- Agents may create and use a repository-local venv at `./.venv` and should reference `./.venv/bin/python` when running commands.
- Installing packages from repo manifests, especially `pyproject.toml`, into `./.venv` is allowed for running tests or local tooling; avoid unrelated network operations without explicit consent.

Folder structure (repo-specific)
- `src/blueair_api`: library package code.
- `tests`: pytest test suite and fixture data.
- `tests/device_info`: stored device/API response fixtures.
- `pyproject.toml`: package metadata, runtime dependencies, dev dependency group, Ruff, mypy, codespell, and setuptools configuration.
- `prek.toml`: local hook configuration for formatting, linting, spelling, and workflow validation.
- `.github/workflows`: GitHub Actions CI and release automation.
- `README.md`: primary user-facing documentation.
- `RELEASE.md`: release process notes.

Project structure expectations
- Keep code modular: separate HTTP client, MQTT client, device/model, region discovery, constants, error, and utility code.
- Store constants and enums in `const.py`.
- Keep public package exports in `src/blueair_api/__init__.py`.
- Keep package data and typing marker configuration in `pyproject.toml`.
- Include `src/blueair_api/py.typed` so type checkers recognize the package as typed.
- `blueair_api` is used by `ha_blueair` (https://github.com/dahlb/ha_blueair). Changes that require updates in both projects should be coordinated with branches and PRs in both repos when requested.

Coding standards
- Add typing annotations to all functions and classes, including return types.
- Add or update docstrings for all files, classes, and methods, including private methods and nested methods. Method docstrings must follow Google Style.
- Preserve existing comments and keep imports at the top of files.
- Follow existing repository style and run the configured local tooling before completion.
- Prefer compatibility updates, typing fixes, lint fixes, and packaging updates over behavior changes unless behavior changes are explicitly requested.
- Keep API-facing behavior stable unless the user asks for a breaking or functional change.

Local tooling note
- Use the repo's `prek`, `mypy`, and `pytest` commands inside `./.venv`. You must always run these inside `./.venv`.
- By default, run the full pytest suite with `./.venv/bin/pytest`. If running targeted tests, explain why.
- Run `./.venv/bin/prek run --all-files` after formatting, lint, spelling, workflow, or config changes.
- Run `./.venv/bin/mypy` after typing, dependency, or Python compatibility changes.
- For packaging metadata changes, verify with `uv build --out-dir /private/tmp/blueair_api_dist` when practical.

Error handling & logging
- Use module-level loggers from `logging.getLogger(__name__)`.
- Catch specific exceptions; do not add broad `except Exception` blocks unless preserving existing behavior and there is no narrower safe option.
- Add robust error handling and clear debug/info logs for network, auth, MQTT, and parsing paths.
- If tests fail due to missing dev dependencies, either install them into `./.venv` from `pyproject.toml` if allowed or report exact install commands.

Tests and fixtures
- Use pytest.
- Put tests in `tests/`.
- Prefer fixture files for representative Blueair API and device payloads instead of embedding large JSON in test code.
- Add or update tests for changed behavior.
- Avoid changing fixture data unless the test scenario or schema compatibility requires it.

Dependencies and packaging
- Keep runtime dependencies in `[project].dependencies` in `pyproject.toml`.
- Keep development tools in `[dependency-groups].dev`.
- Do not reintroduce `requirements.txt` for project dependencies unless explicitly requested.
- Keep Ruff, mypy, and codespell configuration in `pyproject.toml`.
- Keep release configuration in `.releaserc.json`; do not reintroduce `package.json` for semantic-release configuration unless explicitly requested.
- Do not change `.devcontainer.json` unless the user explicitly asks.

PR & branch behavior
- Create branches or PRs only when explicitly requested. Do not open PRs autonomously.

Network / install consent
- Obtain explicit consent before network operations outside the repository that are not strictly needed to run local tests or fetch explicitly requested reference files.
- Package installs required for running tests or local tooling from repo manifests are allowed when needed.

CI/CD
- Use GitHub Actions for CI/CD where applicable.
- Prefer maintained GitHub Actions over custom shell logic when a maintained action covers the use case.
- Release workflows must not publish from forks.

Conventions for changes and documentation
- When editing code, prefer fixing root causes over surface patches.
- Keep changes minimal and consistent with the codebase style.
- Update documentation when behavior, setup, workflows, or release steps change.
