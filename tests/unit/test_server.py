from __future__ import annotations

import json

import pytest

from obsidian_mcp_opencode.config import Config
from obsidian_mcp_opencode.errors import ErrorCode, MCPError
from obsidian_mcp_opencode.locks import LockRegistry
from obsidian_mcp_opencode.obsidian_client import ObsidianClient
from obsidian_mcp_opencode.server import (
    TOOL_REGISTRY,
    ToolDescriptor,
    build_tool_registry,
    dispatch,
    envelope_to_text_content,
)
from obsidian_mcp_opencode.tools import mistake_log, notes, projects

CANONICAL_FREYA_TOOL_NAMES = {
    "read_note",
    "write_note",
    "append_note",
    "list_notes",
    "search_vault",
    "get_mistake_log",
    "append_mistake_log",
    "get_pipeline_index",
    "search_projects",
    "bootstrap_project",
}
CANONICAL_GENERIC_TOOL_NAMES = {
    "read_note",
    "write_note",
    "append_note",
    "list_notes",
    "search_vault",
}
FREYA_WRITE_TOOL_NAMES = {
    "write_note",
    "append_note",
    "append_mistake_log",
    "bootstrap_project",
}
GENERIC_WRITE_TOOL_NAMES = {
    "write_note",
    "append_note",
}
MOVE_TOOL_NAME = "move_note"

EXPECTED_GENERIC_REGISTRY_BASE = 5
EXPECTED_GENERIC_REGISTRY_WITH_MOVE = 6
EXPECTED_FREYA_REGISTRY_BASE = 10
EXPECTED_FREYA_REGISTRY_WITH_MOVE = 11
EXPECTED_FREYA_WRITE_TOOL_COUNT = 4
EXPECTED_FREYA_READ_TOOL_COUNT = 6
EXPECTED_GENERIC_WRITE_TOOL_COUNT = 2
EXPECTED_GENERIC_READ_TOOL_COUNT = 3


@pytest.fixture
def config(freya_config: Config) -> Config:
    return freya_config


@pytest.fixture
def read_only_config(freya_config: Config) -> Config:
    return Config(
        vault_path=freya_config.vault_path,
        api_key=freya_config.api_key,
        base_url=freya_config.base_url,
        log_level=freya_config.log_level,
        read_only=True,
        allow_move=False,
        workflow=freya_config.workflow,
        write_patterns=freya_config.write_patterns,
        append_only_patterns=freya_config.append_only_patterns,
        protected_memory_paths=freya_config.protected_memory_paths,
    )


def make_contexts(config: Config):
    client = ObsidianClient(config)
    locks = LockRegistry()
    return (
        notes.ToolContext(client=client, config=config, locks=locks),
        mistake_log.ToolContext(client=client, config=config, locks=locks),
        projects.ToolContext(client=client, config=config, locks=locks),
        client,
    )


def _descriptor(name: str) -> ToolDescriptor:
    return next(item for item in TOOL_REGISTRY if item.name == name)


def _with_allow_move(config: Config, allow_move: bool) -> Config:
    return Config(
        vault_path=config.vault_path,
        api_key=config.api_key,
        base_url=config.base_url,
        log_level=config.log_level,
        read_only=config.read_only,
        allow_move=allow_move,
        workflow=config.workflow,
        write_patterns=config.write_patterns,
        append_only_patterns=config.append_only_patterns,
        protected_memory_paths=config.protected_memory_paths,
    )


def test_build_tool_registry_without_config_returns_core_descriptors_only() -> None:
    registry = build_tool_registry()

    assert len(registry) == EXPECTED_GENERIC_REGISTRY_BASE
    assert all(isinstance(item, ToolDescriptor) for item in registry)
    assert {item.name for item in registry} == CANONICAL_GENERIC_TOOL_NAMES


def test_build_tool_registry_freya_allow_move_false_returns_ten_descriptors(
    config: Config,
) -> None:
    registry = build_tool_registry(_with_allow_move(config, False))

    assert len(registry) == EXPECTED_FREYA_REGISTRY_BASE
    assert all(isinstance(item, ToolDescriptor) for item in registry)


def test_build_tool_registry_freya_allow_move_true_returns_eleven_descriptors(
    config: Config,
) -> None:
    registry = build_tool_registry(_with_allow_move(config, True))

    assert len(registry) == EXPECTED_FREYA_REGISTRY_WITH_MOVE
    move_descriptor = next(item for item in registry if item.name == MOVE_TOOL_NAME)
    assert move_descriptor.is_write is True


