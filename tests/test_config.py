from __future__ import annotations

from pathlib import Path

import pytest

from mcp_caldav.config import ConfigError, load_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _base(calendar_url: str, *, prefix: str | None = None) -> str:
    prefix_block = (
        f'  allowed_url_prefixes:\n    - "{prefix}"\n'
        if prefix
        else ""
    )
    return f"""
version: 1
settings:
  timezone: Europe/Paris
{prefix_block}
credentials:
  example:
    username_env: CALDAV_USERNAME
    password_env: CALDAV_PASSWORD
calendars:
  - name: me
    label: "Moi"
    url: "{calendar_url}"
    credentials: example
"""


def test_loads_explicit_calendar_url(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _base(
            "https://caldav.example.test/calendars/calendar-user/personal/",
            prefix="https://caldav.example.test/calendars/",
        ),
    )
    config = load_config(path)
    assert config.calendars["me"].label == "Moi"
    assert (
        config.calendars["me"].url
        == "https://caldav.example.test/calendars/calendar-user/personal/"
    )


def test_rejects_url_outside_allowlist(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _base(
            "https://evil.example/calendars/me/",
            prefix="https://caldav.example.test/calendars/",
        ),
    )
    with pytest.raises(ConfigError, match="outside allowed_url_prefixes"):
        load_config(path)


def test_rejects_http_by_default(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _base("http://caldav.example.test/calendars/me/"),
    )
    with pytest.raises(ConfigError, match="Only HTTPS"):
        load_config(path)


def test_rejects_embedded_credentials(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _base("https://user:secret@caldav.example.test/calendars/me/"),
    )
    with pytest.raises(ConfigError, match="must not be embedded"):
        load_config(path)


def test_prefix_matching_is_path_aware(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _base(
            "https://caldav.example.test/calendars-evil/me/",
            prefix="https://caldav.example.test/calendars/",
        ),
    )
    with pytest.raises(ConfigError, match="outside allowed_url_prefixes"):
        load_config(path)
