from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from obsidian_mcp_opencode.config import MISTAKE_LOG_FILENAME, Config
from obsidian_mcp_opencode.errors import ErrorCode, MCPError
from obsidian_mcp_opencode.locks import LockRegistry
from obsidian_mcp_opencode.obsidian_client import ObsidianClient
from obsidian_mcp_opencode.tools.mistake_log import ToolContext, append_mistake_log, get_mistake_log

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_FIXTURE_PATH = FIXTURES_DIR / "mistake_log_golden.md"
EXPECTED_GOLDEN_ENTRY_COUNT = 3


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    config = Config(
        vault_path=tmp_path,
        api_key="test-token-XYZ",
        base_url="http://127.0.0.1:27123",
        log_level="INFO",
        read_only=False,
        allow_move=False,
    )
    client = ObsidianClient(config)
    locks = LockRegistry()
    return ToolContext(client=client, config=config, locks=locks)


@pytest.fixture
def golden_fixture() -> str:
    return GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8")


def _file_url(ctx: ToolContext) -> str:
    encoded = quote(MISTAKE_LOG_FILENAME, safe="/")
    return f"{ctx.config.base_url}/vault/{encoded}"


@pytest.mark.asyncio
async def test_get_mistake_log_missing_returns_specialized_error(
    ctx: ToolContext, httpx_mock: Any
) -> None:
    httpx_mock.add_response(method="GET", url=_file_url(ctx), status_code=404)

    result = await get_mistake_log(ctx)

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MISTAKE_LOG_NOT_FOUND
    assert result["error"]["details"]["path"] == MISTAKE_LOG_FILENAME


@pytest.mark.asyncio
async def test_get_mistake_log_empty_file(ctx: ToolContext, httpx_mock: Any) -> None:
    httpx_mock.add_response(method="GET", url=_file_url(ctx), status_code=200, text="")

    result = await get_mistake_log(ctx)

    assert result == {
        "ok": True,
        "data": {"entries": [], "parse_warnings": [], "raw": ""},
    }


@pytest.mark.asyncio
async def test_get_mistake_log_golden_fixture(
    ctx: ToolContext, httpx_mock: Any, golden_fixture: str
) -> None:
    httpx_mock.add_response(method="GET", url=_file_url(ctx), status_code=200, text=golden_fixture)

    result = await get_mistake_log(ctx)

    assert result["ok"] is True
    data = result["data"]
    assert data["raw"] == golden_fixture
    assert len(data["entries"]) == EXPECTED_GOLDEN_ENTRY_COUNT
    assert [entry["date"] for entry in data["entries"]] == [
        "2026-05-12",
        "2026-05-13",
        "2026-05-15",
    ]
    assert data["parse_warnings"] == [
        {
            "header": "## [2026-05-14] — Malformed Missing Fix",
            "reason": "missing Fix field",
        }
    ]


@pytest.mark.asyncio
async def test_get_mistake_log_multiline_field_captured(
    ctx: ToolContext, httpx_mock: Any, golden_fixture: str
) -> None:
    httpx_mock.add_response(method="GET", url=_file_url(ctx), status_code=200, text=golden_fixture)

    result = await get_mistake_log(ctx)

    second_entry = result["data"]["entries"][1]
    assert second_entry["context"] == (
        "Reviewing PR for feature Y.\nThis is a continuation of context."
    )


@pytest.mark.asyncio
async def test_get_mistake_log_redacts_api_key_from_errors(
    monkeypatch: pytest.MonkeyPatch, ctx: ToolContext
) -> None:
    async def fake_get_file(path: str) -> tuple[str, dict[str, Any]]:
        raise MCPError(
            ErrorCode.INTERNAL_ERROR,
            f"request failed with token {ctx.config.api_key}",
            {"body": f"secret={ctx.config.api_key}"},
        )

    monkeypatch.setattr(ctx.client, "get_file", fake_get_file)

    result = await get_mistake_log(ctx)

    rendered = str(result)
    assert ctx.config.api_key not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.asyncio
