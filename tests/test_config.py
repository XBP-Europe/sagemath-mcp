import pytest

from sagemath_mcp.config import SageSettings


def _clear_env(monkeypatch):
    for key in [
        "SAGEMATH_MCP_EVAL_TIMEOUT",
        "SAGEMATH_MCP_IDLE_TTL",
        "SAGEMATH_MCP_SHUTDOWN_GRACE",
        "SAGEMATH_MCP_MAX_STDOUT",
        "SAGEMATH_MCP_FORCE_PYTHON_WORKER",
        "SAGEMATH_MCP_HTTP_AUTH_TOKEN",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_from_env_rejects_invalid_float(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SAGEMATH_MCP_EVAL_TIMEOUT", "not-a-number")
    with pytest.raises(ValueError) as excinfo:
        SageSettings.from_env()
    assert "Invalid float" in str(excinfo.value)


def test_from_env_rejects_invalid_int(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SAGEMATH_MCP_MAX_STDOUT", "ten")
    with pytest.raises(ValueError) as excinfo:
        SageSettings.from_env()
    assert "Invalid int" in str(excinfo.value)


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("off", False),
        ("", False),
    ],
)
def test_bool_flag_parsing(monkeypatch, raw_value, expected):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SAGEMATH_MCP_FORCE_PYTHON_WORKER", raw_value)
    settings = SageSettings.from_env()
    assert settings.force_python_worker is expected


def test_http_auth_token_defaults_to_none(monkeypatch):
    """Unset -> no token -> the HTTP endpoint is unauthenticated by default."""
    _clear_env(monkeypatch)
    assert SageSettings.from_env().http_auth_token is None


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_http_auth_token_blank_reads_as_unset(monkeypatch, blank):
    """A bare `SAGEMATH_MCP_HTTP_AUTH_TOKEN=` must not enable auth with no secret."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("SAGEMATH_MCP_HTTP_AUTH_TOKEN", blank)
    assert SageSettings.from_env().http_auth_token is None


def test_http_auth_token_is_taken_verbatim(monkeypatch):
    """A configured token is used exactly, not stripped -- it is opaque bytes."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("SAGEMATH_MCP_HTTP_AUTH_TOKEN", "  s3cret-token  ")
    assert SageSettings.from_env().http_auth_token == "  s3cret-token  "
