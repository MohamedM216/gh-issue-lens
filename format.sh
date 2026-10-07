#!/usr/bin/env bash

set -euo pipefail

echo "[1/4] Installing ruff..."
python3 -m pip install --upgrade ruff

echo "[2/4] Auto-fixing tab/space indentation..."
python3 - <<'PY'
from pathlib import Path
import sys


EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}


def replace_leading_tabs_with_4_spaces(text: str) -> str:
    """
    Replace tabs used for indentation with 4 spaces.

    This is the most common fix for Python projects configured with:
    indent_size = 4
    """
    lines = text.splitlines(keepends=True)
    fixed_lines = []

    for line in lines:
        stripped = line.lstrip(" \t")
        leading = line[: len(line) - len(stripped)]

        if "\t" in leading:
            leading = leading.replace("\t", "    ")

        fixed_lines.append(leading + stripped)

    return "".join(fixed_lines)


def expand_leading_tabs(text: str, tabsize: int = 8) -> str:
    """
    Expand leading tabs using Python's normal tab stop behavior.

    This can fix more difficult mixed tab/space cases.
    """
    lines = text.splitlines(keepends=True)
    fixed_lines = []

    for line in lines:
        stripped = line.lstrip(" \t")
        leading = line[: len(line) - len(stripped)]

        if "\t" in leading:
            leading = leading.expandtabs(tabsize)

        fixed_lines.append(leading + stripped)

    return "".join(fixed_lines)


def compile_ok(code: str, filename: str) -> bool:
    try:
        compile(code, filename, "exec")
        return True
    except SyntaxError:
        return False


def should_skip(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


changed_files = 0
failed_files = 0

for path in Path(".").rglob("*.py"):
    if should_skip(path):
        continue

    try:
        original = path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"WARNING: Could not read {path}: {exc}", file=sys.stderr)
        continue

    if "\t" not in original:
        continue

    candidates = [
        ("leading tabs -> 4 spaces", replace_leading_tabs_with_4_spaces(original)),
        ("leading tabs -> expandtabs(8)", expand_leading_tabs(original, 8)),
        ("all tabs -> 4 spaces", original.replace("\t", "    ")),
        ("all tabs -> expandtabs(8)", original.expandtabs(8)),
    ]

    fixed = False

    for candidate_name, candidate_code in candidates:
        if candidate_code == original:
            continue

        if compile_ok(candidate_code, str(path)):
            path.write_text(candidate_code, encoding="utf-8")
            print(f"Fixed indentation in {path} using: {candidate_name}")
            changed_files += 1
            fixed = True
            break

    if not fixed:
        print(f"WARNING: Could not safely auto-fix indentation in {path}", file=sys.stderr)
        failed_files += 1

print(f"Indentation auto-fix finished. Changed files: {changed_files}. Failed files: {failed_files}.")

if failed_files > 0:
    sys.exit(1)
PY

echo "[3/4] Auto-fixing lint issues..."
python3 -m ruff check --fix . || true

echo "[4/4] Formatting code..."
python3 -m ruff format .

echo "Final checks..."
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m tabnanny .

echo "Done."