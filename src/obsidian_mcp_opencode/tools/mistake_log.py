from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from obsidian_mcp_opencode.config import MISTAKE_LOG_FILENAME, TIMEZONE, Config
from obsidian_mcp_opencode.errors import (
    ErrorCode,
    MCPError,
    error_envelope,
    from_exception,
    redact_token,
    success_envelope,
)
from obsidian_mcp_opencode.locks import LockRegistry
from obsidian_mcp_opencode.obsidian_client import ObsidianClient

HEADER_PATTERN = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] — (.+)$")
FIELD_MARKERS: tuple[tuple[str, str], ...] = (
    ("Context", "context"),
    ("Mistake", "mistake"),
    ("Root Cause", "root_cause"),
    ("Fix", "fix"),
    ("Lesson", "lesson"),
)
FIELD_PATTERN = re.compile(
    r"^\*\*(Context|Mistake|Root Cause|Fix|Lesson):\*\*\s?(.*)$"
)
HEADER_INJECTION_PATTERN = re.compile(r"^\s*## \[\d{4}-\d{2}-\d{2}\]", re.MULTILINE)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True, slots=True)
class ToolContext:
    client: ObsidianClient
    config: Config
    locks: LockRegistry


def _sanitize_value(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return redact_token(value, token)
    if isinstance(value, dict):
        return {key: _sanitize_value(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, token) for item in value]
    return value


def _sanitize_exception(exc: MCPError, token: str) -> MCPError:
    return MCPError(
        exc.code,
        redact_token(exc.message, token),
        _sanitize_value(exc.details, token),
    )


def _entry_blocks(body: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None

    for line in body.splitlines():
        if HEADER_PATTERN.match(line):
            if current is not None:
                blocks.append(current)
            current = [line]
            continue

        if current is not None:
            current.append(line)

    if current is not None:
        blocks.append(current)

    return blocks


def _parse_entry_block(lines: list[str]) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    header = lines[0]
    match = HEADER_PATTERN.match(header)
    if match is None:
        return None, None

    fields: dict[str, list[str]] = {key: [] for _, key in FIELD_MARKERS}
    current_field: str | None = None

    for line in lines[1:]:
        field_match = FIELD_PATTERN.match(line)
        if field_match is not None:
            marker_name = field_match.group(1)
            field_value = field_match.group(2)
            field_key = next(key for label, key in FIELD_MARKERS if label == marker_name)
            current_field = field_key
            fields[field_key].append(field_value)
            continue

        if current_field is not None:
            fields[current_field].append(line)

    for label, key in FIELD_MARKERS:
        value = "\n".join(fields[key]).strip()
        if not value:
            return None, {"header": header, "reason": f"missing {label} field"}
        fields[key] = [value]

    entry = {
        "date": match.group(1),
        "title": match.group(2).strip(),
        "context": fields["context"][0],
        "mistake": fields["mistake"][0],
        "root_cause": fields["root_cause"][0],
        "fix": fields["fix"][0],
        "lesson": fields["lesson"][0],
    }
    return entry, None


def _parse_mistake_log(body: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    entries: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    for block in _entry_blocks(body):
        entry, warning = _parse_entry_block(block)
        if entry is not None:
            entries.append(entry)
        elif warning is not None:
            warnings.append(warning)

    return entries, warnings


async def get_mistake_log(ctx: ToolContext) -> dict[str, Any]:
    try:
        body, _metadata = await ctx.client.get_file(MISTAKE_LOG_FILENAME)
    except MCPError as exc:
        safe_exc = _sanitize_exception(exc, ctx.config.api_key)
        if safe_exc.code == ErrorCode.PATH_NOT_FOUND:
            return error_envelope(
                ErrorCode.MISTAKE_LOG_NOT_FOUND,
                "Mistake log file was not found",
                {"path": MISTAKE_LOG_FILENAME},
            )
        return from_exception(safe_exc)

    entries, parse_warnings = _parse_mistake_log(body)
    return success_envelope(
        {"entries": entries, "parse_warnings": parse_warnings, "raw": body}
    )


async def append_mistake_log(
    ctx: ToolContext,
    *,
    title: str,
    context: str,
    mistake: str,
    root_cause: str,
    fix: str,
    lesson: str,
    date: str = "",
) -> dict[str, Any]:
    fields = {
        "title": title,
        "context": context,
        "mistake": mistake,
        "root_cause": root_cause,
        "fix": fix,
        "lesson": lesson,
    }

    error_result: dict[str, Any] | None = None

    if ctx.config.read_only:
        error_result = error_envelope(
            ErrorCode.READ_ONLY_MODE_ENABLED,
            "Read-only mode is enabled",
        )
    else:
        missing_fields = [name for name, value in fields.items() if not value.strip()]
        if missing_fields:
            error_result = error_envelope(
                ErrorCode.VALIDATION_ERROR,
                "Required mistake log fields must be non-empty",
                {"missing_fields": missing_fields},
            )
        elif date and DATE_PATTERN.fullmatch(date) is None:
            error_result = error_envelope(
                ErrorCode.VALIDATION_ERROR,
                "Date must use YYYY-MM-DD format",
                {"field": "date", "value": date},
            )
        else:
            if not date:
                date = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")

            if any(HEADER_INJECTION_PATTERN.search(value) for value in fields.values()):
                error_result = error_envelope(
                    ErrorCode.ENTRY_HEADER_INJECTION,
                    "Mistake log entry fields must not contain nested entry headers",
                )

    if error_result is not None:
        return error_result

    entry = (
        "\n"
        f"## [{date}] — {title}\n"
        f"**Context:** {context}\n"
        f"**Mistake:** {mistake}\n"
        f"**Root Cause:** {root_cause}\n"
        f"**Fix:** {fix}\n"
        f"**Lesson:** {lesson}\n"
    )

    lock = ctx.locks.lock_for(MISTAKE_LOG_FILENAME)
    async with lock:
        try:
            await ctx.client.append_file(MISTAKE_LOG_FILENAME, entry)
            body, _metadata = await ctx.client.get_file(MISTAKE_LOG_FILENAME)
        except MCPError as exc:
            return from_exception(_sanitize_exception(exc, ctx.config.api_key))

        if not body.endswith(entry) or body[-len(entry) :].count(entry) != 1:
            return error_envelope(
                ErrorCode.APPEND_VERIFICATION_FAILED,
                "Mistake log append verification failed",
                {"path": MISTAKE_LOG_FILENAME},
            )

        entries, _warnings = _parse_mistake_log(body)

    return success_envelope({"appended": True, "entry_count": len(entries)})
