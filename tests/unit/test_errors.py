from __future__ import annotations

from obsidian_mcp_opencode.errors import (
    ErrorCode,
    MCPError,
    cap_path_echo,
    error_envelope,
    from_exception,
    redact_token,
    redact_token_patterns,
    success_envelope,
)


def test_success_envelope_shape() -> None:
    assert success_envelope({"value": 1}) == {"ok": True, "data": {"value": 1}}


def test_error_envelope_shape() -> None:
    assert error_envelope(ErrorCode.INTERNAL_ERROR, "boom", {"x": 1}) == {
        "ok": False,
        "error": {
            "code": ErrorCode.INTERNAL_ERROR,
            "message": "boom",
            "details": {"x": 1},
        },
    }


def test_from_exception_round_trip() -> None:
    exc = MCPError(ErrorCode.PATH_FORBIDDEN, "bad path", {"input_path": "x"})

    assert from_exception(exc) == {
        "ok": False,
        "error": {
            "code": ErrorCode.PATH_FORBIDDEN,
            "message": "bad path",
            "details": {"input_path": "x"},
        },
    }


def test_redact_token_replaces_all_and_is_idempotent() -> None:
    token = "secret-token"
    text = f"prefix {token} middle {token} suffix"

    redacted = redact_token(text, token)

    assert redacted == "prefix [REDACTED] middle [REDACTED] suffix"
    assert redact_token(redacted, token) == redacted


def test_redact_token_empty_token_returns_text_unchanged() -> None:
    text = "unchanged"

    assert redact_token(text, "") == text


def test_redact_token_patterns_redacts_long_token_like_strings() -> None:
    token_like = "A234567890123456789012345678901234567890"
    path = "Projects/foo/bar.md"
    text = f"token={token_like} path={path}"

    redacted = redact_token_patterns(text)

    assert token_like not in redacted
    assert "[redacted]" in redacted
    assert path in redacted


def test_cap_path_echo_truncates_and_adds_ellipsis() -> None:
    long_path = "a" * 50

    result = cap_path_echo(long_path, max_chars=20)

    assert result == f"{'a' * 17}..."
