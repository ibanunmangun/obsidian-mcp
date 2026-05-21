from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_mcp_opencode.config import Config
from obsidian_mcp_opencode.errors import ErrorCode, MCPError
from obsidian_mcp_opencode.locks import LockRegistry
from obsidian_mcp_opencode.obsidian_client import ObsidianClient
from obsidian_mcp_opencode.tools.notes import ToolContext, move_note

pytestmark = pytest.mark.asyncio
DELETE_VERIFICATION_SOURCE_STAT_CALLS = 2


@pytest.fixture
async def ctx(freya_config: Config):
    config = Config(
        vault_path=freya_config.vault_path,
        api_key=freya_config.api_key,
        base_url=freya_config.base_url,
        log_level=freya_config.log_level,
        read_only=False,
        allow_move=True,
        workflow=freya_config.workflow,
        write_patterns=freya_config.write_patterns,
        append_only_patterns=freya_config.append_only_patterns,
        protected_memory_paths=freya_config.protected_memory_paths,
    )
    client = ObsidianClient(config)
    locks = LockRegistry()
    context = ToolContext(client=client, config=config, locks=locks)
    try:
        yield context
    finally:
        await client.aclose()


@pytest.fixture
async def read_only_ctx(freya_config: Config):
    config = Config(
        vault_path=freya_config.vault_path,
        api_key=freya_config.api_key,
        base_url=freya_config.base_url,
        log_level=freya_config.log_level,
        read_only=True,
        allow_move=True,
        workflow=freya_config.workflow,
        write_patterns=freya_config.write_patterns,
        append_only_patterns=freya_config.append_only_patterns,
        protected_memory_paths=freya_config.protected_memory_paths,
    )
    client = ObsidianClient(config)
    locks = LockRegistry()
    context = ToolContext(client=client, config=config, locks=locks)
    try:
        yield context
    finally:
        await client.aclose()


def _error_code(result: dict) -> str:
    assert result["ok"] is False
    return result["error"]["code"]


def _build_partial_details(result: dict) -> dict:
    assert result["ok"] is False
    return result["error"]["details"]


