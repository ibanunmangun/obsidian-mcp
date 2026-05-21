from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .config import (
    APPEND_ONLY_PATTERNS,
    HIDDEN_FILE_PREFIX,
    MISTAKE_LOG_FILENAME,
    PROTECTED_MEMORY_PATHS,
    RESERVED_SEGMENTS,
    SLUG_REGEX,
    WRITE_PATTERNS,
)
from .errors import ErrorCode, MCPError, cap_path_echo

SLUG_BODY = SLUG_REGEX.removeprefix("^").removesuffix("$")


def _path_error(code: str, message: str, candidate: str) -> MCPError:
    return MCPError(code, message, {"input_path": cap_path_echo(candidate)})


def validate_vault_path(vault_root: Path, candidate: str) -> Path:
    """Validate a vault-relative candidate path."""

    if candidate == "":
        raise _path_error(ErrorCode.PATH_FORBIDDEN, "Path must not be empty", candidate)
    if candidate.startswith("/"):
        raise _path_error(ErrorCode.PATH_FORBIDDEN, "Absolute paths are forbidden", candidate)
    if "\\" in candidate:
        raise _path_error(
            ErrorCode.PATH_FORBIDDEN,
            "Backslashes are forbidden in vault paths",
            candidate,
        )

    parts = Path(candidate).parts
    if any(part == ".." for part in parts):
        raise _path_error(ErrorCode.PATH_FORBIDDEN, "Parent traversal is forbidden", candidate)
    if any(part.startswith(HIDDEN_FILE_PREFIX) for part in parts):
        raise _path_error(
            ErrorCode.PATH_FORBIDDEN_HIDDEN_FILE,
            "Hidden files are forbidden",
            candidate,
        )

    current = vault_root
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise _path_error(
                ErrorCode.PATH_FORBIDDEN_SYMLINK,
                "Symlinked paths are forbidden",
                candidate,
            )

    try:
        resolved_root = vault_root.resolve(strict=True)
        resolved_path = (vault_root / candidate).resolve(strict=False)
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise _path_error(
            ErrorCode.PATH_FORBIDDEN,
            "Path escapes the vault root",
            candidate,
        ) from exc

    return resolved_path


def validate_slug(slug: str) -> None:
    """Validate a project slug against the configured regex and reserved words."""

    if re.fullmatch(SLUG_REGEX, slug) and slug not in RESERVED_SEGMENTS:
        return
    raise MCPError(
        ErrorCode.SLUG_INVALID,
        "Project slug is invalid",
        {"slug": slug},
    )


def _pattern_to_regex(pattern: str) -> str:
    escaped = re.escape(pattern)
    escaped = escaped.replace(re.escape("{slug}"), f"({SLUG_BODY})")
    escaped = escaped.replace(re.escape("{feature_slug}"), f"({SLUG_BODY})")
    escaped = escaped.replace(re.escape("*"), r"[^/]+")
    return f"^{escaped}$"


def match_write_pattern(vault_relative_path: str) -> bool:
    """Match a vault-relative path against the explicit write allowlist."""

    for pattern in WRITE_PATTERNS:
        if re.fullmatch(_pattern_to_regex(pattern), vault_relative_path):
            parts = Path(vault_relative_path).parts
            for part in parts:
                if part in RESERVED_SEGMENTS:
                    return False
            return True
    return False


def is_append_only(vault_relative_path: str) -> bool:
    """Return True when the path is append-only."""

    return any(
        fnmatch.fnmatchcase(vault_relative_path, pattern) for pattern in APPEND_ONLY_PATTERNS
    )


def is_protected_memory(vault_relative_path: str) -> bool:
    """Return True when the path is a protected memory file."""

    return vault_relative_path in PROTECTED_MEMORY_PATHS


def is_mistake_log(vault_relative_path: str) -> bool:
    """Return True when the path is the mistake log."""

    return vault_relative_path == MISTAKE_LOG_FILENAME


def assert_writable(vault_relative_path: str, *, allow_overwrite: bool, is_append: bool) -> None:
    """Enforce write rules for generic write and append operations."""

    if is_mistake_log(vault_relative_path):
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL,
            "Use the specialized mistake log tool for this path",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
    if not match_write_pattern(vault_relative_path):
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN,
            "Path is not on the write allowlist",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
    if is_append_only(vault_relative_path) and not is_append:
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN_APPEND_ONLY,
            "Append-only files cannot be overwritten",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
    if is_protected_memory(vault_relative_path) and not is_append and allow_overwrite:
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN,
            "Protected memory files cannot be overwritten",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
