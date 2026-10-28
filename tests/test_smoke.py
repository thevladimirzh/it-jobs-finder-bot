"""Bootstrap smoke test: the clean test command must be green on an empty suite.

Runs with ``.venv/bin/python -m pytest`` from the repository root. Real tests live in
tests/unit, tests/acceptance, tests/security and tests/e2e and are written by their
owners (see AGENTS.md) — this file only guards the bootstrap layout.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    ".env.example",
    "alembic.ini",
    "alembic/env.py",
    "Dockerfile",
    "docker-compose.yml",
    "AGENTS.md",
)

REQUIRED_DIRS = (
    "app",
    "alembic/versions",
    "tests/unit",
    "tests/acceptance",
    "tests/security",
    "tests/e2e",
    "tests/features",
    "tests/data",
    "docs",
)


def test_python_is_312() -> None:
    assert sys.version_info[:2] == (3, 12)


def test_bootstrap_files_exist() -> None:
    missing = [rel for rel in REQUIRED_FILES if not (ROOT / rel).is_file()]
    assert not missing, f"missing files: {missing}"


def test_test_layout_exists() -> None:
    missing = [rel for rel in REQUIRED_DIRS if not (ROOT / rel).is_dir()]
    assert not missing, f"missing dirs: {missing}"
