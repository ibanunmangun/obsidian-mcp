from __future__ import annotations

import sys
from pathlib import Path

import pytest

from obsidian_mcp_opencode.config import (
    DEFAULT_BASE_URL,
    FREYA_APPEND_ONLY_PATTERNS,
    FREYA_PROTECTED_MEMORY_PATHS,
    FREYA_WRITE_PATTERNS,
    GENERIC_APPEND_ONLY_PATTERNS,
    GENERIC_PROTECTED_MEMORY_PATHS,
    GENERIC_WRITE_PATTERNS,
    WORKFLOW_FREYA,
    WORKFLOW_GENERIC,
    Config,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_API_KEY = "test-token-abcdefghijklmnopqrstuvwxyz-1234567890"


@pytest.fixture
def freya_config(tmp_path: Path) -> Config:
    return Config(
        vault_path=tmp_path,
        api_key=TEST_API_KEY,
        base_url=DEFAULT_BASE_URL,
        log_level="INFO",
        read_only=False,
        allow_move=False,
        workflow=WORKFLOW_FREYA,
        write_patterns=tuple(FREYA_WRITE_PATTERNS),
        append_only_patterns=tuple(FREYA_APPEND_ONLY_PATTERNS),
        protected_memory_paths=tuple(FREYA_PROTECTED_MEMORY_PATHS),
    )


@pytest.fixture
def generic_config(tmp_path: Path) -> Config:
    return Config(
        vault_path=tmp_path,
        api_key=TEST_API_KEY,
        base_url=DEFAULT_BASE_URL,
        log_level="INFO",
        read_only=False,
        allow_move=False,
        workflow=WORKFLOW_GENERIC,
        write_patterns=tuple(GENERIC_WRITE_PATTERNS),
        append_only_patterns=tuple(GENERIC_APPEND_ONLY_PATTERNS),
        protected_memory_paths=tuple(GENERIC_PROTECTED_MEMORY_PATHS),
    )
