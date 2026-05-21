from __future__ import annotations

import re
from typing import Any

TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+=_-]{40,}(?![A-Za-z0-9+/=_-])")


class ErrorCode:
    PATH_NOT_FOUND = "path_not_found"
    PATH_FORBIDDEN = "path_forbidden"
    PATH_FORBIDDEN_SYMLINK = "path_forbidden_symlink"
    PATH_FORBIDDEN_HIDDEN_FILE = "path_forbidden_hidden_file"
    PATH_FORBIDDEN_USE_SPECIALIZED_TOOL = "path_forbidden_use_specialized_tool"
    PATH_FORBIDDEN_APPEND_ONLY = "path_forbidden_append_only"
    PARENT_DIRECTORY_MISSING = "parent_directory_missing"
    FILE_EXISTS = "file_exists"
    SLUG_INVALID = "slug_invalid"
    PROJECT_ALREADY_EXISTS = "project_already_exists"
    VALIDATION_ERROR = "validation_error"
    ENTRY_HEADER_INJECTION = "entry_header_injection"
    MISTAKE_LOG_NOT_FOUND = "mistake_log_not_found"
    APPEND_VERIFICATION_FAILED = "append_verification_failed"
    WRITE_VERIFICATION_FAILED = "write_verification_failed"
    MOVE_PARTIAL = "move_partial"
    READ_ONLY_MODE_ENABLED = "read_only_mode_enabled"
    API_UNREACHABLE = "api_unreachable"
    API_UNAUTHORIZED = "api_unauthorized"
    INTERNAL_ERROR = "internal_error"
    CONFIG_ERROR = "config_error"


class MCPError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details.copy() if details is not None else {}


class ConfigError(MCPError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.CONFIG_ERROR, message, details)


def success_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Returns {"ok": True, "data": data}."""

    return {"ok": True, "data": data}


def error_envelope(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns a stable error envelope."""

    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "details": details.copy() if details is not None else {},
        },
    }


def from_exception(exc: MCPError) -> dict[str, Any]:
    """Build error_envelope from an MCPError."""

    return error_envelope(exc.code, exc.message, exc.details)


def redact_token(text: str, token: str) -> str:
    """Replace all occurrences of token in text with [REDACTED]."""

    if not token:
        return text
    return text.replace(token, "[REDACTED]")


def redact_token_patterns(text: str) -> str:
    """Redact long token-like substrings while leaving normal paths intact."""

    return TOKEN_PATTERN.sub("[redacted]", text)


def cap_path_echo(path: str, max_chars: int = 200) -> str:
    """Truncate echoed paths and redact token-like substrings."""

    truncated = path
    if len(truncated) > max_chars:
        truncated = f"{truncated[: max_chars - 3]}..."
    return redact_token_patterns(truncated)
