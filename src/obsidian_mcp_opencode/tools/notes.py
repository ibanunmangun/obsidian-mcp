from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import (
    HIDDEN_FILE_PREFIX,
    MAX_SEARCH_QUERY_CHARS,
    MAX_SEARCH_RESULTS,
    MAX_SEARCH_SNIPPET_CHARS,
    PATH_ECHO_MAX_CHARS,
    Config,
)
from ..errors import (
    ErrorCode,
    MCPError,
    cap_path_echo,
    error_envelope,
    from_exception,
    redact_token,
    success_envelope,
)
from ..locks import LockRegistry
from ..obsidian_client import ObsidianClient
from ..safety import (
    assert_writable,
    is_append_only,
    is_mistake_log,
    is_protected_memory,
    match_write_pattern,
    validate_vault_path,
)

LOGGER = logging.getLogger(__name__)
MAX_LIST_RECURSION_DEPTH = 8


@dataclass(frozen=True, slots=True)
class ToolContext:
    client: ObsidianClient
    config: Config
    locks: LockRegistry


def _internal_error(operation: str) -> dict[str, Any]:
    return error_envelope(
        ErrorCode.INTERNAL_ERROR,
        f"{operation} failed unexpectedly",
        {"operation": operation},
    )


def _redacted_exception_envelope(config: Config, exc: MCPError) -> dict[str, Any]:
    message = redact_token(exc.message, config.api_key)
    details = {
        key: redact_token(str(value), config.api_key) if isinstance(value, str) else value
        for key, value in exc.details.items()
    }
    return error_envelope(exc.code, message, details)


def _ensure_writes_enabled(config: Config) -> None:
    if config.read_only:
        raise MCPError(
            ErrorCode.READ_ONLY_MODE_ENABLED,
            "Write operations are disabled in read-only mode",
        )


def _ensure_parent_directory_exists(resolved_path: Path, vault_relative_path: str) -> None:
    parent = resolved_path.parent
    if not parent.exists() or not parent.is_dir():
        raise MCPError(
            ErrorCode.PARENT_DIRECTORY_MISSING,
            "Parent directory does not exist",
            {"input_path": cap_path_echo(vault_relative_path, PATH_ECHO_MAX_CHARS)},
        )


def _size_from_metadata(content: str, metadata: dict[str, Any]) -> int:
    size = metadata.get("size")
    if isinstance(size, int):
        return size
    return len(content.encode("utf-8"))


def _canonical_relative_path(config: Config, candidate: str) -> tuple[Path, str]:
    resolved_path = validate_vault_path(config.vault_path, candidate)
    canonical_path = str(resolved_path.relative_to(config.vault_path)).replace(os.sep, "/")
    return resolved_path, canonical_path


def _normalize_listing_path(path: str, entry_type: str) -> str:
    normalized = path.rstrip("/")
    if entry_type == "folder":
        return f"{normalized}/" if normalized else "/"
    return normalized


async def read_note(ctx: ToolContext, *, path: str) -> dict[str, Any]:
    try:
        validate_vault_path(ctx.config.vault_path, path)
        content, metadata = await ctx.client.get_file(path)
        return success_envelope(
            {
                "content": content,
                "size": _size_from_metadata(content, metadata),
                "mtime": metadata.get("mtime"),
            }
        )
    except MCPError as exc:
        return from_exception(exc)
    except Exception:
        return _internal_error("read_note")


