from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import (
    HIDDEN_FILE_PREFIX,
    MAX_SEARCH_QUERY_CHARS,
    MAX_SEARCH_RESULTS,
    MAX_SEARCH_SNIPPET_CHARS,
    PIPELINE_INDEX_PATH,
    RESERVED_SEGMENTS,
    WORKFLOW_FREYA,
    Config,
)
from ..errors import ErrorCode, MCPError, from_exception, success_envelope
from ..locks import LockRegistry
from ..obsidian_client import ObsidianClient
from ..safety import validate_slug

FILE_MAPPING: dict[str, str] = {
    "project": "PROJECT.md",
    "summary": "SUMMARY.md",
    "logs": "LOGS.md",
    "prd": "PRD.md",
    "design": "DESIGN.md",
    "research": "RESEARCH.md",
    "premortem": "PREMORTEM.md",
}
PIPELINE_INDEX_SLUG = "_pipeline_index"
PROJECTS_PREFIX = "Projects/"
MIN_PROJECT_PATH_PARTS = 3


@dataclass(frozen=True, slots=True)
class ToolContext:
    client: ObsidianClient
    config: Config
    locks: LockRegistry


def _has_hidden_segment(path: str) -> bool:
    return any(part.startswith(HIDDEN_FILE_PREFIX) for part in Path(path).parts)


def _project_slug_for_path(path: str) -> str | None:
    if path == PIPELINE_INDEX_PATH:
        return PIPELINE_INDEX_SLUG

    parts = Path(path).parts
    if len(parts) < MIN_PROJECT_PATH_PARTS or parts[0] != "Projects":
        return None

    slug = parts[1]
    if slug in RESERVED_SEGMENTS:
        return None

    try:
        validate_slug(slug)
    except MCPError:
        return None

    return slug


def _snippet_from_hit(hit: dict[str, Any]) -> str:
    snippet = hit.get("snippet") or hit.get("match") or hit.get("context") or ""
    if not isinstance(snippet, str):
        return ""
    return snippet[:MAX_SEARCH_SNIPPET_CHARS]


async def get_pipeline_index(ctx: ToolContext) -> dict[str, Any]:
    if ctx.config.workflow != WORKFLOW_FREYA:
        return from_exception(
            MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Pipeline index is a Freya-workflow feature. "
                "Run server with --workflow freya to enable.",
                {"workflow": ctx.config.workflow},
            )
        )

    try:
        content, _metadata = await ctx.client.get_file(PIPELINE_INDEX_PATH)
        return success_envelope({"content": content, "exists": True})
    except MCPError as exc:
        if exc.code == ErrorCode.PATH_NOT_FOUND:
            return success_envelope({"content": "", "exists": False})
        return from_exception(exc)


async def search_projects(
    ctx: ToolContext,
    *,
    query: str,
    max_results: int = 30,
) -> dict[str, Any]:
    if ctx.config.workflow != WORKFLOW_FREYA:
        return from_exception(
            MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Project search is a Freya-workflow feature. "
                "Run server with --workflow freya to enable.",
                {"workflow": ctx.config.workflow},
            )
        )

    if not query.strip():
        return from_exception(
            MCPError(ErrorCode.VALIDATION_ERROR, "Query must not be empty")
        )
    if len(query) > MAX_SEARCH_QUERY_CHARS:
        return from_exception(
            MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Query exceeds maximum length",
                {"max_query_chars": MAX_SEARCH_QUERY_CHARS},
            )
        )

    capped_results = min(max_results, MAX_SEARCH_RESULTS)

    try:
        hits = await ctx.client.search(query)
    except MCPError as exc:
        return from_exception(exc)

    normalized_hits: list[dict[str, Any]] = []
    lowered_query = query.casefold()

    for hit in hits:
        path = hit.get("path") or hit.get("filename") or hit.get("name")
        if not isinstance(path, str) or not path.startswith(PROJECTS_PREFIX):
            continue
        if _has_hidden_segment(path):
            continue

        project_slug = _project_slug_for_path(path)
        if project_slug is None:
            continue

        basename = Path(path).name.casefold()
        match_type = "filename" if lowered_query in basename else "content"
        normalized_hits.append(
            {
                "project_slug": project_slug,
                "path": path,
                "snippet": _snippet_from_hit(hit),
                "match_type": match_type,
            }
        )

    truncated = len(normalized_hits) > capped_results
    return success_envelope(
        {"hits": normalized_hits[:capped_results], "truncated": truncated}
    )


async def bootstrap_project(
    ctx: ToolContext,
    *,
    slug: str,
    files: dict[str, str] | None = None,
) -> dict[str, Any]:
    if ctx.config.workflow != WORKFLOW_FREYA:
        return from_exception(
            MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Project bootstrap is a Freya-workflow feature. "
                "Run server with --workflow freya to enable.",
                {"workflow": ctx.config.workflow},
            )
        )

    if ctx.config.read_only:
        return from_exception(
            MCPError(
                ErrorCode.READ_ONLY_MODE_ENABLED,
                "Read-only mode is enabled",
            )
        )

    try:
        validate_slug(slug)
        target_dir = ctx.config.vault_path / "Projects" / slug

        if target_dir.exists():
            raise MCPError(
                ErrorCode.PROJECT_ALREADY_EXISTS,
                "Project already exists",
                {"slug": slug},
            )

        remote_project_path = f"Projects/{slug}/PROJECT.md"
        stat_result = await ctx.client.stat(remote_project_path)
        if stat_result.get("exists"):
            raise MCPError(
                ErrorCode.PROJECT_ALREADY_EXISTS,
                "Project already exists",
                {"slug": slug},
            )

        requested_files = files or {}
        unknown_keys = sorted(set(requested_files) - set(FILE_MAPPING))
        if unknown_keys:
            raise MCPError(
                ErrorCode.VALIDATION_ERROR,
                "Unknown bootstrap file keys",
                {"unknown_keys": unknown_keys},
            )

        target_dir.mkdir(parents=True, exist_ok=False)

        created_files: list[str] = []
        for key, canonical_filename in FILE_MAPPING.items():
            if key not in requested_files:
                continue

            vault_relative = f"Projects/{slug}/{canonical_filename}"
            await ctx.client.put_file(vault_relative, requested_files[key])
            verification = await ctx.client.stat(vault_relative)
            if not verification.get("exists"):
                raise MCPError(
                    ErrorCode.WRITE_VERIFICATION_FAILED,
                    "Post-write verification failed",
                    {"path": vault_relative},
                )
            created_files.append(vault_relative)

        return success_envelope(
            {
                "created_directory": f"Projects/{slug}/",
                "created_files": created_files,
            }
        )
    except MCPError as exc:
        return from_exception(exc)
