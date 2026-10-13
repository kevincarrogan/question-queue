default:
    @just --list --unsorted

# First-time bootstrap: dependencies and git hooks
[group('setup')]
setup: install
    uv run pre-commit install

# Install dependencies from the lockfile
[group('setup')]
install:
    uv sync

# Run the TUI against a file (scratch.md by default, git-ignored)
[group('dev')]
dev file='scratch.md':
    uv run qq {{file}}

# Build the wheel and sdist into dist/
[group('dev')]
build:
    uv build

# Run the test suite
[group('quality')]
test *args:
    uv run pytest {{args}}

# Run every linter
[group('quality')]
lint *args:
    uv run pre-commit run --all-files {{args}}

# Format in place
[group('quality')]
format:
    uv run ruff format
    uv run ruff check --fix

# Verify formatting
[group('quality')]
format-check:
    uv run ruff format --check

# Static type checks
[group('quality')]
typecheck:
    uv run mypy

# The CI gate
[group('quality')]
check: format-check lint typecheck test

# Remove caches and the local env
[group('quality')]
clean:
    rm -rf .venv .mypy_cache .pytest_cache .ruff_cache dist
    find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Add Python dependencies
[group('deps')]
[positional-arguments]
add +pkgs:
    uv add "$@"

# Remove Python dependencies
[group('deps')]
[positional-arguments]
remove +pkgs:
    uv remove "$@"

# Refresh the lockfile
[group('deps')]
lock:
    uv lock
