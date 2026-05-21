from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .config import REQUEST_TIMEOUT_SECONDS, Config
from .errors import ErrorCode, MCPError, redact_token, redact_token_patterns

HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_HEAD_UNSUPPORTED = frozenset({405, 501})


class ObsidianClient:
    def __init__(self, config: Config) -> None:
        """Build httpx.AsyncClient with bearer auth header. Token NEVER logged."""

        self._config = config
        verify: bool | str = False if config.base_url.startswith("https://") else True
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {config.api_key}"},
            verify=verify,
            event_hooks=None,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _safe_body(self, body: str) -> str:
        redacted = redact_token(body, self._config.api_key)
        return redact_token_patterns(redacted)

    def _map_http_error(
        self,
        operation: str,
        path: str,
        *,
        response: httpx.Response | None = None,
        exc: Exception | None = None,
    ) -> MCPError:
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
            return MCPError(
                ErrorCode.API_UNREACHABLE,
                f"{operation} failed: Obsidian API unreachable at {self._config.base_url}",
                {"path": path, "timeout": REQUEST_TIMEOUT_SECONDS},
            )

        if response is None:
            return MCPError(
                ErrorCode.INTERNAL_ERROR,
                f"{operation} failed unexpectedly",
                {"path": path},
            )

        if response.status_code == HTTP_STATUS_UNAUTHORIZED:
            return MCPError(
                ErrorCode.API_UNAUTHORIZED,
                f"{operation} failed: unauthorized",
                {"path": path},
            )
        if response.status_code == HTTP_STATUS_NOT_FOUND and operation == "get_file":
            return MCPError(
                ErrorCode.PATH_NOT_FOUND,
                "Vault path not found",
                {"path": path},
            )

        safe_body = self._safe_body(response.text)
        return MCPError(
            ErrorCode.INTERNAL_ERROR,
            f"{operation} failed with status {response.status_code}",
            {"path": path, "status_code": response.status_code, "body": safe_body},
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        content: str | None = None,
        operation: str | None = None,
    ) -> httpx.Response:
        operation_name = operation or method.lower()
        kwargs: dict[str, Any] = {}
        if content is not None:
            kwargs["content"] = content.encode("utf-8")
            kwargs["headers"] = {"Content-Type": "text/markdown; charset=utf-8"}
        try:
            response = await self._client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise self._map_http_error(operation_name, url, exc=exc) from exc

        if response.status_code >= HTTP_STATUS_BAD_REQUEST:
            raise self._map_http_error(operation_name, url, response=response)

        return response

    def _vault_path_url(self, vault_relative_path: str, *, directory: bool = False) -> str:
        encoded = quote(vault_relative_path, safe="/")
        suffix = "/" if directory else ""
        return f"/vault/{encoded}{suffix}"

    @staticmethod
    def _extract_metadata(response: httpx.Response) -> dict[str, Any]:
        size_header = response.headers.get("Content-Length")
        mtime_header = response.headers.get("Last-Modified") or response.headers.get(
            "X-Last-Modified"
        )
        size = int(size_header) if size_header is not None and size_header.isdigit() else None
        mtime = float(mtime_header) if mtime_header is not None else None
        return {"size": size, "mtime": mtime}

    async def get_file(self, vault_relative_path: str) -> tuple[str, dict[str, Any]]:
        response = await self._request(
            "GET",
            self._vault_path_url(vault_relative_path),
            operation="get_file",
        )
        return response.text, self._extract_metadata(response)

    async def put_file(self, vault_relative_path: str, content: str) -> None:
        await self._request(
            "PUT",
            self._vault_path_url(vault_relative_path),
            content=content,
            operation="put_file",
        )

    async def append_file(self, vault_relative_path: str, content: str) -> None:
        await self._request(
            "POST",
            self._vault_path_url(vault_relative_path),
            content=content,
            operation="append_file",
        )

    async def list_directory(self, vault_relative_path: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            self._vault_path_url(vault_relative_path, directory=True),
            operation="list_directory",
        )
        data = response.json()
        entries = data.get("files") if isinstance(data, dict) else data
        normalized: list[dict[str, Any]] = []
        for entry in entries or []:
            # Plugin v4 returns either bare strings (filenames, with trailing "/" for folders)
            # or dicts with explicit fields. Normalize both shapes.
            if isinstance(entry, str):
                raw_path = entry
                is_dir = raw_path.endswith("/")
                name = raw_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
                normalized.append(
                    {
                        "name": name,
                        "path": raw_path,
                        "is_dir": is_dir,
                        "size": None,
                        "mtime": None,
                    }
                )
                continue

            path = entry.get("path") or entry.get("filename") or entry.get("name")
            name = entry.get("name") or (
                path.rsplit("/", maxsplit=1)[-1] if isinstance(path, str) else ""
            )
            is_dir = bool(
                entry.get("is_dir") or entry.get("type") == "folder" or str(path).endswith("/")
            )
            normalized.append(
                {
                    "name": name,
                    "path": path,
                    "is_dir": is_dir,
                    "size": entry.get("size"),
                    "mtime": entry.get("mtime"),
                }
            )
        return normalized

    async def search(self, query: str) -> list[dict[str, Any]]:
        try:
            response = await self._client.post("/search/simple/", params={"query": query})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise self._map_http_error("search", "/search/simple/", exc=exc) from exc

        if response.status_code >= HTTP_STATUS_BAD_REQUEST:
            raise self._map_http_error("search", "/search/simple/", response=response)

        data = response.json()
        if isinstance(data, dict):
            hits = data.get("files") or data.get("results") or data.get("hits") or []
            return hits if isinstance(hits, list) else []
        return data if isinstance(data, list) else []

    async def stat(self, vault_relative_path: str) -> dict[str, Any]:
        url = self._vault_path_url(vault_relative_path)
        try:
            response = await self._client.head(url)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise self._map_http_error("stat", url, exc=exc) from exc

        if response.status_code == HTTP_STATUS_NOT_FOUND:
            return {"exists": False, "size": None, "mtime": None}
        if response.status_code in HTTP_STATUS_HEAD_UNSUPPORTED:
            content, metadata = await self.get_file(vault_relative_path)
            return {
                "exists": True,
                "size": metadata.get("size") or len(content.encode("utf-8")),
                "mtime": metadata.get("mtime"),
            }
        if response.status_code >= HTTP_STATUS_BAD_REQUEST:
            raise self._map_http_error("stat", url, response=response)

        metadata = self._extract_metadata(response)
        return {"exists": True, "size": metadata["size"], "mtime": metadata["mtime"]}