def test_build_tool_registry_generic_allow_move_false_returns_five_descriptors(
    generic_config: Config,
) -> None:
    registry = build_tool_registry(generic_config)

    assert len(registry) == EXPECTED_GENERIC_REGISTRY_BASE
    assert {item.name for item in registry} == CANONICAL_GENERIC_TOOL_NAMES


def test_build_tool_registry_generic_allow_move_true_returns_six_descriptors(
    generic_config: Config,
) -> None:
    registry = build_tool_registry(_with_allow_move(generic_config, True))

    assert len(registry) == EXPECTED_GENERIC_REGISTRY_WITH_MOVE
    assert {item.name for item in registry} == (
        CANONICAL_GENERIC_TOOL_NAMES | {MOVE_TOOL_NAME}
    )


def test_tool_names_are_unique_and_match_canonical_names_for_freya(
    config: Config,
) -> None:
    registry = build_tool_registry(config)
    names = [item.name for item in registry]

    assert len(names) == len(set(names))
    assert set(names) == CANONICAL_FREYA_TOOL_NAMES


def test_tool_names_are_unique_and_match_canonical_names_for_generic(
    generic_config: Config,
) -> None:
    registry = build_tool_registry(generic_config)
    names = [item.name for item in registry]

    assert len(names) == len(set(names))
    assert set(names) == CANONICAL_GENERIC_TOOL_NAMES


def test_write_flag_classification_matches_freya_contract(
    config: Config,
) -> None:
    registry = build_tool_registry(config)
    write_tools = {item.name for item in registry if item.is_write}
    read_tools = {item.name for item in registry if not item.is_write}

    assert write_tools == FREYA_WRITE_TOOL_NAMES
    assert len(write_tools) == EXPECTED_FREYA_WRITE_TOOL_COUNT
    assert len(read_tools) == EXPECTED_FREYA_READ_TOOL_COUNT
    assert write_tools.isdisjoint(read_tools)


def test_write_flag_classification_matches_generic_contract(generic_config: Config) -> None:
    registry = build_tool_registry(generic_config)
    write_tools = {item.name for item in registry if item.is_write}
    read_tools = {item.name for item in registry if not item.is_write}

    assert write_tools == GENERIC_WRITE_TOOL_NAMES
    assert len(write_tools) == EXPECTED_GENERIC_WRITE_TOOL_COUNT
    assert len(read_tools) == EXPECTED_GENERIC_READ_TOOL_COUNT
    assert write_tools.isdisjoint(read_tools)


def test_write_flag_classification_includes_move_only_when_enabled(config: Config) -> None:
    disabled_registry = build_tool_registry(_with_allow_move(config, False))
    enabled_registry = build_tool_registry(_with_allow_move(config, True))

    disabled_write_tools = {item.name for item in disabled_registry if item.is_write}
    enabled_write_tools = {item.name for item in enabled_registry if item.is_write}

    assert disabled_write_tools == FREYA_WRITE_TOOL_NAMES
    assert enabled_write_tools == FREYA_WRITE_TOOL_NAMES | {MOVE_TOOL_NAME}


def test_no_tool_descriptor_exposes_delete_name(config: Config, generic_config: Config) -> None:
    registries = [
        build_tool_registry(),
        build_tool_registry(config),
        build_tool_registry(_with_allow_move(config, True)),
        build_tool_registry(generic_config),
        build_tool_registry(_with_allow_move(generic_config, True)),
    ]

    for registry in registries:
        names = {item.name for item in registry}
        assert "delete_note" not in names
        assert "delete_file" not in names
        assert all("delete" not in name for name in names)


async def test_dispatch_read_only_config_blocks_write_tool(read_only_config: Config) -> None:
    notes_ctx, mistake_log_ctx, projects_ctx, client = make_contexts(read_only_config)

    try:
        result = await dispatch(
            _descriptor("write_note"),
            {"path": "Projects/foo/PROJECT.md", "content": "body"},
            notes_ctx=notes_ctx,
            mistake_log_ctx=mistake_log_ctx,
            projects_ctx=projects_ctx,
            config=read_only_config,
        )
    finally:
        await client.aclose()

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.READ_ONLY_MODE_ENABLED
    assert result["error"]["details"]["tool"] == "write_note"


