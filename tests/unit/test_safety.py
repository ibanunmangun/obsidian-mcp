from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_mcp_opencode.errors import ErrorCode, MCPError
from obsidian_mcp_opencode.safety import (
    assert_writable,
    is_append_only,
    is_protected_memory,
    match_write_pattern,
    validate_slug,
    validate_vault_path,
)


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
    assert match_write_pattern(path) is True


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
    assert match_write_pattern(path) is False


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
    assert is_append_only(path) is expected


def test_is_protected_memory_only_matches_pipeline_index() -> None:
    assert is_protected_memory("Projects/PIPELINE_INDEX.md") is True
    assert is_protected_memory("Projects/foo/PROJECT.md") is False


def test_assert_writable_rejects_mistake_log_generic_write() -> None:
    with pytest.raises(MCPError) as exc_info:
        assert_writable("Freya - Mistake Log.md", allow_overwrite=False, is_append=False)

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN_USE_SPECIALIZED_TOOL


def test_assert_writable_rejects_append_only_overwrite() -> None:
    with pytest.raises(MCPError) as exc_info:
        assert_writable("Projects/foo/LOGS.md", allow_overwrite=True, is_append=False)

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN_APPEND_ONLY


def test_assert_writable_rejects_protected_memory_overwrite() -> None:
    with pytest.raises(MCPError) as exc_info:
        assert_writable("Projects/PIPELINE_INDEX.md", allow_overwrite=True, is_append=False)

    assert exc_info.value.code == ErrorCode.PATH_FORBIDDEN
