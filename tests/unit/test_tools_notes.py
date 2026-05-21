from __future__ import annotations

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from obsidian_mcp_opencode.config import (
    MAX_SEARCH_QUERY_CHARS,
    MAX_SEARCH_RESULTS,
    MAX_SEARCH_SNIPPET_CHARS,
    Config,
)
from obsidian_mcp_opencode.errors import ErrorCode
from obsidian_mcp_opencode.locks import LockRegistry
from obsidian_mcp_opencode.obsidian_client import ObsidianClient
from obsidian_mcp_opencode.tools.notes import (
    ToolContext,
    append_note,
    list_notes,
    read_note,
    search_vault,
    write_note,
)

TEST_API_KEY = "test-token-abcdefghijklmnopqrstuvwxyz-1234567890"
EXPECTED_RECURSIVE_REQUESTS = 8

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ctx(tmp_path: Path):
    config = Config(
        vault_path=tmp_path,
        api_key=TEST_API_KEY,
        base_url="http://127.0.0.1:27123",
        log_level="INFO",
        read_only=False,
    )
    client = ObsidianClient(config)
    locks = LockRegistry()
    context = ToolContext(client=client, config=config, locks=locks)
    try:
        yield context
    finally:
        await client.aclose()


@pytest.fixture
async def read_only_ctx(tmp_path: Path):
    config = Config(
        vault_path=tmp_path,
        api_key=TEST_API_KEY,
        base_url="http://127.0.0.1:27123",
        log_level="INFO",
        read_only=True,
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


async def test_read_note_success_returns_content_size_and_mtime(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        text="hello world",
        headers={"Content-Length": "11", "Last-Modified": "123.5"},
    )

    result = await read_note(ctx, path="Projects/foo/PROJECT.md")

    assert result == {
        "ok": True,
        "data": {"content": "hello world", "size": 11, "mtime": 123.5},
    }


async def test_read_note_absolute_path_rejected(ctx: ToolContext) -> None:
    result = await read_note(ctx, path="/etc/passwd")
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_read_note_missing_path_maps_to_path_not_found(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        status_code=404,
    )

    result = await read_note(ctx, path="Projects/foo/PROJECT.md")
    assert _error_code(result) == ErrorCode.PATH_NOT_FOUND


async def test_read_note_hidden_file_rejected(ctx: ToolContext) -> None:
    result = await read_note(ctx, path=".obsidian/config.json")
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_HIDDEN_FILE


async def test_write_note_read_only_mode_rejected(read_only_ctx: ToolContext) -> None:
    result = await write_note(read_only_ctx, path="Projects/foo/PROJECT.md", content="body")
    assert _error_code(result) == ErrorCode.READ_ONLY_MODE_ENABLED


async def test_write_note_non_whitelisted_path_rejected(ctx: ToolContext) -> None:
    result = await write_note(ctx, path="Notes/random.md", content="body")
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_write_note_mistake_log_requires_specialized_tool(ctx: ToolContext) -> None:
    result = await write_note(ctx, path="Freya - Mistake Log.md", content="body")
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL


async def test_write_note_append_only_project_logs_rejected(
    ctx: ToolContext,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)

    result = await write_note(ctx, path="Projects/foo/LOGS.md", content="body", overwrite=True)
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_APPEND_ONLY


async def test_write_note_parent_directory_missing(ctx: ToolContext) -> None:
    result = await write_note(ctx, path="Projects/foo/PROJECT.md", content="body")
    assert _error_code(result) == ErrorCode.PARENT_DIRECTORY_MISSING


async def test_write_note_existing_file_without_overwrite_rejected(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        headers={"Content-Length": "4"},
    )

    result = await write_note(ctx, path="Projects/foo/PROJECT.md", content="body")
    assert _error_code(result) == ErrorCode.FILE_EXISTS


async def test_write_note_happy_create_path(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        status_code=404,
    )
    httpx_mock.add_response(
        method="PUT",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        status_code=204,
    )
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        headers={"Content-Length": "12"},
    )

    result = await write_note(ctx, path="Projects/foo/PROJECT.md", content="hello world!")

    assert result == {
        "ok": True,
        "data": {"created": True, "overwritten": False, "size": 12},
    }


async def test_write_note_happy_overwrite_path(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    caplog.set_level("INFO")
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        headers={"Content-Length": "8"},
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        text="old body",
        headers={"Content-Length": "8"},
    )
    httpx_mock.add_response(
        method="PUT",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        status_code=204,
    )
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        headers={"Content-Length": "8"},
    )

    result = await write_note(
        ctx,
        path="Projects/foo/PROJECT.md",
        content="new body",
        overwrite=True,
    )

    assert result == {
        "ok": True,
        "data": {"created": False, "overwritten": True, "size": 8},
    }
    assert "sha256=" in caplog.text