async def write_note(
    ctx: ToolContext,
    *,
    path: str,
    content: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    try:
        _ensure_writes_enabled(ctx.config)
        resolved_path = validate_vault_path(ctx.config.vault_path, path)
        assert_writable(path, allow_overwrite=overwrite, is_append=False)
        _ensure_parent_directory_exists(resolved_path, path)

        stat_before = await ctx.client.stat(path)
        existed_before = bool(stat_before.get("exists"))

        if existed_before and not overwrite:
            raise MCPError(
                ErrorCode.FILE_EXISTS,
                "File already exists; set overwrite=true to replace it",
                {"input_path": cap_path_echo(path, PATH_ECHO_MAX_CHARS)},
            )

        if existed_before and overwrite:
            previous_content, previous_metadata = await ctx.client.get_file(path)
            previous_size = _size_from_metadata(previous_content, previous_metadata)
            previous_sha256 = hashlib.sha256(previous_content.encode("utf-8")).hexdigest()
            LOGGER.info(
                "Overwriting note path=%s size=%s sha256=%s",
                cap_path_echo(path, PATH_ECHO_MAX_CHARS),
                previous_size,
                previous_sha256,
            )

        await ctx.client.put_file(path, content)

        validate_vault_path(ctx.config.vault_path, path)
        stat_after = await ctx.client.stat(path)
        if not stat_after.get("exists"):
            raise MCPError(
                ErrorCode.WRITE_VERIFICATION_FAILED,
                "Write verification failed after write",
                {"input_path": cap_path_echo(path, PATH_ECHO_MAX_CHARS)},
            )

        size_after = stat_after.get("size")
        if not isinstance(size_after, int):
            size_after = len(content.encode("utf-8"))

        return success_envelope(
            {
                "created": not existed_before,
                "overwritten": existed_before,
                "size": size_after,
            }
        )
    except MCPError as exc:
        return from_exception(exc)
    except Exception:
        return _internal_error("write_note")


async def append_note(ctx: ToolContext, *, path: str, content: str) -> dict[str, Any]:
    try:
        _ensure_writes_enabled(ctx.config)
        resolved_path = validate_vault_path(ctx.config.vault_path, path)
        if is_mistake_log(path):
            raise MCPError(
                ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL,
                "Use the specialized mistake log tool for this path",
                {"input_path": cap_path_echo(path, PATH_ECHO_MAX_CHARS)},
            )
        assert_writable(path, allow_overwrite=False, is_append=True)
        _ensure_parent_directory_exists(resolved_path, path)

        append_only = is_append_only(path)
        lock = ctx.locks.lock_for(path) if append_only else None

        async def _do_append() -> dict[str, Any]:
            stat_before = await ctx.client.stat(path)
            existed_before = bool(stat_before.get("exists"))
            size_before_raw = stat_before.get("size")
            size_before = size_before_raw if isinstance(size_before_raw, int) else 0

            await ctx.client.append_file(path, content)

            stat_after = await ctx.client.stat(path)
            if not stat_after.get("exists"):
                raise MCPError(
                    ErrorCode.APPEND_VERIFICATION_FAILED,
                    "Append verification failed after append",
                    {"input_path": cap_path_echo(path, PATH_ECHO_MAX_CHARS)},
                )

            size_after_raw = stat_after.get("size")
            size_after = (
                size_after_raw
                if isinstance(size_after_raw, int)
                else size_before + len(content.encode("utf-8"))
            )

            if append_only:
                full_content, _ = await ctx.client.get_file(path)
                appended_count = full_content.count(content)
                if not full_content.endswith(content) or appended_count != 1:
                    raise MCPError(
                        ErrorCode.APPEND_VERIFICATION_FAILED,
                        "Append verification failed: file tail did not match appended content",
                        {
                            "input_path": cap_path_echo(path, PATH_ECHO_MAX_CHARS),
                            "appended_count": appended_count,
                        },
                    )

            return success_envelope(
                {
                    "created": not existed_before,
                    "size_before": size_before,
                    "size_after": size_after,
                }
            )

        if lock is None:
            return await _do_append()

        async with lock:
            return await _do_append()
    except MCPError as exc:
        return from_exception(exc)
    except Exception:
        return _internal_error("append_note")


async def list_notes(
    ctx: ToolContext,
    *,
    path: str = "",
    recursive: bool = False,
) -> dict[str, Any]:
    try:
        if path != "":
            validate_vault_path(ctx.config.vault_path, path)

        entries: list[dict[str, Any]] = []

        async def _walk(current_path: str, depth: int) -> None:
            raw_entries = await ctx.client.list_directory(current_path)
            for entry in raw_entries:
                name = str(entry.get("name") or "")
                if name.startswith(HIDDEN_FILE_PREFIX):
                    continue

                entry_path = str(entry.get("path") or name).rstrip("/")
                entry_type = "folder" if bool(entry.get("is_dir")) else "file"
                entries.append(
                    {
                        "path": _normalize_listing_path(entry_path, entry_type),
                        "type": entry_type,
                        "size": entry.get("size"),
                    }
                )

                if recursive and entry_type == "folder" and depth < MAX_LIST_RECURSION_DEPTH:
                    await _walk(entry_path, depth + 1)

        await _walk(path, 1)
        return success_envelope({"entries": entries})
    except MCPError as exc:
        return from_exception(exc)
    except Exception:
        return _internal_error("list_notes")


async def search_vault(
    ctx: ToolContext,
    *,
    query: str,
    path_prefix: str = "",
    max_results: int = 50,
) -> dict[str, Any]:
    try:
        normalized_query = query.strip()
        if not normalized_query:
            raise MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Search query must not be empty",
            )
        if len(normalized_query) > MAX_SEARCH_QUERY_CHARS:
            raise MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Search query exceeds maximum length",
                {"max_chars": MAX_SEARCH_QUERY_CHARS},
            )

        capped_max_results = min(max_results, MAX_SEARCH_RESULTS)

        if path_prefix:
            validate_vault_path(ctx.config.vault_path, path_prefix)

        raw_hits = await ctx.client.search(normalized_query)
        query_lower = normalized_query.lower()
        filtered_hits: list[dict[str, Any]] = []

        for hit in raw_hits:
            hit_path = hit.get("path") or hit.get("filename") or hit.get("name")
            if not isinstance(hit_path, str) or not hit_path:
                continue
            if path_prefix and not hit_path.startswith(path_prefix):
                continue

            try:
                validate_vault_path(ctx.config.vault_path, hit_path)
            except MCPError:
                continue

            filename = Path(hit_path).name.lower()
            is_filename_match = query_lower in filename
            snippet = hit.get("snippet") or hit.get("match") or ""
            if not isinstance(snippet, str):
                snippet = str(snippet)
            snippet = snippet[:MAX_SEARCH_SNIPPET_CHARS]

            line_value = hit.get("line")
            line_number = line_value if isinstance(line_value, int) else None
            filtered_hits.append(
                {
                    "path": hit_path,
                    "snippet": snippet,
                    "line": None if is_filename_match else line_number,
                    "match_type": "filename" if is_filename_match else "content",
                }
            )

        truncated = len(filtered_hits) > capped_max_results
        return success_envelope(
            {
                "hits": filtered_hits[:capped_max_results],
                "truncated": truncated,
            }
        )
    except MCPError as exc:
        return from_exception(exc)
    except Exception:
        return _internal_error("search_vault")


