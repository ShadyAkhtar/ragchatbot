#!/bin/bash
# Run code quality checks: formatting check + test suite.
# Fails (non-zero exit) if formatting is off or any test fails.
set -e

echo "Checking formatting with black..."
uv run black --check --diff backend main.py

echo "Running tests..."
uv run pytest

echo "All checks passed."
