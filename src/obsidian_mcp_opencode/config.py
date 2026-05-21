from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from dotenv import dotenv_values

from .errors import ConfigError

WORKFLOW_GENERIC: Final[str] = "generic"
WORKFLOW_FREYA: Final[str] = "freya"
SUPPORTED_WORKFLOWS: Final[frozenset[str]] = frozenset(
    {WORKFLOW_GENERIC, WORKFLOW_FREYA}
)
DEFAULT_WORKFLOW: Final[str] = WORKFLOW_GENERIC

GENERIC_WRITE_PATTERNS: Final[list[str]] = [
    "**/*.md",
    "*.md",
]
GENERIC_APPEND_ONLY_PATTERNS: Final[list[str]] = []
GENERIC_PROTECTED_MEMORY_PATHS: Final[list[str]] = []

FREYA_WRITE_PATTERNS: Final[list[str]] = [
    # Generic project docs
    "Projects/{slug}/PROJECT.md",
    "Projects/{slug}/LOGS.md",
    "Projects/{slug}/SUMMARY.md",
    "Projects/{slug}/LESSONS.md",
    "Projects/{slug}/LESSONS_ARCHIVE.md",
    "Projects/{slug}/BUILD_LOG.md",
    "Projects/{slug}/PRD.md",
    "Projects/{slug}/PREMORTEM.md",
    "Projects/{slug}/DESIGN.md",
    "Projects/{slug}/RESEARCH.md",
    "Projects/{slug}/TASKS.md",
    "Projects/{slug}/REVIEW.md",
    "Projects/{slug}/SECURITY.md",
    "Projects/{slug}/DEVILS-ADVOCATE.md",
    # Feature-suffixed variants
    "Projects/{slug}/PRD-{feature_slug}.md",
    "Projects/{slug}/PREMORTEM-{feature_slug}.md",
    "Projects/{slug}/DESIGN-{feature_slug}.md",
    "Projects/{slug}/RESEARCH-{feature_slug}.md",
    "Projects/{slug}/TASKS-{feature_slug}.md",
    "Projects/{slug}/REVIEW-{feature_slug}.md",
    "Projects/{slug}/SECURITY-{feature_slug}.md",
    "Projects/{slug}/SUMMARY-{feature_slug}.md",
    "Projects/{slug}/DEVILS-ADVOCATE-{feature_slug}.md",
    # Free-form docs subfolder
    "Projects/{slug}/docs/*.md",
    # Cross-project memory
    "Projects/PIPELINE_INDEX.md",
    # Vault root
    "Freya - Mistake Log.md",
    "LOGS.md",
]

FREYA_APPEND_ONLY_PATTERNS: Final[list[str]] = [
    "Freya - Mistake Log.md",
    "LOGS.md",
    "Projects/*/LOGS.md",
    "Projects/*/BUILD_LOG.md",
]

FREYA_PROTECTED_MEMORY_PATHS: Final[list[str]] = [
    "Projects/PIPELINE_INDEX.md",
]

# Aliases preserved so external code/tests that import these still work; new code
# should use the workflow-aware getters.
WRITE_PATTERNS = FREYA_WRITE_PATTERNS
APPEND_ONLY_PATTERNS = FREYA_APPEND_ONLY_PATTERNS
PROTECTED_MEMORY_PATHS = FREYA_PROTECTED_MEMORY_PATHS

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


def resolve_write_patterns(
    workflow: str, override: list[str] | None = None
) -> list[str]:
    """Return active write patterns for the given workflow."""

    if override is not None:
        return override
    if workflow == WORKFLOW_FREYA:
        return FREYA_WRITE_PATTERNS
    return GENERIC_WRITE_PATTERNS


def resolve_append_only_patterns(
    workflow: str, override: list[str] | None = None
) -> list[str]:
    """Return active append-only patterns for the given workflow."""

    if override is not None:
        return override
    if workflow == WORKFLOW_FREYA:
        return FREYA_APPEND_ONLY_PATTERNS
    return GENERIC_APPEND_ONLY_PATTERNS


def resolve_protected_memory_paths(workflow: str) -> list[str]:
    """Return active protected memory paths for the given workflow."""

    if workflow == WORKFLOW_FREYA:
        return FREYA_PROTECTED_MEMORY_PATHS
    return GENERIC_PROTECTED_MEMORY_PATHS


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime configuration. Built once at startup, then frozen."""

    vault_path: Path
    api_key: str
    base_url: str
    log_level: str
    read_only: bool
    allow_move: bool
    workflow: str = WORKFLOW_FREYA
    write_patterns: tuple[str, ...] = field(
        default_factory=lambda: tuple(FREYA_WRITE_PATTERNS)
    )
    append_only_patterns: tuple[str, ...] = field(
        default_factory=lambda: tuple(FREYA_APPEND_ONLY_PATTERNS)
    )
    protected_memory_paths: tuple[str, ...] = field(
        default_factory=lambda: tuple(FREYA_PROTECTED_MEMORY_PATHS)
    )


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


def _parse_pattern_list(value: str | None) -> list[str] | None:
    """Parse a comma-separated pattern list."""

    if not value or not value.strip():
        return None
    return [pattern.strip() for pattern in value.split(",") if pattern.strip()]


def load_config(
    *,
    env_file: Path | None = None,
    read_only: bool = False,
    allow_move: bool = False,
    workflow: str | None = None,
) -> Config:
    """Load and validate runtime configuration."""

    values = _load_env_values(env_file)
    vault_path = _validate_vault_path(values.get("OBSIDIAN_VAULT_PATH"))
    api_key = _validate_api_key(values.get("OBSIDIAN_API_KEY"))
    base_url = _validate_base_url(values.get("OBSIDIAN_BASE_URL"))
    log_level = (values.get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()

    resolved_workflow = (
        workflow or values.get("OBSIDIAN_WORKFLOW", DEFAULT_WORKFLOW)
    ).lower()
    if resolved_workflow not in SUPPORTED_WORKFLOWS:
        raise ConfigError(
            f"Unsupported workflow '{resolved_workflow}'. Use 'generic' or 'freya'."
        )

    write_patterns_override = _parse_pattern_list(values.get("OBSIDIAN_WRITE_PATTERNS"))
    append_only_override = _parse_pattern_list(
        values.get("OBSIDIAN_APPEND_ONLY_PATTERNS")
    )
    write_patterns = tuple(
        resolve_write_patterns(resolved_workflow, write_patterns_override)
    )
    append_only_patterns = tuple(
        resolve_append_only_patterns(resolved_workflow, append_only_override)
    )
    protected_memory_paths = tuple(resolve_protected_memory_paths(resolved_workflow))

    return Config(
        vault_path=vault_path,
        api_key=api_key,
        base_url=base_url,
        log_level=log_level,
        read_only=READ_ONLY_MODE or read_only,
        allow_move=allow_move,
        workflow=resolved_workflow,
        write_patterns=write_patterns,
        append_only_patterns=append_only_patterns,
        protected_memory_paths=protected_memory_paths,
    )