async def test_write_note_protected_memory_cannot_overwrite(
    ctx: ToolContext,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects").mkdir(parents=True)
    result = await write_note(
        ctx,
        path="Projects/PIPELINE_INDEX.md",
        content="body",
        overwrite=True,
    )
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_append_note_read_only_mode_rejected(read_only_ctx: ToolContext) -> None:
    result = await append_note(read_only_ctx, path="Projects/foo/PROJECT.md", content="tail")
    assert _error_code(result) == ErrorCode.READ_ONLY_MODE_ENABLED


async def test_append_note_mistake_log_requires_specialized_tool(
    ctx: ToolContext,
    tmp_path: Path,
) -> None:
    tmp_path.mkdir(exist_ok=True)
    result = await append_note(ctx, path="Freya - Mistake Log.md", content="tail")
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL


async def test_append_note_non_whitelisted_path_rejected(ctx: ToolContext) -> None:
    result = await append_note(ctx, path="Notes/random.md", content="tail")
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN


async def test_append_note_parent_directory_missing(ctx: ToolContext) -> None:
    result = await append_note(ctx, path="Projects/foo/PROJECT.md", content="tail")
    assert _error_code(result) == ErrorCode.PARENT_DIRECTORY_MISSING


async def test_append_note_happy_path(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        headers={"Content-Length": "5"},
    )
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        status_code=204,
    )
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        headers={"Content-Length": "9"},
    )

    result = await append_note(ctx, path="Projects/foo/PROJECT.md", content="tail")

    assert result == {
        "ok": True,
        "data": {"created": False, "size_before": 5, "size_after": 9},
    }


async def test_append_note_append_only_bad_tail_readback_fails(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/LOGS.md",
        headers={"Content-Length": "5"},
    )
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:27123/vault/Projects/foo/LOGS.md",
        status_code=204,
    )
    httpx_mock.add_response(
        method="HEAD",
        url="http://127.0.0.1:27123/vault/Projects/foo/LOGS.md",
        headers={"Content-Length": "9"},
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/Projects/foo/LOGS.md",
        text="wrong body",
        headers={"Content-Length": "10"},
    )

    result = await append_note(ctx, path="Projects/foo/LOGS.md", content="tail")
    assert _error_code(result) == ErrorCode.APPEND_VERIFICATION_FAILED


async def test_list_notes_root_filters_hidden_entries(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault//",
        json={
            "files": [
                {"name": ".obsidian", "path": ".obsidian/", "is_dir": True, "size": None},
                {"name": "Projects", "path": "Projects/", "is_dir": True, "size": None},
                {"name": "LOGS.md", "path": "LOGS.md", "is_dir": False, "size": 12},
            ]
        },
    )

    result = await list_notes(ctx)

    assert result == {
        "ok": True,
        "data": {
            "entries": [
                {"path": "Projects/", "type": "folder", "size": None},
                {"path": "LOGS.md", "type": "file", "size": 12},
            ]
        },
    }


async def test_list_notes_subdir_validation(ctx: ToolContext) -> None:
    result = await list_notes(ctx, path=".obsidian", recursive=False)
    assert _error_code(result) == ErrorCode.PATH_FORBIDDEN_HIDDEN_FILE


