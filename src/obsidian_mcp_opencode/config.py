from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from dotenv import dotenv_values

from .errors import ConfigError

WRITE_PATTERNS: Final[list[str]] = [
    "Projects/{slug}/PROJECT.md",
    "Projects/{slug}/LOGS.md",
    "Projects/{slug}/SUMMARY.md",
    "Projects/{slug}/PRD.md",
    "Projects/{slug}/PREMORTEM.md",
    "Projects/{slug}/PREMORTEM-{feature_slug}.md",
    "Projects/{slug}/DESIGN.md",
    "Projects/{slug}/RESEARCH.md",
    "Projects/{slug}/TASKS.md",
    "Projects/{slug}/docs/*.md",
    "Projects/PIPELINE_INDEX.md",
    "Freya - Mistake Log.md",
    "LOGS.md",
]

APPEND_ONLY_PATTERNS: Final[list[str]] = [
    "Freya - Mistake Log.md",
    "LOGS.md",
    "Projects/*/LOGS.md",
]

PROTECTED_MEMORY_PATHS: Final[list[str]] = [
    "Projects/PIPELINE_INDEX.md",
]

MISTAKE_LOG_FILENAME: Final[str] = "Freya - Mistake Log.md"
PIPELINE_INDEX_PATH: Final[str] = "Projects/PIPELINE_INDEX.md"
SLUG_REGEX: Final[str] = r"^[a-z0-9][a-z0-9-]{0,79}$"
RESERVED_SEGMENTS: Final[frozenset[str]] = frozenset(
    {"home", "tmp", "etc", "Users", "root", "var", "bin", ".."}
)
HIDDEN_FILE_PREFIX: Final[str] = "."
TIMEZONE: Final[str] = "Asia/Jakarta"
REQUEST_TIMEOUT_SECONDS: Final[int] = 30
MAX_SEARCH_RESULTS: Final[int] = 100
MAX_SEARCH_SNIPPET_CHARS: Final[int] = 300
MAX_SEARCH_QUERY_CHARS: Final[int] = 200
PATH_ECHO_MAX_CHARS: Final[int] = 200
DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:27123"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
READ_ONLY_MODE: Final[bool] = False

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "obsidian-mcp-opencode"
)
DEFAULT_ENV_FILE = DEFAULT_CONFIG_DIR / ".env"
PROJECT_ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime configuration. Built once at startup, then frozen."""

    vault_path: Path
    api_key: str
    base_url: str
    log_level: str
    read_only: bool


def _load_env_values(env_file: Path | None) -> dict[str, str]:
    if env_file is not None:
        selected_file = env_file
        warned_project_fallback = False
    elif DEFAULT_ENV_FILE.exists():
        selected_file = DEFAULT_ENV_FILE
        warned_project_fallback = False
    elif PROJECT_ENV_FILE.exists():
        selected_file = PROJECT_ENV_FILE
        warned_project_fallback = True
    else:
        selected_file = None
        warned_project_fallback = False

    values = dict(os.environ)

    if selected_file is None:
        return values

    file_values = {
        key: value
        for key, value in dotenv_values(selected_file).items()
        if value is not None
    }
    values.update(file_values)

    if warned_project_fallback:
        LOGGER.warning("Using fallback project .env file at %s", selected_file)

    return values


def _validate_vault_path(raw_vault_path: str | None) -> Path:
    if not raw_vault_path:
        raise ConfigError("Missing required configuration: OBSIDIAN_VAULT_PATH")

    vault_path = Path(raw_vault_path)
    if not vault_path.is_absolute():
        raise ConfigError("OBSIDIAN_VAULT_PATH must be an absolute path")
    if not vault_path.exists():
        raise ConfigError("OBSIDIAN_VAULT_PATH does not exist")
    if not vault_path.is_dir():
        raise ConfigError("OBSIDIAN_VAULT_PATH must point to a directory")
    if vault_path.is_symlink():
        raise ConfigError("OBSIDIAN_VAULT_PATH must not be a symlink")

    return vault_path.resolve(strict=True)


def _validate_api_key(api_key: str | None) -> str:
    if not api_key:
        raise ConfigError("Missing required configuration: OBSIDIAN_API_KEY")
    return api_key


def _validate_base_url(base_url: str | None) -> str:
    candidate = base_url or DEFAULT_BASE_URL
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("OBSIDIAN_BASE_URL must be a valid http(s) URL")
    return candidate.rstrip("/")


def load_config(*, env_file: Path | None = None, read_only: bool = False) -> Config:
    """Load and validate runtime configuration."""

    values = _load_env_values(env_file)
    vault_path = _validate_vault_path(values.get("OBSIDIAN_VAULT_PATH"))
    api_key = _validate_api_key(values.get("OBSIDIAN_API_KEY"))
    base_url = _validate_base_url(values.get("OBSIDIAN_BASE_URL"))
    log_level = (values.get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()

    return Config(
        vault_path=vault_path,
        api_key=api_key,
        base_url=base_url,
        log_level=log_level,
        read_only=READ_ONLY_MODE or read_only,
    )
