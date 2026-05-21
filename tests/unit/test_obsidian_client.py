from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from obsidian_mcp_opencode.config import Config
from obsidian_mcp_opencode.errors import ErrorCode, MCPError
from obsidian_mcp_opencode.obsidian_client import ObsidianClient

TEST_API_KEY = "token-abcdefghijklmnopqrstuvwxyz-1234567890"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        vault_path=tmp_path,
        api_key=TEST_API_KEY,
        base_url="http://127.0.0.1:27123",
        log_level="INFO",
        read_only=False,
        allow_move=False,
    )


async def test_get_file_maps_401_to_api_unauthorized(
    config: Config,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(status_code=401)
    client = ObsidianClient(config)

    with pytest.raises(MCPError) as exc_info:
        await client.get_file("Projects/foo/PROJECT.md")

    await client.aclose()
    assert exc_info.value.code == ErrorCode.API_UNAUTHORIZED


async def test_get_file_maps_connect_error_to_api_unreachable(
    config: Config,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    client = ObsidianClient(config)

    with pytest.raises(MCPError) as exc_info:
        await client.get_file("Projects/foo/PROJECT.md")

    await client.aclose()
    assert exc_info.value.code == ErrorCode.API_UNREACHABLE


async def test_get_file_maps_404_to_path_not_found(config: Config, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=404)
    client = ObsidianClient(config)

    with pytest.raises(MCPError) as exc_info:
        await client.get_file("Projects/foo/PROJECT.md")

    await client.aclose()
    assert exc_info.value.code == ErrorCode.PATH_NOT_FOUND


async def test_get_file_redacts_api_key_from_5xx_error(
    config: Config,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(status_code=500, text=f"server exploded {TEST_API_KEY}")
    client = ObsidianClient(config)

    with pytest.raises(MCPError) as exc_info:
        await client.get_file("Projects/foo/PROJECT.md")

    await client.aclose()
    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
    assert TEST_API_KEY not in exc_info.value.message
    assert TEST_API_KEY not in str(exc_info.value.details)


async def test_authorization_header_is_sent(config: Config, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=200, text="hello")
    client = ObsidianClient(config)

    await client.get_file("Projects/foo/PROJECT.md")

    request = httpx_mock.get_requests()[0]
    await client.aclose()
    assert request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"


async def test_api_key_never_appears_in_caplog(
    config: Config,
    httpx_mock: HTTPXMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    httpx_mock.add_response(status_code=500, text=f"error {TEST_API_KEY}")
    client = ObsidianClient(config)

    with pytest.raises(MCPError):
        await client.get_file("Projects/foo/PROJECT.md")

    await client.aclose()
    assert TEST_API_KEY not in caplog.text


@pytest.mark.parametrize(
    ("method_name", "method_args"),
    [
        ("put_file", ("Projects/foo/PROJECT.md", "body")),
        ("append_file", ("Projects/foo/LOGS.md", "body")),
        ("delete_file", ("Projects/foo/PROJECT.md",)),
        ("list_directory", ("Projects/foo",)),
        ("search", ("needle",)),
        ("stat", ("Projects/foo/PROJECT.md",)),
    ],
)
async def test_methods_map_401_to_api_unauthorized(
    config: Config,
    httpx_mock: HTTPXMock,
    method_name: str,
    method_args: tuple[str, ...],
) -> None:
    httpx_mock.add_response(status_code=401)
    client = ObsidianClient(config)

    method = getattr(client, method_name)
    with pytest.raises(MCPError) as exc_info:
        await method(*method_args)

    await client.aclose()
    assert exc_info.value.code == ErrorCode.API_UNAUTHORIZED


@pytest.mark.parametrize(
    ("method_name", "method_args"),
    [
        ("put_file", ("Projects/foo/PROJECT.md", "body")),
        ("append_file", ("Projects/foo/LOGS.md", "body")),
        ("delete_file", ("Projects/foo/PROJECT.md",)),
        ("list_directory", ("Projects/foo",)),
        ("search", ("needle",)),
        ("stat", ("Projects/foo/PROJECT.md",)),
    ],
)
async def test_methods_map_connect_error_to_api_unreachable(
    config: Config,
    httpx_mock: HTTPXMock,
    method_name: str,
    method_args: tuple[str, ...],
) -> None:
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    client = ObsidianClient(config)

    method = getattr(client, method_name)
    with pytest.raises(MCPError) as exc_info:
        await method(*method_args)

    await client.aclose()
    assert exc_info.value.code == ErrorCode.API_UNREACHABLE


@pytest.mark.parametrize(
    ("method_name", "method_args"),
    [
        ("put_file", ("Projects/foo/PROJECT.md", "body")),
        ("append_file", ("Projects/foo/LOGS.md", "body")),
        ("delete_file", ("Projects/foo/PROJECT.md",)),
        ("list_directory", ("Projects/foo",)),
        ("search", ("needle",)),
        ("stat", ("Projects/foo/PROJECT.md",)),
    ],
)
async def test_methods_redact_api_key_from_5xx_errors(
    config: Config,
    httpx_mock: HTTPXMock,
    method_name: str,
    method_args: tuple[str, ...],
) -> None:
    httpx_mock.add_response(status_code=500, text=f"failure {TEST_API_KEY}")
    client = ObsidianClient(config)

    method = getattr(client, method_name)
    with pytest.raises(MCPError) as exc_info:
        await method(*method_args)

    await client.aclose()
    assert TEST_API_KEY not in exc_info.value.message
    assert TEST_API_KEY not in str(exc_info.value.details)