async def move_note(  # noqa: PLR0911, PLR0912
    ctx: ToolContext, *, source_path: str, destination_path: str
) -> dict[str, Any]:
    try:
        _ensure_writes_enabled(ctx.config)

        _, canonical_source = _canonical_relative_path(ctx.config, source_path)
        destination_resolved, canonical_destination = _canonical_relative_path(
            ctx.config, destination_path
        )

        if canonical_source == canonical_destination:
            raise MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Source and destination must differ",
                {
                    "reason": "source_and_destination_identical",
                    "input_path": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS),
                },
            )

        if is_mistake_log(canonical_source):
            raise MCPError(
                ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL,
                "Use the specialized mistake log tool for this path",
                {"input_path": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS)},
            )
        if is_append_only(canonical_source):
            raise MCPError(
                ErrorCode.PATH_FORBIDDEN_APPEND_ONLY,
                "Append-only files cannot be moved",
                {"input_path": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS)},
            )
        if is_protected_memory(canonical_source):
            raise MCPError(
                ErrorCode.PATH_FORBIDDEN,
                "Protected memory files cannot be moved",
                {"input_path": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS)},
            )

        if not match_write_pattern(canonical_destination):
            raise MCPError(
                ErrorCode.PATH_FORBIDDEN,
                "Path is not on the write allowlist",
                {"input_path": cap_path_echo(canonical_destination, PATH_ECHO_MAX_CHARS)},
            )
        if is_mistake_log(canonical_destination):
            raise MCPError(
                ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL,
                "Use the specialized mistake log tool for this path",
                {"input_path": cap_path_echo(canonical_destination, PATH_ECHO_MAX_CHARS)},
            )
        if is_append_only(canonical_destination):
            raise MCPError(
                ErrorCode.PATH_FORBIDDEN_APPEND_ONLY,
                "Append-only files cannot be moved",
                {"input_path": cap_path_echo(canonical_destination, PATH_ECHO_MAX_CHARS)},
            )
        _ensure_parent_directory_exists(destination_resolved, canonical_destination)

        destination_stat = await ctx.client.stat(canonical_destination)
        if destination_stat.get("exists"):
            raise MCPError(
                ErrorCode.FILE_EXISTS,
                "Destination file already exists",
                {"input_path": cap_path_echo(canonical_destination, PATH_ECHO_MAX_CHARS)},
            )

        source_stat = await ctx.client.stat(canonical_source)
        if not source_stat.get("exists"):
            raise MCPError(
                ErrorCode.PATH_NOT_FOUND,
                "Vault path not found",
                {"input_path": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS)},
            )

        ordered_paths = sorted({canonical_source, canonical_destination})
        async with ctx.locks.lock_for(ordered_paths[0]):
            async with ctx.locks.lock_for(ordered_paths[1]):
                source_stat = await ctx.client.stat(canonical_source)
                if not source_stat.get("exists"):
                    return error_envelope(
                        ErrorCode.PATH_NOT_FOUND,
                        "Vault path not found",
                        {"input_path": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS)},
                    )

                destination_stat = await ctx.client.stat(canonical_destination)
                if destination_stat.get("exists"):
                    return error_envelope(
                        ErrorCode.FILE_EXISTS,
                        "Destination file already exists",
                        {"input_path": cap_path_echo(canonical_destination, PATH_ECHO_MAX_CHARS)},
                    )

                content, _ = await ctx.client.get_file(canonical_source)
                await ctx.client.put_file(canonical_destination, content)

                try:
                    written_content, _ = await ctx.client.get_file(canonical_destination)
                except MCPError as exc:
                    raise MCPError(
                        ErrorCode.WRITE_VERIFICATION_FAILED,
                        "Destination read-back failed",
                        {
                            "source": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS),
                            "destination": cap_path_echo(
                                canonical_destination,
                                PATH_ECHO_MAX_CHARS,
                            ),
                            "underlying_error": exc.code,
                        },
                    ) from exc

                if written_content != content:
                    raise MCPError(
                        ErrorCode.WRITE_VERIFICATION_FAILED,
                        "Destination content does not match source",
                        {
                            "source": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS),
                            "destination": cap_path_echo(
                                canonical_destination,
                                PATH_ECHO_MAX_CHARS,
                            ),
                            "expected_size": len(content),
                            "actual_size": len(written_content),
                        },
                    )

                try:
                    await ctx.client.delete_file(canonical_source)
                except MCPError as exc:
                    return error_envelope(
                        ErrorCode.MOVE_PARTIAL,
                        "Move partially completed: destination created but source deletion failed",
                        {
                            "stage": "delete_source",
                            "source": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS),
                            "destination": cap_path_echo(
                                canonical_destination,
                                PATH_ECHO_MAX_CHARS,
                            ),
                            "destination_created": True,
                            "destination_exists_after_write": True,
                            "source_delete_attempted": True,
                            "source_exists_after_delete": True,
                            "manual_cleanup_required": True,
                            "underlying_error": exc.code,
                        },
                    )

                try:
                    after_stat = await ctx.client.stat(canonical_source)
                except MCPError:
                    return error_envelope(
                        ErrorCode.MOVE_PARTIAL,
                        "Move partially completed: cannot verify source deletion",
                        {
                            "stage": "verify_source_deleted",
                            "source": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS),
                            "destination": cap_path_echo(
                                canonical_destination,
                                PATH_ECHO_MAX_CHARS,
                            ),
                            "destination_created": True,
                            "destination_exists_after_write": True,
                            "source_delete_attempted": True,
                            "source_exists_after_delete": "unknown",
                            "manual_cleanup_required": True,
                        },
                    )

                if after_stat.get("exists"):
                    return error_envelope(
                        ErrorCode.MOVE_PARTIAL,
                        "Move partially completed: source still exists after delete",
                        {
                            "stage": "verify_source_deleted",
                            "source": cap_path_echo(canonical_source, PATH_ECHO_MAX_CHARS),
                            "destination": cap_path_echo(
                                canonical_destination,
                                PATH_ECHO_MAX_CHARS,
                            ),
                            "destination_created": True,
                            "destination_exists_after_write": True,
                            "source_delete_attempted": True,
                            "source_exists_after_delete": True,
                            "manual_cleanup_required": True,
                        },
                    )

        return success_envelope(
            {
                "moved": True,
                "source": canonical_source,
                "destination": canonical_destination,
            }
        )
    except MCPError as exc:
        return _redacted_exception_envelope(ctx.config, exc)
    except Exception:
        return _internal_error("move_note")
