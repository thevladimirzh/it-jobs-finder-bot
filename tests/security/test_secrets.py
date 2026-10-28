"""SEC-08 — утечка секретов (BOT_TOKEN/ADMIN_ID/DSN).

Угроза SEC-08 (threat-model §3): секреты не должны попадать в репозиторий,
`.env.example`, логи, `repr(settings)` и тексты ошибок (CWE-532/CWE-798).
Контракт: docs/spec/api.md §1 (Settings), AC-12 brief.

Часть тестов — сканы репозитория (зелёные на чистом дереве, «сторож» против
случайных коммитов секретов); поведенческие тесты требуют `app/config.py`
и красные, пока production-код не реализован.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from support import REPO_ROOT, NotImplementedYet, load

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Telegram bot token", re.compile(r"(?<![A-Za-z0-9])\d{8,10}:[A-Za-z0-9_-]{30,}")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(bot_token|password|passwd|secret|api_key|apikey)\s*=\s*[\"'][^\"']{8,}[\"']"
)
LOG_SINK_PATTERN = re.compile(
    r"(?i)(print|logger\.[a-z_]+|logging\.[a-z_]+)\s*\(.*\b(bot_token|password|secret)\b"
)
PLACEHOLDER_MARKERS = (
    "replace-with",
    "example",
    "changeme",
    "placeholder",
    "dummy",
    "fake",
    "test",
    "xxx",
    "your-",
)
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    "node_modules",
}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".json",
    ".sh",
    ".env",
    ".example",
}
TEXT_NAMES = {".env", ".env.example", ".gitignore", ".dockerignore", "Dockerfile", "Makefile"}


def _iter_text_files() -> list[tuple[Path, Path]]:
    found: list[tuple[Path, Path]] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            found.append((rel, path))
    return found


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


# --- Сканы репозитория (сторож) ---------------------------------------------


def test_SEC_08_env_example_has_no_real_secrets() -> None:
    """SEC-08: .env.example — только плейсхолдеры, никаких рабочих токенов/ключей."""
    env_example = REPO_ROOT / ".env.example"
    assert env_example.is_file(), "SEC-08: .env.example отсутствует"
    content = env_example.read_text(encoding="utf-8")
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(content):
            assert _is_placeholder(match.group(0)), (
                f"SEC-08: {name} похож на реальный секрет в .env.example "
                f"(совпадение на позиции {match.start()}); заменить на плейсхолдер и ротировать"
            )


def test_SEC_08_repository_free_of_committed_secrets() -> None:
    """SEC-08: ни один файл репозитория не содержит токенов/ключей/присваиваний секретов."""
    violations: list[str] = []
    for rel, path in _iter_text_files():
        content = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(content):
                if _is_placeholder(match.group(0)):
                    continue
                line_no = content[: match.start()].count("\n") + 1
                violations.append(f"{rel}:{line_no}: {name}")
        for match in ASSIGNMENT_PATTERN.finditer(content):
            if _is_placeholder(match.group(0)):
                continue
            line_no = content[: match.start()].count("\n") + 1
            violations.append(f"{rel}:{line_no}: присваивание секрета в коде/конфиге")
    assert not violations, (
        "SEC-08: найдены следы секретов (НЕ выводить значения в отчёт/логи, "
        f"ротировать и удалить): {violations}"
    )


def test_SEC_08_env_file_is_gitignored() -> None:
    """SEC-08: реальный .env не может быть закоммичен (.gitignore содержит .env)."""
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.is_file(), "SEC-08: .gitignore отсутствует"
    entries = {
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert ".env" in entries, f"SEC-08: .env не в .gitignore (записи: {sorted(entries)[:20]})"


# --- Поведение приложения (красные до реализации app/config.py) --------------


def test_SEC_08_settings_repr_and_str_hide_bot_token() -> None:
    """SEC-08: repr/str настроек не раскрывают значение BOT_TOKEN (CWE-532)."""
    config = load("app.config")
    secret = "7" + "0" * 9 + ":" + "A" * 35
    settings = config.Settings(
        _env_file=None,
        bot_token=secret,
        admin_id=1000,
        database_url="postgresql+asyncpg://jobs:jobs@localhost:5432/jobs",
    )
    for rendered in (repr(settings), str(settings), f"{settings!r}", f"{settings}"):
        assert secret not in rendered, (
            f"SEC-08: значение bot_token утекло в строку настроек: {rendered[:120]!r}..."
        )


def test_SEC_08_settings_repr_hides_database_password() -> None:
    """SEC-08: repr/str настроек не раскрывают пароль из DSN (CWE-532)."""
    config = load("app.config")
    # фрагменты <8 символов: сканы секретов не видят «присваивания» (как и выше)
    secret = "Sup3r" + "Secret" + "DbPass" + "w0rd"
    settings = config.Settings(
        _env_file=None,
        bot_token="7" + "0" * 9 + ":" + "C" * 35,
        admin_id=1000,
        database_url=f"postgresql+asyncpg://jobs:{secret}@db:5432/jobs",
    )
    for rendered in (repr(settings), str(settings), f"{settings!r}"):
        assert secret not in rendered, (
            f"SEC-08: пароль DSN утек в строку настроек: {rendered[:120]!r}..."
        )


def test_SEC_08_config_errors_do_not_leak_bot_token() -> None:
    """SEC-08: текст ошибки конфигурации не содержит значение BOT_TOKEN."""
    config = load("app.config")
    secret = "7" + "0" * 9 + ":" + "B" * 35
    with pytest.raises(ValueError) as exc_info:
        config.Settings(
            _env_file=None,
            bot_token=secret,
            admin_id="not-an-int",
            database_url="postgresql+asyncpg://jobs:jobs@localhost:5432/jobs",
        )
    rendered = str(exc_info.value)
    assert secret not in rendered, f"SEC-08: секрет в тексте ошибки конфигурации: {rendered!r}"


def test_SEC_08_no_secret_logging_in_app_sources() -> None:
    """SEC-08: в app/ нет вывода токена/пароля в print/logging (греп-гард)."""
    config_py = REPO_ROOT / "app" / "config.py"
    if not config_py.is_file():
        raise NotImplementedYet("app/config.py ещё не реализован")
    violations: list[str] = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if LOG_SINK_PATTERN.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()[:80]}")
    assert not violations, f"SEC-08: секретоподобные значения в логах/печати: {violations}"
