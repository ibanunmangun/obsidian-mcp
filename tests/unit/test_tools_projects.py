from __future__ import annotations

from pathlib import Path

import httpx
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
from obsidian_mcp_opencode.tools.projects import (
    ToolContext,
    bootstrap_project,
    get_pipeline_index,
    search_projects,
)

TEST_API_KEY = "token-abcdefghijklmnopqrstuvwxyz-1234567890"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    config = Config(
        vault_path=tmp_path,
        api_key=TEST_API_KEY,
        base_url="http://127.0.0.1:27123",
        log_level="INFO",
        read_only=False,
        allow_move=False,
    )
    client = ObsidianClient(config)
    locks = LockRegistry()
    return ToolContext(client=client, config=config, locks=locks)


async def test_get_pipeline_index_missing_returns_exists_false(ctx: ToolContext) -> None:
    async def fake_get_file(path: str) -> tuple[str, dict]:
        raise ctx.client._map_http_error("get_file", path, response=httpx.Response(status_code=404))

    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]

    result = await get_pipeline_index(ctx)

    await ctx.client.aclose()
    assert result == {"ok": True, "data": {"content": "", "exists": False}}


async def test_get_pipeline_index_present_returns_content(ctx: ToolContext) -> None:
    async def fake_get_file(path: str) -> tuple[str, dict]:
        assert path == "Projects/PIPELINE_INDEX.md"
        return "pipeline body", {"size": 13, "mtime": 123.0}

    ctx.client.get_file = fake_get_file  # type: ignore[method-assign]

    result = await get_pipeline_index(ctx)

    await ctx.client.aclose()
    assert result == {"ok": True, "data": {"content": "pipeline body", "exists": True}}


