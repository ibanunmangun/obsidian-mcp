from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from pathlib import Path

from .config import HIDDEN_FILE_PREFIX, MISTAKE_LOG_FILENAME, RESERVED_SEGMENTS, SLUG_REGEX
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
    escaped = escaped.replace(re.escape("**/"), r"(?:.+/)?")
    escaped = escaped.replace(re.escape("*"), r"[^/]+")
    return f"^{escaped}$"


def match_write_pattern(
    vault_relative_path: str,
    write_patterns: Iterable[str],
    *,
    enforce_reserved_segments: bool = True,
) -> bool:
    """Match a vault-relative path against an explicit write allowlist."""

    for pattern in write_patterns:
        if re.fullmatch(_pattern_to_regex(pattern), vault_relative_path):
            if enforce_reserved_segments:
                parts = Path(vault_relative_path).parts
                for part in parts:
                    if part in RESERVED_SEGMENTS:
                        return False
            return True
    return False


def is_append_only(vault_relative_path: str, append_only_patterns: Iterable[str]) -> bool:
    """Return True when the path is append-only."""

    return any(
        fnmatch.fnmatchcase(vault_relative_path, pattern) for pattern in append_only_patterns
    )


def is_protected_memory(vault_relative_path: str, protected_memory_paths: Iterable[str]) -> bool:
    """Return True when the path is a protected memory file."""

    return vault_relative_path in protected_memory_paths


def is_mistake_log(
    vault_relative_path: str, mistake_log_filename: str = MISTAKE_LOG_FILENAME
) -> bool:
    """Return True when the path is the mistake log."""

    return vault_relative_path == mistake_log_filename


def assert_writable(
    vault_relative_path: str,
    *,
    allow_overwrite: bool,
    is_append: bool,
    write_patterns: Iterable[str],
    append_only_patterns: Iterable[str],
    protected_memory_paths: Iterable[str],
    mistake_log_filename: str | None = None,
    enforce_reserved_segments: bool = True,
) -> None:
    """Enforce write rules for generic write and append operations."""

    if mistake_log_filename is not None and is_mistake_log(
        vault_relative_path, mistake_log_filename
    ):
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL,
            "Use the specialized mistake log tool for this path",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
    if not match_write_pattern(
        vault_relative_path,
        write_patterns,
        enforce_reserved_segments=enforce_reserved_segments,
    ):
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN,
            "Path is not on the write allowlist",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
    if is_append_only(vault_relative_path, append_only_patterns) and not is_append:
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN_APPEND_ONLY,
            "Append-only files cannot be overwritten",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
    if (
        is_protected_memory(vault_relative_path, protected_memory_paths)
        and not is_append
        and allow_overwrite
    ):
        raise MCPError(
            ErrorCode.PATH_FORBIDDEN,
            "Protected memory files cannot be overwritten",
            {"input_path": cap_path_echo(vault_relative_path)},
        )
