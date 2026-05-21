from __future__ import annotations

from obsidian_mcp_opencode.config import (
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
from obsidian_mcp_opencode.safety import match_write_pattern
from obsidian_mcp_opencode.server import build_tool_registry

EXPECTED_GENERIC_REGISTRY_BASE = 5
EXPECTED_GENERIC_REGISTRY_WITH_MOVE = 6
EXPECTED_FREYA_REGISTRY_BASE = 10
EXPECTED_FREYA_REGISTRY_WITH_MOVE = 11


def test_generic_mode_allows_any_markdown_path() -> None:
    assert match_write_pattern("notes/journal/2026-05.md", GENERIC_WRITE_PATTERNS) is True
    assert match_write_pattern("Projects/anything/whatever.md", GENERIC_WRITE_PATTERNS) is True


def test_generic_mode_registry_has_five_or_six_tools(
    generic_config: Config,
) -> None:
    registry = build_tool_registry(generic_config)
    move_registry = build_tool_registry(
        Config(
            vault_path=generic_config.vault_path,
            api_key=generic_config.api_key,
            base_url=generic_config.base_url,
            log_level=generic_config.log_level,
            read_only=generic_config.read_only,
            allow_move=True,
            workflow=generic_config.workflow,
            write_patterns=generic_config.write_patterns,
            append_only_patterns=generic_config.append_only_patterns,
            protected_memory_paths=generic_config.protected_memory_paths,
        )
    )

    assert len(registry) == EXPECTED_GENERIC_REGISTRY_BASE
    assert len(move_registry) == EXPECTED_GENERIC_REGISTRY_WITH_MOVE


def test_generic_mode_does_not_register_freya_specific_tools(
    generic_config: Config,
) -> None:
    names = {descriptor.name for descriptor in build_tool_registry(generic_config)}

    assert "get_mistake_log" not in names
    assert "append_mistake_log" not in names
    assert "get_pipeline_index" not in names
    assert "search_projects" not in names
    assert "bootstrap_project" not in names


def test_generic_mode_has_no_append_only_or_protected_paths_by_default(
    generic_config: Config,
) -> None:
    assert generic_config.workflow == WORKFLOW_GENERIC
    assert generic_config.append_only_patterns == tuple(GENERIC_APPEND_ONLY_PATTERNS)
    assert generic_config.protected_memory_paths == tuple(GENERIC_PROTECTED_MEMORY_PATHS)


def test_generic_mode_reserved_segments_not_enforced() -> None:
    assert (
        match_write_pattern(
            "Projects/home/whatever.md",
            GENERIC_WRITE_PATTERNS,
            enforce_reserved_segments=False,
        )
        is True
    )


def test_freya_mode_registry_has_ten_or_eleven_tools(
    freya_config: Config,
) -> None:
    registry = build_tool_registry(freya_config)
    move_registry = build_tool_registry(
        Config(
            vault_path=freya_config.vault_path,
            api_key=freya_config.api_key,
            base_url=freya_config.base_url,
            log_level=freya_config.log_level,
            read_only=freya_config.read_only,
            allow_move=True,
            workflow=freya_config.workflow,
            write_patterns=freya_config.write_patterns,
            append_only_patterns=freya_config.append_only_patterns,
            protected_memory_paths=freya_config.protected_memory_paths,
        )
    )

    assert len(registry) == EXPECTED_FREYA_REGISTRY_BASE
    assert len(move_registry) == EXPECTED_FREYA_REGISTRY_WITH_MOVE


def test_freya_mode_preserves_v020_pattern_behavior(freya_config: Config) -> None:
    assert freya_config.workflow == WORKFLOW_FREYA
    assert list(freya_config.write_patterns) == FREYA_WRITE_PATTERNS
    assert list(freya_config.append_only_patterns) == FREYA_APPEND_ONLY_PATTERNS
    assert list(freya_config.protected_memory_paths) == FREYA_PROTECTED_MEMORY_PATHS
    assert match_write_pattern("Projects/foo/PROJECT.md", freya_config.write_patterns) is True
    assert match_write_pattern("Projects/foo/random.md", freya_config.write_patterns) is False