async def test_move_note_read_only_mode_returns_error(read_only_ctx: ToolContext) -> None:
    result = await move_note(
        read_only_ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.READ_ONLY_MODE_ENABLED


async def test_move_note_source_absolute_path_rejected(ctx: ToolContext) -> None:
    result = await move_note(
        ctx,
        source_path="/etc/passwd",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_move_note_source_parent_traversal_rejected(ctx: ToolContext) -> None:
    result = await move_note(
        ctx,
        source_path="../secret.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_move_note_source_hidden_segment_rejected(ctx: ToolContext) -> None:
    result = await move_note(
        ctx,
        source_path="Projects/.foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_HIDDEN_FILE


async def test_move_note_source_mistake_log_rejected(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Freya - Mistake Log.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL


async def test_move_note_source_append_only_logs_rejected(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Projects/foo/LOGS.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_APPEND_ONLY


async def test_move_note_source_protected_memory_rejected(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Projects/PIPELINE_INDEX.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_move_note_destination_not_whitelisted_rejected(
    ctx: ToolContext, tmp_path: Path
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Notes/random.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_move_note_destination_mistake_log_rejected(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Freya - Mistake Log.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL


async def test_move_note_destination_append_only_rejected(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/LOGS.md",
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_APPEND_ONLY


async def test_move_note_identical_canonical_paths_rejected(
    ctx: ToolContext, tmp_path: Path
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Projects/foo//PROJECT.md",
        destination_path="Projects/foo/PROJECT.md",
    )
    assert _error_code(result) == ErrorCode.VALIDATION_ERROR
    assert result["error"]["details"]["reason"] == "source_and_destination_identical"


async def test_move_note_destination_parent_missing(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/bar/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PARENT_DIRECTORY_MISSING


async def test_move_note_destination_already_exists(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)

    async def fake_stat(path: str) -> dict[str, object]:
        if path == "Projects/foo/SUMMARY.md":
            return {"exists": True, "size": 4, "mtime": 1.0}
        return {"exists": True, "size": 4, "mtime": 1.0}

    ctx.client.stat = fake_stat  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.FILE_EXISTS


async def test_move_note_source_missing(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)

    async def fake_stat(path: str) -> dict[str, object]:
        if path == "Projects/foo/SUMMARY.md":
            return {"exists": False, "size": None, "mtime": None}
        return {"exists": False, "size": None, "mtime": None}

    ctx.client.stat = fake_stat  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )
    assert _error_code(result) == ErrorCode.PATH_NOT_FOUND


async def test_move_note_happy_path_same_folder_rename(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    state = {
        "Projects/foo/PROJECT.md": {"exists": True, "content": "hello world", "mtime": 1.0},
        "Projects/foo/SUMMARY.md": {"exists": False, "content": "", "mtime": None},
    }

    async def fake_stat(path: str) -> dict[str, object]:
        entry = state[path]
        if not entry["exists"]:
            return {"exists": False, "size": None, "mtime": None}
        content = str(entry["content"])
        return {"exists": True, "size": len(content.encode("utf-8")), "mtime": entry["mtime"]}

    async def fake_get_file(path: str) -> tuple[str, dict[str, object]]:
        entry = state[path]
        if not entry["exists"]:
            raise MCPError(ErrorCode.PATH_NOT_FOUND, "Vault path not found", {"path": path})
        content = str(entry["content"])
        return content, {"size": len(content.encode("utf-8")), "mtime": entry["mtime"]}

    async def fake_put_file(path: str, content: str) -> None:
        state[path] = {"exists": True, "content": content, "mtime": 2.0}

    async def fake_delete_file(path: str) -> None:
        state[path]["exists"] = False
        state[path]["content"] = ""
        state[path]["mtime"] = None

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]
    ctx.client.delete_file = fake_delete_file  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )

    assert result == {
        "ok": True,
        "data": {
            "moved": True,
            "source": "Projects/foo/PROJECT.md",
            "destination": "Projects/foo/SUMMARY.md",
        },
    }
    assert state["Projects/foo/PROJECT.md"]["exists"] is False
    assert state["Projects/foo/SUMMARY.md"]["exists"] is True
    assert state["Projects/foo/SUMMARY.md"]["content"] == "hello world"


async def test_move_note_happy_path_different_folder(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    (tmp_path / "Projects" / "bar").mkdir(parents=True)
    state = {
        "Projects/foo/PROJECT.md": {"exists": True, "content": "payload", "mtime": 1.0},
        "Projects/bar/SUMMARY.md": {"exists": False, "content": "", "mtime": None},
    }

    async def fake_stat(path: str) -> dict[str, object]:
        entry = state[path]
        if not entry["exists"]:
            return {"exists": False, "size": None, "mtime": None}
        content = str(entry["content"])
        return {"exists": True, "size": len(content.encode("utf-8")), "mtime": entry["mtime"]}

    async def fake_get_file(path: str) -> tuple[str, dict[str, object]]:
        content = str(state[path]["content"])
        return content, {"size": len(content.encode("utf-8")), "mtime": state[path]["mtime"]}

    async def fake_put_file(path: str, content: str) -> None:
        state[path] = {"exists": True, "content": content, "mtime": 2.0}

    async def fake_delete_file(path: str) -> None:
        state[path]["exists"] = False
        state[path]["content"] = ""
        state[path]["mtime"] = None

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]
    ctx.client.delete_file = fake_delete_file  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/bar/SUMMARY.md",
    )

    assert result["ok"] is True
    assert result["data"]["destination"] == "Projects/bar/SUMMARY.md"
    assert state["Projects/foo/PROJECT.md"]["exists"] is False
    assert state["Projects/bar/SUMMARY.md"]["content"] == "payload"


async def test_move_note_destination_readback_content_mismatch_returns_write_verification_failed(
    ctx: ToolContext,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    delete_called = False
    get_calls: list[str] = []

    async def fake_stat(path: str) -> dict[str, object]:
        return {"exists": path == "Projects/foo/PROJECT.md", "size": 5, "mtime": 1.0}

    async def fake_get_file(path: str) -> tuple[str, dict[str, object]]:
        get_calls.append(path)
        if get_calls == ["Projects/foo/PROJECT.md"]:
            return "hello", {"size": 5, "mtime": 1.0}
        return "wrong", {"size": 5, "mtime": 1.0}

    async def fake_put_file(path: str, content: str) -> None:
        assert path == "Projects/foo/SUMMARY.md"
        assert content == "hello"

    async def fake_delete_file(path: str) -> None:
        nonlocal delete_called
        delete_called = True

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]
    ctx.client.delete_file = fake_delete_file  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )

    assert _error_code(result) == ErrorCode.WRITE_VERIFICATION_FAILED
    assert delete_called is False


async def test_move_note_destination_readback_failure_returns_write_verification_failed(
    ctx: ToolContext,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    delete_called = False
    get_calls = 0

    async def fake_stat(path: str) -> dict[str, object]:
        return {"exists": path == "Projects/foo/PROJECT.md", "size": 5, "mtime": 1.0}

    async def fake_get_file(path: str) -> tuple[str, dict[str, object]]:
        nonlocal get_calls
        get_calls += 1
        if get_calls == 1:
            return "hello", {"size": 5, "mtime": 1.0}
        raise MCPError(ErrorCode.INTERNAL_ERROR, "boom", {"body": "bad"})

    async def fake_put_file(path: str, content: str) -> None:
        assert path == "Projects/foo/SUMMARY.md"
        assert content == "hello"

    async def fake_delete_file(path: str) -> None:
        nonlocal delete_called
        delete_called = True

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]
    ctx.client.delete_file = fake_delete_file  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )

    assert _error_code(result) == ErrorCode.WRITE_VERIFICATION_FAILED
    assert result["error"]["details"]["underlying_error"] == ErrorCode.INTERNAL_ERROR
    assert delete_called is False


async def test_move_note_delete_failure_returns_move_partial(
    ctx: ToolContext, tmp_path: Path
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)

    async def fake_stat(path: str) -> dict[str, object]:
        return {"exists": path == "Projects/foo/PROJECT.md", "size": 5, "mtime": 1.0}

    async def fake_get_file(path: str) -> tuple[str, dict[str, object]]:
        return "hello", {"size": 5, "mtime": 1.0}

    async def fake_put_file(path: str, content: str) -> None:
        assert path == "Projects/foo/SUMMARY.md"
        assert content == "hello"

    async def fake_delete_file(path: str) -> None:
        raise MCPError(ErrorCode.INTERNAL_ERROR, "delete failed", {"body": "x"})

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]
    ctx.client.delete_file = fake_delete_file  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )

    details = _build_partial_details(result)
    assert _error_code(result) == ErrorCode.MOVE_PARTIAL
    assert details == {
        "stage": "delete_source",
        "source": "Projects/foo/PROJECT.md",
        "destination": "Projects/foo/SUMMARY.md",
        "destination_created": True,
        "destination_exists_after_write": True,
        "source_delete_attempted": True,
        "source_exists_after_delete": True,
        "manual_cleanup_required": True,
        "underlying_error": ErrorCode.INTERNAL_ERROR,
    }


async def test_move_note_stat_after_delete_failure_returns_move_partial(
    ctx: ToolContext,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    stat_calls: dict[str, int] = {}

    async def fake_stat(path: str) -> dict[str, object]:
        stat_calls[path] = stat_calls.get(path, 0) + 1
        if path == "Projects/foo/SUMMARY.md":
            return {"exists": False, "size": None, "mtime": None}
        if (
            path == "Projects/foo/PROJECT.md"
            and stat_calls[path] <= DELETE_VERIFICATION_SOURCE_STAT_CALLS
        ):
            return {"exists": True, "size": 5, "mtime": 1.0}
        raise MCPError(ErrorCode.INTERNAL_ERROR, "stat failed", {"body": "x"})

    async def fake_get_file(path: str) -> tuple[str, dict[str, object]]:
        return "hello", {"size": 5, "mtime": 1.0}

    async def fake_put_file(path: str, content: str) -> None:
        assert path == "Projects/foo/SUMMARY.md"
        assert content == "hello"

    async def fake_delete_file(path: str) -> None:
        return None

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]
    ctx.client.delete_file = fake_delete_file  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )

    details = _build_partial_details(result)
    assert _error_code(result) == ErrorCode.MOVE_PARTIAL
    assert details["stage"] == "verify_source_deleted"
    assert details["source_exists_after_delete"] == "unknown"
    assert details["manual_cleanup_required"] is True


async def test_move_note_source_still_exists_after_delete_returns_move_partial(
    ctx: ToolContext,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    stat_calls: dict[str, int] = {}

    async def fake_stat(path: str) -> dict[str, object]:
        stat_calls[path] = stat_calls.get(path, 0) + 1
        if path == "Projects/foo/SUMMARY.md":
            return {"exists": False, "size": None, "mtime": None}
        return {"exists": True, "size": 5, "mtime": 1.0}

    async def fake_get_file(path: str) -> tuple[str, dict[str, object]]:
        return "hello", {"size": 5, "mtime": 1.0}

    async def fake_put_file(path: str, content: str) -> None:
        assert path == "Projects/foo/SUMMARY.md"
        assert content == "hello"

    async def fake_delete_file(path: str) -> None:
        return None

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]
    ctx.client.delete_file = fake_delete_file  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )

    details = _build_partial_details(result)
    assert _error_code(result) == ErrorCode.MOVE_PARTIAL
    assert details["stage"] == "verify_source_deleted"
    assert details["source_exists_after_delete"] is True
    assert details["manual_cleanup_required"] is True


async def test_move_note_redacts_token_from_error_envelope(
    ctx: ToolContext, tmp_path: Path
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)

    async def fake_stat(path: str) -> dict[str, object]:
        if path == "Projects/foo/SUMMARY.md":
            raise MCPError(
                ErrorCode.INTERNAL_ERROR,
                f"failure {ctx.config.api_key}",
                {"body": f"secret={ctx.config.api_key}"},
            )
        return {"exists": True, "size": 5, "mtime": 1.0}

    ctx.client.stat = fake_stat  # type: ignore[method-assign]

    result = await move_note(
        ctx,
        source_path="Projects/foo/PROJECT.md",
        destination_path="Projects/foo/SUMMARY.md",
    )

    rendered = str(result)
    assert result["ok"] is False
    assert ctx.config.api_key not in rendered
    assert "[REDACTED]" in rendered
