from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp import types
from mcp.server import InitializationOptions, NotificationOptions, Server
from mcp.server.stdio import stdio_server

from . import __version__
from .config import Config
from .errors import (
    ErrorCode,
    MCPError,
    error_envelope,
    from_exception,
    redact_token,
)
from .locks import LockRegistry
from .obsidian_client import ObsidianClient
from .tools import mistake_log, notes, projects

logger = logging.getLogger(__name__)

ENVELOPE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok"],
    "properties": {
        "ok": {"type": "boolean"},
        "data": {"type": "object"},
        "error": {
            "type": "object",
            "required": ["code", "message", "details"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
            },
            "additionalProperties": True,
        },
    },
    "additionalProperties": True,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "read_note": (
        "Read a vault-relative note and return its content, size, and "
        "modification time."
    ),
    "write_note": (
        "Create a new note or replace an existing one. Refuses to clobber "
        "unless overwrite=true."
    ),
    "append_note": (
        "Append content to a note. Creates the file if missing (parent "
        "directory must exist)."
    ),
    "list_notes": "List notes and folders under a vault path. Hidden entries are filtered out.",
    "search_vault": (
        "Search the vault by case-insensitive substring across filenames and "
        "content."
    ),
    "get_mistake_log": (
        "Read the Freya mistake log and return parsed entries plus parse "
        "warnings."
    ),
    "append_mistake_log": (
        "Append a new mistake log entry in canonical format with the 5 "
        "required fields."
    ),
    "get_pipeline_index": (
        "Read the cross-project pipeline index. Returns exists=false if the "
        "file is missing."
    ),
    "search_projects": (
        "Search inside Projects/**/*.md only. Returns hits with inferred "
        "project slug."
    ),
    "bootstrap_project": (
        "Create a new Projects/{slug}/ directory and initial files. The only "
        "tool that creates project directories."
    ),
}


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    is_write: bool


TOOL_REGISTRY: list[ToolDescriptor]


def build_tool_registry() -> list[ToolDescriptor]:
    """Build the static descriptor list. Pure function — no I/O."""

    return [
        ToolDescriptor(
            name="read_note",
            description=TOOL_DESCRIPTIONS["read_note"],
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Vault-relative path."}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=notes.read_note,
            is_write=False,
        ),
        ToolDescriptor(
            name="write_note",
            description=TOOL_DESCRIPTIONS["write_note"],
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean", "default": False},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            handler=notes.write_note,
            is_write=True,
        ),
        ToolDescriptor(
            name="append_note",
            description=TOOL_DESCRIPTIONS["append_note"],
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            handler=notes.append_note,
            is_write=True,
        ),
        ToolDescriptor(
            name="list_notes",
            description=TOOL_DESCRIPTIONS["list_notes"],
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": ""},
                    "recursive": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            handler=notes.list_notes,
            is_write=False,
        ),
        ToolDescriptor(
            name="search_vault",
            description=TOOL_DESCRIPTIONS["search_vault"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path_prefix": {"type": "string", "default": ""},
                    "max_results": {
                        "type": "integer",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=notes.search_vault,
            is_write=False,
        ),
        ToolDescriptor(
            name="get_mistake_log",
            description=TOOL_DESCRIPTIONS["get_mistake_log"],
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=mistake_log.get_mistake_log,
            is_write=False,
        ),
        ToolDescriptor(
            name="append_mistake_log",
            description=TOOL_DESCRIPTIONS["append_mistake_log"],
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "context": {"type": "string"},
                    "mistake": {"type": "string"},
                    "root_cause": {"type": "string"},
                    "fix": {"type": "string"},
                    "lesson": {"type": "string"},
                    "date": {
                        "type": "string",
                        "default": "",
                        "description": "YYYY-MM-DD or empty for today.",
                    },
                },
                "required": [
                    "title",
                    "context",
                    "mistake",
                    "root_cause",
                    "fix",
                    "lesson",
                ],
                "additionalProperties": False,
            },
            handler=mistake_log.append_mistake_log,
            is_write=True,
        ),
        ToolDescriptor(
            name="get_pipeline_index",
            description=TOOL_DESCRIPTIONS["get_pipeline_index"],
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=projects.get_pipeline_index,
            is_write=False,
        ),
        ToolDescriptor(
            name="search_projects",
            description=TOOL_DESCRIPTIONS["search_projects"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {
                        "type": "integer",
                        "default": 30,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=projects.search_projects,
            is_write=False,
        ),
        ToolDescriptor(
            name="bootstrap_project",
            description=TOOL_DESCRIPTIONS["bootstrap_project"],
            input_schema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "files": {
                        "type": "object",
                        "properties": {
                            "project": {"type": "string"},
                            "summary": {"type": "string"},
                            "logs": {"type": "string"},
                            "prd": {"type": "string"},
                            "design": {"type": "string"},
                            "research": {"type": "string"},
                            "premortem": {"type": "string"},
                        },
                        "additionalProperties": False,
                        "default": {},
                    },
                },
                "required": ["slug"],
                "additionalProperties": False,
            },
            handler=projects.bootstrap_project,
            is_write=True,
        ),
    ]