async def test_list_notes_recursive_depth_cap_behavior(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
    tmp_path: Path,
) -> None:
    current = tmp_path
    for level in range(1, 11):
        current = current / f"level{level}"
        current.mkdir(parents=True, exist_ok=True)

    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/",
        json={
            "files": [
                {"name": "level2", "path": "level1/level2/", "is_dir": True, "size": None}
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/level2/",
        json={
            "files": [
                {"name": "level3", "path": "level1/level2/level3/", "is_dir": True, "size": None}
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/level2/level3/",
        json={
            "files": [
                {
                    "name": "level4",
                    "path": "level1/level2/level3/level4/",
                    "is_dir": True,
                    "size": None,
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/level2/level3/level4/",
        json={
            "files": [
                {
                    "name": "level5",
                    "path": "level1/level2/level3/level4/level5/",
                    "is_dir": True,
                    "size": None,
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/level2/level3/level4/level5/",
        json={
            "files": [
                {
                    "name": "level6",
                    "path": "level1/level2/level3/level4/level5/level6/",
                    "is_dir": True,
                    "size": None,
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/level2/level3/level4/level5/level6/",
        json={
            "files": [
                {
                    "name": "level7",
                    "path": "level1/level2/level3/level4/level5/level6/level7/",
                    "is_dir": True,
                    "size": None,
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/level2/level3/level4/level5/level6/level7/",
        json={
            "files": [
                {
                    "name": "level8",
                    "path": "level1/level2/level3/level4/level5/level6/level7/level8/",
                    "is_dir": True,
                    "size": None,
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/level1/level2/level3/level4/level5/level6/level7/level8/",
        json={
            "files": [
                {
                    "name": "level9",
                    "path": "level1/level2/level3/level4/level5/level6/level7/level8/level9/",
                    "is_dir": True,
                    "size": None,
                }
            ]
        },
    )

    result = await list_notes(ctx, path="level1", recursive=True)

    assert result["ok"] is True
    paths = [entry["path"] for entry in result["data"]["entries"]]
    assert "level1/level2/level3/level4/level5/level6/level7/level8/level9/" in paths
    assert len(httpx_mock.get_requests()) == EXPECTED_RECURSIVE_REQUESTS


async def test_search_vault_empty_query_rejected(ctx: ToolContext) -> None:
    result = await search_vault(ctx, query="   ")
    assert _error_code(result) == ErrorCode.VALIDATION_ERROR


async def test_search_vault_oversized_query_rejected(ctx: ToolContext) -> None:
    result = await search_vault(ctx, query="a" * (MAX_SEARCH_QUERY_CHARS + 1))
    assert _error_code(result) == ErrorCode.VALIDATION_ERROR


async def test_search_vault_happy_path_returns_capped_results(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
) -> None:
    snippet = "x" * (MAX_SEARCH_SNIPPET_CHARS + 25)
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:27123/search/simple/?query=needle",
        json=[
            {"path": "Projects/foo/PROJECT.md", "snippet": snippet, "line": 2},
            {"path": "Projects/foo/SUMMARY.md", "snippet": "second", "line": 3},
        ],
    )

    result = await search_vault(ctx, query="needle", max_results=1)

    assert result["ok"] is True
    assert result["data"]["truncated"] is True
    assert len(result["data"]["hits"]) == 1
    assert len(result["data"]["hits"][0]["snippet"]) == MAX_SEARCH_SNIPPET_CHARS


async def test_search_vault_path_prefix_filters_hits(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
    tmp_path: Path,
) -> None:
    (tmp_path / "Projects" / "foo").mkdir(parents=True)
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:27123/search/simple/?query=needle",
        json=[
            {"path": "Projects/foo/PROJECT.md", "snippet": "keep", "line": 1},
            {"path": "Projects/bar/PROJECT.md", "snippet": "drop", "line": 2},
        ],
    )

    result = await search_vault(ctx, query="needle", path_prefix="Projects/foo")

    assert result == {
        "ok": True,
        "data": {
            "hits": [
                {
                    "path": "Projects/foo/PROJECT.md",
                    "snippet": "keep",
                    "line": 1,
                    "match_type": "content",
                }
            ],
            "truncated": False,
        },
    }


async def test_search_vault_detects_filename_vs_content_matches(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:27123/search/simple/?query=project",
        json=[
            {"path": "Projects/foo/project-notes.md", "snippet": "body hit", "line": 9},
            {"path": "Projects/foo/SUMMARY.md", "snippet": "mentions project", "line": 4},
        ],
    )

    result = await search_vault(ctx, query="project")

    assert result == {
        "ok": True,
        "data": {
            "hits": [
                {
                    "path": "Projects/foo/project-notes.md",
                    "snippet": "body hit",
                    "line": None,
                    "match_type": "filename",
                },
                {
                    "path": "Projects/foo/SUMMARY.md",
                    "snippet": "mentions project",
                    "line": 4,
                    "match_type": "content",
                },
            ],
            "truncated": False,
        },
    }


async def test_search_vault_caps_max_results_to_global_limit(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
) -> None:
    hits = [
        {"path": f"Projects/foo/file-{index}.md", "snippet": "hit", "line": index}
        for index in range(MAX_SEARCH_RESULTS + 5)
    ]
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:27123/search/simple/?query=needle",
        json=hits,
    )

    result = await search_vault(ctx, query="needle", max_results=MAX_SEARCH_RESULTS + 50)

    assert result["ok"] is True
    assert len(result["data"]["hits"]) == MAX_SEARCH_RESULTS
    assert result["data"]["truncated"] is True


async def test_read_note_redacts_api_key_from_http_error(
    ctx: ToolContext,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="http://127.0.0.1:27123/vault/Projects/foo/PROJECT.md",
        status_code=500,
        text=f"failure {TEST_API_KEY}",
    )

    result = await read_note(ctx, path="Projects/foo/PROJECT.md")

    assert result["ok"] is False
    error_text = str(result["error"])
    assert TEST_API_KEY not in error_text
