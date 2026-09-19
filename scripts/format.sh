#!/bin/bash
# Auto-format the codebase with black.
set -e

echo "Running black..."
uv run black backend main.py

echo "Done."