async def test_dispatch_read_only_config_allows_read_tool_attempt(
    read_only_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes_ctx, mistake_log_ctx, projects_ctx, client = make_contexts(read_only_config)
    called: dict[str, object] = {}

    async def fake_read_note(ctx: notes.ToolContext, *, path: str) -> dict[str, object]:
        called["ctx"] = ctx
        called["path"] = path
        return {"ok": True, "data": {"content": "x", "size": 1, "mtime": None}}

    monkeypatch.setattr(notes, "read_note", fake_read_note)
    descriptor = ToolDescriptor(
        name="read_note",
        description="desc",
        input_schema={"type": "object"},
        handler=notes.read_note,
        is_write=False,
    )

    try:
        result = await dispatch(
            descriptor,
            {"path": "Projects/foo/PROJECT.md"},
            notes_ctx=notes_ctx,
            mistake_log_ctx=mistake_log_ctx,
            projects_ctx=projects_ctx,
            config=read_only_config,
        )
    finally:
        await client.aclose()

    assert result["ok"] is True
    assert called["ctx"] is notes_ctx
    assert called["path"] == "Projects/foo/PROJECT.md"


async def test_dispatch_catches_mcp_error_and_returns_exception_envelope(
    config: Config,
) -> None:
    notes_ctx, mistake_log_ctx, projects_ctx, client = make_contexts(config)

    async def fake_handler(ctx: notes.ToolContext, **_kwargs: object) -> dict[str, object]:
        raise MCPError(ErrorCode.PATH_FORBIDDEN, "bad path", {"input_path": "x"})

    descriptor = ToolDescriptor(
        name="read_note",
        description="desc",
        input_schema={"type": "object"},
        handler=fake_handler,
        is_write=False,
    )

    try:
        result = await dispatch(
            descriptor,
            {},
            notes_ctx=notes_ctx,
            mistake_log_ctx=mistake_log_ctx,
            projects_ctx=projects_ctx,
            config=config,
        )
    finally:
        await client.aclose()

    assert result == {
        "ok": False,
        "error": {
            "code": ErrorCode.PATH_FORBIDDEN,
            "message": "bad path",
            "details": {"input_path": "x"},
        },
    }


async def test_dispatch_catches_unexpected_exception_and_redacts_token(
    config: Config,
    caplog: pytest.LogCaptureFixture,
) -> None:
    notes_ctx, mistake_log_ctx, projects_ctx, client = make_contexts(config)
    caplog.set_level("ERROR")

    async def fake_handler(ctx: notes.ToolContext, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError(f"boom {config.api_key}")

    descriptor = ToolDescriptor(
        name="read_note",
        description="desc",
        input_schema={"type": "object"},
        handler=fake_handler,
        is_write=False,
    )

    try:
        result = await dispatch(
            descriptor,
            {},
            notes_ctx=notes_ctx,
            mistake_log_ctx=mistake_log_ctx,
            projects_ctx=projects_ctx,
            config=config,
        )
    finally:
        await client.aclose()

    assert result == {
        "ok": False,
        "error": {
            "code": ErrorCode.INTERNAL_ERROR,
            "message": "read_note failed unexpectedly",
            "details": {"tool": "read_note"},
        },
    }
    assert config.api_key not in json.dumps(result)
    assert config.api_key not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "RuntimeError" not in json.dumps(result)
    assert "Traceback" not in json.dumps(result)


async def test_dispatch_unknown_tool_name_returns_validation_error(config: Config) -> None:
    notes_ctx, mistake_log_ctx, projects_ctx, client = make_contexts(config)

    try:
        result = await dispatch(
            None,
            {"name": "does_not_exist"},
            notes_ctx=notes_ctx,
            mistake_log_ctx=mistake_log_ctx,
            projects_ctx=projects_ctx,
            config=config,
        )
    finally:
        await client.aclose()

    assert result == {
        "ok": False,
        "error": {
            "code": ErrorCode.VALIDATION_ERROR,
            "message": "Unknown tool name",
            "details": {"unknown_tool": "does_not_exist"},
        },
    }


def test_envelope_to_text_content_returns_one_json_text_item() -> None:
    envelope = {"ok": True, "data": {"value": 1}}

    content = envelope_to_text_content(envelope)

    assert len(content) == 1
    assert content[0].type == "text"
    assert json.loads(content[0].text) == envelope
