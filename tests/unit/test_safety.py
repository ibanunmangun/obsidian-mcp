from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_mcp_opencode.config import (
    FREYA_APPEND_ONLY_PATTERNS,
    FREYA_PROTECTED_MEMORY_PATHS,
    FREYA_WRITE_PATTERNS,
    GENERIC_APPEND_ONLY_PATTERNS,
    GENERIC_PROTECTED_MEMORY_PATHS,
    GENERIC_WRITE_PATTERNS,
)
from obsidian_mcp_opencode.errors import ErrorCode, MCPError
from obsidian_mcp_opencode.safety import (
    assert_writable,
    is_append_only,
    is_protected_memory,
    match_write_pattern,
    validate_slug,
    validate_vault_path,
)

FREYA_ASSERT_KWARGS = {
    "write_patterns": FREYA_WRITE_PATTERNS,
    "append_only_patterns": FREYA_APPEND_ONLY_PATTERNS,
    "protected_memory_paths": FREYA_PROTECTED_MEMORY_PATHS,
    "mistake_log_filename": "Freya - Mistake Log.md",
    "enforce_reserved_segments": True,
}

GENERIC_ASSERT_KWARGS = {
    "write_patterns": GENERIC_WRITE_PATTERNS,
    "append_only_patterns": GENERIC_APPEND_ONLY_PATTERNS,
    "protected_memory_paths": GENERIC_PROTECTED_MEMORY_PATHS,
    "mistake_log_filename": None,
    "enforce_reserved_segments": False,
}


def test_validate_vault_path_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(MCPError) as exc_info:
        validate_vault_path(tmp_path, "")

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN


def test_validate_vault_path_rejects_absolute(tmp_path: Path) -> None:
    with pytest.raises(MCPError) as exc_info:
        validate_vault_path(tmp_path, "/etc/passwd")

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN


def test_validate_vault_path_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(MCPError) as exc_info:
        validate_vault_path(tmp_path, "../secret.md")

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN


def test_validate_vault_path_rejects_backslash(tmp_path: Path) -> None:
    with pytest.raises(MCPError) as exc_info:
        validate_vault_path(tmp_path, r"folder\note.md")

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN


def test_validate_vault_path_rejects_hidden_segment(tmp_path: Path) -> None:
    with pytest.raises(MCPError) as exc_info:
        validate_vault_path(tmp_path, ".obsidian/config")

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN_HIDDEN_FILE


def test_validate_vault_path_rejects_symlink(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    symlink_dir = tmp_path / "linked"
    symlink_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(MCPError) as exc_info:
        validate_vault_path(tmp_path, "linked/note.md")

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN_SYMLINK


def test_validate_vault_path_returns_resolved_path(tmp_path: Path) -> None:
    resolved = validate_vault_path(tmp_path, "folder/note.md")

    assert resolved == (tmp_path / "folder/note.md").resolve(strict=False)


def test_validate_slug_accepts_valid_slug() -> None:
    validate_slug("foo-bar")


@pytest.mark.parametrize("slug", ["Foo", "foo_bar", "-foo", "home", "a" * 81])
def test_validate_slug_rejects_invalid_values(slug: str) -> None:
    with pytest.raises(MCPError) as exc_info:
        validate_slug(slug)

    assert exc_info.value.code == ErrorCode.SLUG_INVALID


@pytest.mark.parametrize(
    "path",
    [
        "Projects/foo/PROJECT.md",
        "Projects/foo/docs/notes.md",
        "Freya - Mistake Log.md",
        "LOGS.md",
        "Projects/PIPELINE_INDEX.md",
        "Projects/foo/PREMORTEM-bar.md",
    ],
)
def test_match_write_pattern_positive_cases(path: str) -> None:
    assert match_write_pattern(path, FREYA_WRITE_PATTERNS) is True


@pytest.mark.parametrize(
    "path",
    [
        "Projects/foo/random.md",
        "Projects/Foo/PROJECT.md",
        "Projects/foo/docs/sub/x.md",
        "random.md",
        "Projects/home/PROJECT.md",
    ],
)
def test_match_write_pattern_negative_cases(path: str) -> None:
    assert match_write_pattern(path, FREYA_WRITE_PATTERNS) is False


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Freya - Mistake Log.md", True),
        ("LOGS.md", True),
        ("Projects/foo/LOGS.md", True),
        ("Projects/foo/PROJECT.md", False),
    ],
)
def test_is_append_only(path: str, expected: bool) -> None:
    assert is_append_only(path, FREYA_APPEND_ONLY_PATTERNS) is expected


def test_is_protected_memory_only_matches_pipeline_index() -> None:
    assert is_protected_memory("Projects/PIPELINE_INDEX.md", FREYA_PROTECTED_MEMORY_PATHS) is True
    assert is_protected_memory("Projects/foo/PROJECT.md", FREYA_PROTECTED_MEMORY_PATHS) is False


def test_assert_writable_rejects_mistake_log_generic_write() -> None:
    with pytest.raises(MCPError) as exc_info:
        assert_writable(
            "Freya - Mistake Log.md",
            allow_overwrite=False,
            is_append=False,
            **FREYA_ASSERT_KWARGS,
        )

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL


def test_assert_writable_rejects_append_only_overwrite() -> None:
    with pytest.raises(MCPError) as exc_info:
        assert_writable(
            "Projects/foo/LOGS.md",
            allow_overwrite=True,
            is_append=False,
            **FREYA_ASSERT_KWARGS,
        )

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN_APPEND_ONLY


def test_assert_writable_rejects_protected_memory_overwrite() -> None:
    with pytest.raises(MCPError) as exc_info:
        assert_writable(
            "Projects/PIPELINE_INDEX.md",
            allow_overwrite=True,
            is_append=False,
            **FREYA_ASSERT_KWARGS,
        )

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN


def test_generic_match_write_pattern_allows_any_markdown() -> None:
    assert match_write_pattern("notes/journal/2026-05.md", GENERIC_WRITE_PATTERNS) is True
    assert match_write_pattern("Projects/anything/whatever.md", GENERIC_WRITE_PATTERNS) is True


def test_generic_match_write_pattern_rejects_non_markdown() -> None:
    assert match_write_pattern("notes/journal/2026-05.txt", GENERIC_WRITE_PATTERNS) is False


def test_generic_mode_reserved_segments_not_enforced() -> None:
    assert (
        match_write_pattern(
            "Projects/home/whatever.md",
            GENERIC_WRITE_PATTERNS,
            enforce_reserved_segments=False,
        )
        is True
    )


def test_generic_mode_has_no_append_only_or_protected_paths() -> None:
    assert is_append_only("LOGS.md", GENERIC_APPEND_ONLY_PATTERNS) is False
    assert (
        is_protected_memory("Projects/PIPELINE_INDEX.md", GENERIC_PROTECTED_MEMORY_PATHS)
        is False
    )


def test_generic_assert_writable_allows_root_logs_when_not_overriden() -> None:
    assert_writable(
        "LOGS.md",
        allow_overwrite=True,
        is_append=False,
        **GENERIC_ASSERT_KWARGS,
    )