async def test_get_pipeline_index_api_unreachable_propagates(
    ctx: ToolContext, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_exception(httpx.ConnectError("boom"))

    result = await get_pipeline_index(ctx)

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.API_UNREACHABLE


async def test_get_pipeline_index_redacts_token_on_http_error(
    ctx: ToolContext, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(status_code=500, text=f"failure {TEST_API_KEY}")

    result = await get_pipeline_index(ctx)

    await ctx.client.aclose()
    assert result["ok"] is False
    assert TEST_API_KEY not in str(result)


async def test_search_projects_rejects_empty_query(ctx: ToolContext) -> None:
    result = await search_projects(ctx, query="")

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR


async def test_search_projects_rejects_oversized_query(ctx: ToolContext) -> None:
    result = await search_projects(ctx, query="a" * (MAX_SEARCH_QUERY_CHARS + 1))

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR


async def test_search_projects_filters_and_infers_project_slug(ctx: ToolContext) -> None:
    long_snippet = "x" * (MAX_SEARCH_SNIPPET_CHARS + 25)

    async def fake_search(query: str) -> list[dict]:
        assert query == "project"
        return [
            {"path": "Notes/random.md", "snippet": "outside"},
            {"path": "Projects/foo/.git/x.md", "snippet": "hidden"},
            {"path": "Projects/home/PROJECT.md", "snippet": "reserved"},
            {"path": "Projects/Foo/PROJECT.md", "snippet": "invalid slug"},
            {"path": "Projects/PIPELINE_INDEX.md", "snippet": "pipeline"},
            {"path": "Projects/foo/PROJECT.md", "snippet": long_snippet},
            {"path": "Projects/foo/notes.md", "snippet": "body match only"},
        ]

    ctx.client.search = fake_search  # type: ignore[method-assign]

    result = await search_projects(ctx, query="project")

    await ctx.client.aclose()
    assert result["ok"] is True
    assert result["data"]["truncated"] is False
    assert result["data"]["hits"] == [
        {
            "project_slug": "_pipeline_index",
            "path": "Projects/PIPELINE_INDEX.md",
            "snippet": "pipeline",
            "match_type": "content",
        },
        {
            "project_slug": "foo",
            "path": "Projects/foo/PROJECT.md",
            "snippet": long_snippet[:MAX_SEARCH_SNIPPET_CHARS],
            "match_type": "filename",
        },
        {
            "project_slug": "foo",
            "path": "Projects/foo/notes.md",
            "snippet": "body match only",
            "match_type": "content",
        },
    ]


async def test_search_projects_caps_max_results_and_sets_truncated(ctx: ToolContext) -> None:
    async def fake_search(query: str) -> list[dict]:
        return [
            {"path": f"Projects/foo/note-{index}.md", "snippet": f"snippet {index}"}
            for index in range(MAX_SEARCH_RESULTS + 5)
        ]

    ctx.client.search = fake_search  # type: ignore[method-assign]

    result = await search_projects(ctx, query="note", max_results=MAX_SEARCH_RESULTS + 50)

    await ctx.client.aclose()
    assert result["ok"] is True
    assert len(result["data"]["hits"]) == MAX_SEARCH_RESULTS
    assert result["data"]["truncated"] is True


async def test_bootstrap_project_rejects_read_only(ctx: ToolContext) -> None:
    readonly_ctx = ToolContext(
        client=ctx.client,
        config=Config(
            vault_path=ctx.config.vault_path,
            api_key=ctx.config.api_key,
            base_url=ctx.config.base_url,
            log_level=ctx.config.log_level,
            read_only=True,
            allow_move=False,
        ),
        locks=ctx.locks,
    )

    result = await bootstrap_project(readonly_ctx, slug="foo")

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.READ_ONLY_MODE_ENABLED


@pytest.mark.parametrize(
    "slug",
    ["Foo", "home", "-foo", "foo_bar", "a" * 81, "foo/bar", ".."],
)
async def test_bootstrap_project_rejects_invalid_slugs(ctx: ToolContext, slug: str) -> None:
    result = await bootstrap_project(ctx, slug=slug)

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.SLUG_INVALID


async def test_bootstrap_project_rejects_existing_local_directory(ctx: ToolContext) -> None:
    existing = ctx.config.vault_path / "Projects" / "existing-project"
    existing.mkdir(parents=True)

    result = await bootstrap_project(ctx, slug="existing-project")

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.PROJECT_ALREADY_EXISTS


async def test_bootstrap_project_rejects_unknown_file_key(ctx: ToolContext) -> None:
    async def fake_stat(path: str) -> dict:
        return {"exists": False, "size": None, "mtime": None}

    ctx.client.stat = fake_stat  # type: ignore[method-assign]

    result = await bootstrap_project(ctx, slug="foo", files={"unknown": "value"})

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert result["error"]["details"]["unknown_keys"] == ["unknown"]


async def test_bootstrap_project_subset_files_written_in_canonical_order(ctx: ToolContext) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_stat(path: str) -> dict:
        if path == "Projects/foo/PROJECT.md":
            if not calls:
                return {"exists": False, "size": None, "mtime": None}
            return {"exists": True, "size": 7, "mtime": 1.0}
        if path == "Projects/foo/LOGS.md":
            return {"exists": True, "size": 4, "mtime": 1.0}
        return {"exists": False, "size": None, "mtime": None}

    async def fake_put_file(path: str, content: str) -> None:
        calls.append((path, content))

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]

    result = await bootstrap_project(
        ctx,
        slug="foo",
        files={"logs": "log!", "project": "project"},
    )

    await ctx.client.aclose()
    assert (ctx.config.vault_path / "Projects" / "foo").is_dir()
    assert calls == [
        ("Projects/foo/PROJECT.md", "project"),
        ("Projects/foo/LOGS.md", "log!"),
    ]
    assert result == {
        "ok": True,
        "data": {
            "created_directory": "Projects/foo/",
            "created_files": ["Projects/foo/PROJECT.md", "Projects/foo/LOGS.md"],
        },
    }


async def test_bootstrap_project_creates_directory_with_no_files(ctx: ToolContext) -> None:
    async def fake_stat(path: str) -> dict:
        return {"exists": False, "size": None, "mtime": None}

    ctx.client.stat = fake_stat  # type: ignore[method-assign]

    result = await bootstrap_project(ctx, slug="foo")

    await ctx.client.aclose()
    assert result == {
        "ok": True,
        "data": {"created_directory": "Projects/foo/", "created_files": []},
    }
    assert (ctx.config.vault_path / "Projects" / "foo").is_dir()


async def test_bootstrap_project_writes_all_supported_files(ctx: ToolContext) -> None:
    writes: list[str] = []

    async def fake_stat(path: str) -> dict:
        if path == "Projects/foo/PROJECT.md" and not writes:
            return {"exists": False, "size": None, "mtime": None}
        return {"exists": True, "size": 1, "mtime": 1.0}

    async def fake_put_file(path: str, content: str) -> None:
        writes.append(path)

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]

    result = await bootstrap_project(
        ctx,
        slug="foo",
        files={
            "project": "1",
            "summary": "2",
            "logs": "3",
            "prd": "4",
            "design": "5",
            "research": "6",
            "premortem": "7",
        },
    )

    await ctx.client.aclose()
    assert writes == [
        "Projects/foo/PROJECT.md",
        "Projects/foo/SUMMARY.md",
        "Projects/foo/LOGS.md",
        "Projects/foo/PRD.md",
        "Projects/foo/DESIGN.md",
        "Projects/foo/RESEARCH.md",
        "Projects/foo/PREMORTEM.md",
    ]
    assert result["ok"] is True
    assert result["data"]["created_files"] == writes


async def test_bootstrap_project_fails_when_post_write_verification_fails(ctx: ToolContext) -> None:
    writes: list[str] = []

    async def fake_stat(path: str) -> dict:
        if path == "Projects/foo/PROJECT.md" and not writes:
            return {"exists": False, "size": None, "mtime": None}
        return {"exists": False, "size": None, "mtime": None}

    async def fake_put_file(path: str, content: str) -> None:
        writes.append(path)

    ctx.client.stat = fake_stat  # type: ignore[method-assign]
    ctx.client.put_file = fake_put_file  # type: ignore[method-assign]

    result = await bootstrap_project(ctx, slug="foo", files={"project": "body"})

    await ctx.client.aclose()
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.WRITE_VERIFICATION_FAILED
    assert result["error"]["details"]["path"] == "Projects/foo/PROJECT.md"
