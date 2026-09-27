from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AUTH_TYPES = {"basic", "digest"}


class ConfigError(ValueError):
    """Invalid or unsafe configuration."""


@dataclass(frozen=True, slots=True)
class Settings:
    timezone: str = "UTC"
    request_timeout_seconds: int = 20
    max_range_days: int = 366
    max_results: int = 500
    max_parallel_calendars: int = 4
    max_text_length: int = 4000
    verify_tls: bool = True
    require_https: bool = True
    allowed_url_prefixes: tuple[str, ...] = ()

    @property
    def zoneinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(f"Unknown timezone: {self.timezone}") from exc


@dataclass(frozen=True, slots=True)
class CredentialProfile:
    name: str
    username_env: str
    password_env: str
    auth_type: str = "basic"

    def resolve(self) -> tuple[str, str]:
        username = os.environ.get(self.username_env, "")
        password = os.environ.get(self.password_env, "")
        missing = [
            env_name
            for env_name, value in (
                (self.username_env, username),
                (self.password_env, password),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise ConfigError(
                f"Missing credential environment variable(s) for profile "
                f"'{self.name}': {joined}"
            )
        return username, password


@dataclass(frozen=True, slots=True)
class CalendarConfig:
    name: str
    label: str
    url: str
    credentials: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    settings: Settings
    credentials: dict[str, CredentialProfile]
    calendars: dict[str, CalendarConfig]


def config_path_from_env() -> Path:
    return Path(os.environ.get("MCP_CALDAV_CONFIG", "config.yaml")).expanduser()


def load_config(path: str | Path | None = None) -> AppConfig:
    source = Path(path) if path is not None else config_path_from_env()
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {source}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in configuration: {source}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a mapping")
    if raw.get("version") != 1:
        raise ConfigError("Configuration 'version' must be 1")

    settings = _parse_settings(raw.get("settings", {}))
    credentials = _parse_credentials(raw.get("credentials", {}))
    calendars = _parse_calendars(raw.get("calendars", []), credentials, settings)

    if not calendars:
        raise ConfigError("At least one calendar must be configured")

    return AppConfig(
        settings=settings,
        credentials=credentials,
        calendars=calendars,
    )


def _parse_settings(value: Any) -> Settings:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigError("'settings' must be a mapping")

    prefixes_raw = value.get("allowed_url_prefixes", [])
    if prefixes_raw is None:
        prefixes_raw = []
    if not isinstance(prefixes_raw, list) or not all(
        isinstance(item, str) for item in prefixes_raw
    ):
        raise ConfigError("'settings.allowed_url_prefixes' must be a list of URLs")

    settings = Settings(
        timezone=str(value.get("timezone", "UTC")),
        request_timeout_seconds=_bounded_int(
            value.get("request_timeout_seconds", 20),
            "request_timeout_seconds",
            1,
            120,
        ),
        max_range_days=_bounded_int(
            value.get("max_range_days", 366),
            "max_range_days",
            1,
            3660,
        ),
        max_results=_bounded_int(
            value.get("max_results", 500),
            "max_results",
            1,
            5000,
        ),
        max_parallel_calendars=_bounded_int(
            value.get("max_parallel_calendars", 4),
            "max_parallel_calendars",
            1,
            32,
        ),
        max_text_length=_bounded_int(
            value.get("max_text_length", 4000),
            "max_text_length",
            128,
            100_000,
        ),
        verify_tls=_bool(value.get("verify_tls", True), "verify_tls"),
        require_https=_bool(value.get("require_https", True), "require_https"),
        allowed_url_prefixes=tuple(
            _normalize_url(prefix, require_https=_bool(
                value.get("require_https", True), "require_https"
            ))
            for prefix in prefixes_raw
        ),
    )
    _ = settings.zoneinfo
    return settings


def _parse_credentials(value: Any) -> dict[str, CredentialProfile]:
    if not isinstance(value, dict) or not value:
        raise ConfigError("'credentials' must be a non-empty mapping")

    result: dict[str, CredentialProfile] = {}
    for name, item in value.items():
        _validate_name(str(name), "credential profile")
        if not isinstance(item, dict):
            raise ConfigError(f"Credential profile '{name}' must be a mapping")

        username_env = str(item.get("username_env", ""))
        password_env = str(item.get("password_env", ""))
        auth_type = str(item.get("auth_type", "basic")).lower()

        if not _ENV_RE.fullmatch(username_env):
            raise ConfigError(
                f"Credential profile '{name}': invalid username_env '{username_env}'"
            )
        if not _ENV_RE.fullmatch(password_env):
            raise ConfigError(
                f"Credential profile '{name}': invalid password_env '{password_env}'"
            )
        if auth_type not in _AUTH_TYPES:
            raise ConfigError(
                f"Credential profile '{name}': auth_type must be one of "
                f"{sorted(_AUTH_TYPES)}"
            )

        result[str(name)] = CredentialProfile(
            name=str(name),
            username_env=username_env,
            password_env=password_env,
            auth_type=auth_type,
        )
    return result


def _parse_calendars(
    value: Any,
    credentials: dict[str, CredentialProfile],
    settings: Settings,
) -> dict[str, CalendarConfig]:
    if not isinstance(value, list):
        raise ConfigError("'calendars' must be a list")

    result: dict[str, CalendarConfig] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"Calendar entry #{index + 1} must be a mapping")

        name = str(item.get("name", ""))
        label = str(item.get("label", name))
        credential_name = str(item.get("credentials", ""))
        raw_url = str(item.get("url", ""))

        _validate_name(name, "calendar")
        if name in result:
            raise ConfigError(f"Duplicate calendar name: '{name}'")
        if not label.strip():
            raise ConfigError(f"Calendar '{name}': label must not be empty")
        if len(label) > 200:
            raise ConfigError(f"Calendar '{name}': label is too long")
        if credential_name not in credentials:
            raise ConfigError(
                f"Calendar '{name}': unknown credentials profile "
                f"'{credential_name}'"
            )

        url = _normalize_url(raw_url, require_https=settings.require_https)
        if settings.allowed_url_prefixes and not any(
            _url_is_under(url, prefix) for prefix in settings.allowed_url_prefixes
        ):
            raise ConfigError(
                f"Calendar '{name}': URL is outside allowed_url_prefixes"
            )

        result[name] = CalendarConfig(
            name=name,
            label=label.strip(),
            url=url,
            credentials=credential_name,
        )
    return result


def _validate_name(value: str, kind: str) -> None:
    if not _NAME_RE.fullmatch(value):
        raise ConfigError(
            f"Invalid {kind} name '{value}'. Allowed: letters, digits, '.', '_' "
            "and '-', max 64 characters."
        )


def _normalize_url(value: str, *, require_https: bool) -> str:
    if not value:
        raise ConfigError("Calendar URL must not be empty")

    split = urlsplit(value)
    if split.scheme not in {"https", "http"}:
        raise ConfigError(f"Unsupported URL scheme: '{split.scheme}'")
    if require_https and split.scheme != "https":
        raise ConfigError("Only HTTPS calendar URLs are allowed")
    if not split.hostname:
        raise ConfigError("Calendar URL must contain a hostname")
    if split.username is not None or split.password is not None:
        raise ConfigError("Credentials must not be embedded in calendar URLs")
    if split.query or split.fragment:
        raise ConfigError("Calendar URLs must not contain query strings or fragments")

    decoded_path = unquote(split.path or "/")
    normalized_path = posixpath.normpath(decoded_path)
    if decoded_path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path

    host = split.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = split.port
    except ValueError as exc:
        raise ConfigError("Calendar URL contains an invalid port") from exc

    if port is not None:
        netloc = f"{host}:{port}"
    else:
        netloc = host

    encoded_path = quote(
        normalized_path,
        safe="/:@!$&'()*+,;=-._~",
    )
    return urlunsplit(
        (
            split.scheme.lower(),
            netloc,
            encoded_path,
            "",
            "",
        )
    )


def _url_is_under(url: str, prefix: str) -> bool:
    child = urlsplit(url)
    parent = urlsplit(prefix)

    if (
        child.scheme != parent.scheme
        or child.hostname != parent.hostname
        or child.port != parent.port
    ):
        return False

    child_path = posixpath.normpath(unquote(child.path))
    parent_path = posixpath.normpath(unquote(parent.path))

    if child_path == parent_path:
        return True
    return child_path.startswith(parent_path.rstrip("/") + "/")


def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"'{field}' must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'{field}' must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(
            f"'{field}' must be between {minimum} and {maximum}"
        )
    return parsed


def _bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"'{field}' must be a boolean")