TOOL_REGISTRY = build_tool_registry()


def _context_for_descriptor(
    descriptor: ToolDescriptor,
    *,
    notes_ctx: notes.ToolContext,
    mistake_log_ctx: mistake_log.ToolContext,
    projects_ctx: projects.ToolContext,
) -> notes.ToolContext | mistake_log.ToolContext | projects.ToolContext:
    if descriptor.name in {
        "read_note",
        "write_note",
        "append_note",
        "list_notes",
        "search_vault",
    }:
        return notes_ctx
    if descriptor.name in {"get_mistake_log", "append_mistake_log"}:
        return mistake_log_ctx
    if descriptor.name in {
        "get_pipeline_index",
        "search_projects",
        "bootstrap_project",
    }:
        return projects_ctx
    raise MCPError(
        ErrorCode.INTERNAL_ERROR,
        "Tool descriptor is not registered",
        {"tool": descriptor.name},
    )


async def dispatch(
    descriptor: ToolDescriptor | None,
    arguments: dict[str, Any],
    *,
    notes_ctx: notes.ToolContext,
    mistake_log_ctx: mistake_log.ToolContext,
    projects_ctx: projects.ToolContext,
    config: Config,
) -> dict[str, Any]:
    """
    Top-level dispatcher.
    1. If config.read_only and descriptor.is_write -> return error_envelope(
       READ_ONLY_MODE_ENABLED, ...). (Each individual tool also checks read_only;
       this is a defense-in-depth gate at the SDK boundary.)
    2. Choose the right ctx based on descriptor name.
    3. Try descriptor.handler(ctx, **arguments).
    4. On MCPError -> return from_exception(exc).
    5. On any unexpected exception -> log redacted, return error_envelope(INTERNAL_ERROR, ...).
       The exception's traceback MUST NOT appear in the envelope.
    Return the dict envelope.
    """

    if descriptor is None:
        return error_envelope(
            ErrorCode.VALIDATION_ERROR,
            "Unknown tool name",
            {"unknown_tool": arguments.get("name")},
        )

    if config.read_only and descriptor.is_write:
        return error_envelope(
            ErrorCode.READ_ONLY_MODE_ENABLED,
            "Write operations are disabled in read-only mode",
            {"tool": descriptor.name},
        )

    try:
        ctx = _context_for_descriptor(
            descriptor,
            notes_ctx=notes_ctx,
            mistake_log_ctx=mistake_log_ctx,
            projects_ctx=projects_ctx,
        )
        return await descriptor.handler(ctx, **arguments)
    except MCPError as exc:
        return from_exception(exc)
    except Exception as exc:  # pragma: no cover - covered by tests
        safe_message = redact_token(str(exc), config.api_key)
        logger.exception(
            "Unhandled tool exception in %s: %s",
            descriptor.name,
            safe_message,
            exc_info=False,
        )
        return error_envelope(
            ErrorCode.INTERNAL_ERROR,
            f"{descriptor.name} failed unexpectedly",
            {"tool": descriptor.name},
        )


def envelope_to_text_content(envelope: dict[str, Any]) -> list[types.TextContent]:
    """JSON-serialize the envelope into [TextContent(text=...)] for MCP response."""

    return [types.TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False))]


async def serve_stdio(config: Config) -> None:
    """
    Run the MCP server over stdio.
    1. Build ObsidianClient, LockRegistry, and per-module ToolContext instances.
    2. Initialize mcp.server.Server.
    3. Register list_tools() handler returning Tool objects.
    4. Register call_tool(name, arguments) handler that:
       a. Looks up descriptor by name. If not found → return error envelope.
       b. Calls dispatch(...).
       c. Wraps the envelope in TextContent.
    5. Run with stdio_server() context manager.
    6. On shutdown, await client.aclose().
    """

    client = ObsidianClient(config)
    locks = LockRegistry()
    notes_ctx = notes.ToolContext(client=client, config=config, locks=locks)
    mistake_log_ctx = mistake_log.ToolContext(client=client, config=config, locks=locks)
    projects_ctx = projects.ToolContext(client=client, config=config, locks=locks)
    tool_registry = build_tool_registry()
    descriptors_by_name = {descriptor.name: descriptor for descriptor in tool_registry}

    server = Server("obsidian-mcp-opencode", version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=descriptor.name,
                description=descriptor.description,
                inputSchema=descriptor.input_schema,
            )
            for descriptor in tool_registry
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        descriptor = descriptors_by_name.get(name)
        envelope = await dispatch(
            descriptor,
            arguments if descriptor is not None else {"name": name},
            notes_ctx=notes_ctx,
            mistake_log_ctx=mistake_log_ctx,
            projects_ctx=projects_ctx,
            config=config,
        )
        return envelope_to_text_content(envelope)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="obsidian-mcp-opencode",
                    server_version=__version__,
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    finally:
        await client.aclose()
