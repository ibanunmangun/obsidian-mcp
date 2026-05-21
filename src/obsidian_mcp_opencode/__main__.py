from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import DEFAULT_LOG_LEVEL, load_config
from .errors import ConfigError, MCPError
from .server import serve_stdio


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obsidian-mcp-opencode",
        description="Python MCP server for Obsidian vault access via Local REST API.",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable all write tools. Read tools continue to work.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to .env file. Overrides default search order.",
    )
    parser.add_argument(
        "--allow-move",
        action="store_true",
        help=(
            "Enable the move_note tool. Off by default — when off, move_note is "
            "not registered with the MCP server and the LLM cannot see or call it."
        ),
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    log_level = DEFAULT_LOG_LEVEL
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        config = load_config(
            env_file=args.env_file,
            read_only=args.read_only,
            allow_move=args.allow_move,
        )
    except ConfigError as exc:
        print(f"obsidian-mcp-opencode: configuration error: {exc.message}", file=sys.stderr)
        sys.exit(1)

    logging.getLogger().setLevel(config.log_level)

    logging.getLogger(__name__).info(
        "Starting MCP server (vault=%s, base_url=%s, read_only=%s, allow_move=%s)",
        config.vault_path,
        config.base_url,
        config.read_only,
        config.allow_move,
    )

    try:
        asyncio.run(serve_stdio(config))
    except KeyboardInterrupt:
        sys.exit(0)
    except MCPError as exc:
        print(f"obsidian-mcp-opencode: fatal: {exc.message}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
