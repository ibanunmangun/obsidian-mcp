from __future__ import annotations

import logging
from pathlib import Path

import pytest

from obsidian_mcp_opencode import config as config_module
from obsidian_mcp_opencode.config import DEFAULT_BASE_URL, Config, load_config
from obsidian_mcp_opencode.errors import ConfigError

TEST_API_KEY = "test-token-abcdefghijklmnopqrstuvwxyz-1234567890"


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate every test from the real environment AND the real config files.

    Without this, tests that expect a missing var would pick up the values from
    the developer's real ~/.config/obsidian-mcp-opencode/.env or project .env.
    """

    for key in ["OBSIDIAN_VAULT_PATH", "OBSIDIAN_API_KEY", "OBSIDIAN_BASE_URL", "LOG_LEVEL"]:
        monkeypatch.delenv(key, raising=False)
    # Redirect default env-file lookups to a guaranteed-missing location.
    nowhere = tmp_path / "no-such-config-dir" / ".env"
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", nowhere)
    monkeypatch.setattr(config_module, "PROJECT_ENV_FILE", nowhere)


def test_missing_vault_path_raises_config_error() -> None:
    with pytest.raises(ConfigError, match="OBSIDIAN_VAULT_PATH"):
        load_config()


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    file_path = tmp_path / ".env"
    file_path.write_text(
        f"OBSIDIAN_VAULT_PATH={tmp_path}\n"
        f"OBSIDIAN_API_KEY={TEST_API_KEY}\n"
        "OBSIDIAN_BASE_URL=http://localhost:9999\n"
        "LOG_LEVEL=debug\n",
        encoding="utf-8",
    )
    return file_path


def test_missing_api_key_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))

    with pytest.raises(ConfigError, match="OBSIDIAN_API_KEY"):
        load_config()


def test_relative_vault_path_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "relative/path")
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    with pytest.raises(ConfigError, match="absolute"):
        load_config()


def test_nonexistent_vault_path_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "missing"))
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    with pytest.raises(ConfigError, match="does not exist"):
        load_config()


def test_file_vault_path_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "vault.md"
    file_path.write_text("content", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(file_path))
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    with pytest.raises(ConfigError, match="directory"):
        load_config()


def test_symlink_vault_path_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    symlink_path = tmp_path / "vault-link"
    symlink_path.symlink_to(vault_dir, target_is_directory=True)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(symlink_path))
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    with pytest.raises(ConfigError, match="symlink"):
        load_config()


def test_valid_config_loads_successfully(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    config = load_config()

    assert config.vault_path == tmp_path.resolve()
    assert config.api_key == TEST_API_KEY
    assert config.base_url == DEFAULT_BASE_URL
    assert config.log_level == "INFO"
    assert config.read_only is False
    assert config.allow_move is False


def test_env_file_argument_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_file: Path,
) -> None:
    other_path = tmp_path / "other"
    other_path.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(other_path))
    monkeypatch.setenv("OBSIDIAN_API_KEY", "another-token")
    monkeypatch.setenv("OBSIDIAN_BASE_URL", "http://localhost:1111")

    config = load_config(env_file=env_file, read_only=True)

    assert config.vault_path == tmp_path.resolve()
    assert config.api_key == TEST_API_KEY
    assert config.base_url == "http://localhost:9999"
    assert config.log_level == "DEBUG"
    assert config.read_only is True


def test_config_allow_move_field_defaults_to_false(tmp_path: Path) -> None:
    config = Config(
        vault_path=tmp_path,
        api_key=TEST_API_KEY,
        base_url=DEFAULT_BASE_URL,
        log_level="INFO",
        read_only=False,
        allow_move=False,
    )

    assert config.allow_move is False


def test_load_config_propagates_allow_move_true(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    config = load_config(allow_move=True)

    assert config.allow_move is True


def test_load_config_defaults_allow_move_to_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    config = load_config()

    assert config.allow_move is False


def test_api_key_never_appears_in_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_API_KEY", TEST_API_KEY)

    load_config()

    assert TEST_API_KEY not in caplog.text
