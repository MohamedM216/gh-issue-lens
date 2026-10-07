#!/usr/bin/env bash

set -euo pipefail

echo "Installing ruff..."
python3 -m pip install --upgrade ruff

echo "Checking tab/space indentation..."
python3 -m tabnanny .

echo "Formatting Python files..."
python3 -m ruff check --fix .
python3 -m ruff format .

echo "Done."