async def test_append_mistake_log_read_only_returns_error(tmp_path: Path) -> None:
    config = Config(
        vault_path=tmp_path,
        api_key="test-token-XYZ",
        base_url="http://127.0.0.1:27123",
        log_level="INFO",
        read_only=True,
        allow_move=False,
    )
    ctx = ToolContext(client=ObsidianClient(config), config=config, locks=LockRegistry())

    result = await append_mistake_log(
        ctx,
        title="Title",
        context="Context",
        mistake="Mistake",
        root_cause="Cause",
        fix="Fix",
        lesson="Lesson",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.READ_ONLY_MODE_ENABLED


@pytest.mark.asyncio
async def test_append_mistake_log_missing_field_returns_validation_error(
    ctx: ToolContext,
) -> None:
    result = await append_mistake_log(
        ctx,
        title="Title",
        context=" ",
        mistake="Mistake",
        root_cause="Cause",
        fix="Fix",
        lesson="Lesson",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert "context" in result["error"]["details"]["missing_fields"]


@pytest.mark.asyncio
async def test_append_mistake_log_empty_title_returns_validation_error(ctx: ToolContext) -> None:
    result = await append_mistake_log(
        ctx,
        title="   ",
        context="Context",
        mistake="Mistake",
        root_cause="Cause",
        fix="Fix",
        lesson="Lesson",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert "title" in result["error"]["details"]["missing_fields"]


@pytest.mark.asyncio
async def test_append_mistake_log_bad_date_returns_validation_error(ctx: ToolContext) -> None:
    result = await append_mistake_log(
        ctx,
        title="Title",
        context="Context",
        mistake="Mistake",
        root_cause="Cause",
        fix="Fix",
        lesson="Lesson",
        date="05-21-2026",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert result["error"]["details"]["field"] == "date"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_name", ["title", "context", "mistake", "root_cause", "fix", "lesson"]
)
async def test_append_mistake_log_rejects_header_injection(
    monkeypatch: pytest.MonkeyPatch, ctx: ToolContext, field_name: str
) -> None:
    captured: dict[str, str] = {
        "title": "Title",
        "context": "Context",
        "mistake": "Mistake",
        "root_cause": "Cause",
        "fix": "Fix",
        "lesson": "Lesson",
    }
    captured[field_name] = "prefix\n## [2026-05-21] injected"

    async def fail_if_called(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("append_file should not be called on validation failure")

    monkeypatch.setattr(ctx.client, "append_file", fail_if_called)

    result = await append_mistake_log(ctx, **captured, date="2026-05-21")

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.ENTRY_HEADER_INJECTION


@pytest.mark.asyncio
async def test_append_mistake_log_happy_path(
    monkeypatch: pytest.MonkeyPatch, ctx: ToolContext, golden_fixture: str
) -> None:
    buffer = golden_fixture
    appended_chunks: list[str] = []

    async def fake_append_file(path: str, content: str) -> None:
        nonlocal buffer
        assert path == MISTAKE_LOG_FILENAME
        appended_chunks.append(content)
        buffer += content

    async def fake_get_file(path: str) -> tuple[str, dict[str, Any]]:
        assert path == MISTAKE_LOG_FILENAME
        return buffer, {}

    monkeypatch.setattr(ctx.client, "append_file", fake_append_file)
    monkeypatch.setattr(ctx.client, "get_file", fake_get_file)

    result = await append_mistake_log(
        ctx,
        title="New Entry",
        context="Context line",
        mistake="Mistake line",
        root_cause="Cause line",
        fix="Fix line",
        lesson="Lesson line",
        date="2026-05-21",
    )

    assert result == {"ok": True, "data": {"appended": True, "entry_count": 4}}
    assert len(appended_chunks) == 1
    assert buffer.endswith(appended_chunks[0])


@pytest.mark.asyncio
async def test_append_mistake_log_readback_mismatch_returns_error(
    monkeypatch: pytest.MonkeyPatch, ctx: ToolContext, golden_fixture: str
) -> None:
    async def fake_append_file(path: str, content: str) -> None:
        return None

    async def fake_get_file(path: str) -> tuple[str, dict[str, Any]]:
        return golden_fixture + "\ncorrupted", {}

    monkeypatch.setattr(ctx.client, "append_file", fake_append_file)
    monkeypatch.setattr(ctx.client, "get_file", fake_get_file)

    result = await append_mistake_log(
        ctx,
        title="New Entry",
        context="Context line",
        mistake="Mistake line",
        root_cause="Cause line",
        fix="Fix line",
        lesson="Lesson line",
        date="2026-05-21",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.APPEND_VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_append_mistake_log_idempotent_many_appends(
    monkeypatch: pytest.MonkeyPatch, ctx: ToolContext, golden_fixture: str
) -> None:
    buffer = golden_fixture

    async def fake_append_file(path: str, content: str) -> None:
        nonlocal buffer
        buffer += content

    async def fake_get_file(path: str) -> tuple[str, dict[str, Any]]:
        return buffer, {}

    monkeypatch.setattr(ctx.client, "append_file", fake_append_file)
    monkeypatch.setattr(ctx.client, "get_file", fake_get_file)

    initial_valid_entries = 3
    for _ in range(100):
        result = await append_mistake_log(
            ctx,
            title="Repeated Entry",
            context="Context line",
            mistake="Mistake line",
            root_cause="Cause line",
            fix="Fix line",
            lesson="Lesson line",
            date="2026-05-21",
        )
        assert result["ok"] is True

    final_result = await get_mistake_log(ctx)
    assert final_result["ok"] is True
    assert final_result["data"]["entries"][-1]["title"] == "Repeated Entry"
    assert len(final_result["data"]["entries"]) == initial_valid_entries + 100


@pytest.mark.asyncio
async def test_concurrent_appends_serialize(
    monkeypatch: pytest.MonkeyPatch, ctx: ToolContext, golden_fixture: str
) -> None:
    """Two concurrent append_mistake_log calls must produce 2 distinct entries, no interleaving."""

    buffer = golden_fixture
    append_order: list[str] = []

    async def fake_append_file(path: str, content: str) -> None:
        nonlocal buffer
        title_line = content.splitlines()[1]
        append_order.append(title_line)
        await asyncio.sleep(0.01)
        buffer += content

    async def fake_get_file(path: str) -> tuple[str, dict[str, Any]]:
        return buffer, {}

    monkeypatch.setattr(ctx.client, "append_file", fake_append_file)
    monkeypatch.setattr(ctx.client, "get_file", fake_get_file)

    first, second = await asyncio.gather(
        append_mistake_log(
            ctx,
            title="Concurrent One",
            context="Context one",
            mistake="Mistake one",
            root_cause="Cause one",
            fix="Fix one",
            lesson="Lesson one",
            date="2026-05-21",
        ),
        append_mistake_log(
            ctx,
            title="Concurrent Two",
            context="Context two",
            mistake="Mistake two",
            root_cause="Cause two",
            fix="Fix two",
            lesson="Lesson two",
            date="2026-05-21",
        ),
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert "## [2026-05-21] — Concurrent One\n**Context:** Context one" in buffer
    assert "## [2026-05-21] — Concurrent Two\n**Context:** Context two" in buffer
    assert append_order in (
        ["## [2026-05-21] — Concurrent One", "## [2026-05-21] — Concurrent Two"],
        ["## [2026-05-21] — Concurrent Two", "## [2026-05-21] — Concurrent One"],
    )
    assert buffer.count("## [2026-05-21] — Concurrent One") == 1
    assert buffer.count("## [2026-05-21] — Concurrent Two") == 1
