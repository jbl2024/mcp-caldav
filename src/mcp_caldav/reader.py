from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime

import caldav

from .config import CalendarConfig, ConfigError, CredentialProfile, Settings
from .models import Event, event_from_component, matches_query


logger = logging.getLogger("mcp-caldav.reader")


class CalendarReadError(RuntimeError):
    """A bounded, non-secret-bearing error suitable for higher layers."""


class ReadOnlyViolation(RuntimeError):
    """Attempted use of a mutating DAV HTTP method."""


class ReadOnlyDAVClient(caldav.DAVClient):
    """DAVClient with an HTTP-level read-only allowlist.

    This is defense in depth: even if write-capable caldav objects are
    accidentally used by future code, mutating DAV methods are rejected
    before any network request is sent.
    """

    _ALLOWED_METHODS = frozenset(
        {
            "GET",
            "HEAD",
            "OPTIONS",
            "PROPFIND",
            "REPORT",
        }
    )

    def request(
        self,
        url,
        method="GET",
        body="",
        headers=None,
        *args,
        **kwargs,
    ):
        normalized_method = str(method).upper()
        if normalized_method not in self._ALLOWED_METHODS:
            raise ReadOnlyViolation(
                f"DAV method '{normalized_method}' is disabled by read-only policy"
            )
        return super().request(
            url,
            method,
            body,
            headers,
            *args,
            **kwargs,
        )


class CalendarReader:
    """Read-only access to one explicitly configured CalDAV collection.

    This class intentionally has no save/create/update/delete API.
    """

    def __init__(
        self,
        calendar: CalendarConfig,
        credentials: CredentialProfile,
        settings: Settings,
    ) -> None:
        self.config = calendar
        self._credentials = credentials
        self._settings = settings
        self._client: ReadOnlyDAVClient | None = None
        self._calendar = None
        self._thread_lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    async def list_events(
        self,
        start: datetime,
        end: datetime,
        *,
        query: str = "",
    ) -> list[Event]:
        async with self._async_lock:
            return await asyncio.to_thread(
                self._list_events_sync,
                start,
                end,
                query,
            )

    async def get_event(self, uid: str) -> Event:
        if not uid or len(uid) > 512:
            raise CalendarReadError("Invalid event UID")

        async with self._async_lock:
            return await asyncio.to_thread(self._get_event_sync, uid)

    def _get_calendar(self):
        if self._calendar is not None:
            return self._calendar

        username, password = self._credentials.resolve()

        # Explicit collection URL; RFC6764/autodiscovery is deliberately off.
        self._client = ReadOnlyDAVClient(
            url=self.config.url,
            username=username,
            password=password,
            auth_type=self._credentials.auth_type,
            timeout=self._settings.request_timeout_seconds,
            ssl_verify_cert=self._settings.verify_tls,
            enable_rfc6764=False,
            require_tls=self._settings.require_https,
        )
        self._calendar = self._client.calendar(url=self.config.url)
        return self._calendar

    def _list_events_sync(
        self,
        start: datetime,
        end: datetime,
        query: str,
    ) -> list[Event]:
        with self._thread_lock:
            try:
                calendar = self._get_calendar()
                objects = calendar.search(
                    start=start,
                    end=end,
                    event=True,
                    expand=True,
                )
            except (ConfigError, ReadOnlyViolation) as exc:
                logger.error(
                    "CalDAV reader policy/configuration failure for calendar '%s': %s",
                    self.config.name,
                    exc,
                )
                raise CalendarReadError(
                    f"Calendar '{self.config.name}' is unavailable"
                ) from exc
            except Exception as exc:
                logger.exception(
                    "CalDAV search failed for calendar '%s'",
                    self.config.name,
                )
                raise CalendarReadError(
                    f"Calendar '{self.config.name}' is unavailable"
                ) from exc

            events: list[Event] = []
            for obj in objects:
                try:
                    component = obj.get_icalendar_component()
                    event = event_from_component(
                        component,
                        calendar=self.config.name,
                        calendar_label=self.config.label,
                        default_timezone=self._settings.zoneinfo,
                    )
                    if matches_query(event, query):
                        events.append(event)
                except Exception:
                    # A malformed single VEVENT must not make the whole
                    # calendar unreadable.
                    logger.warning(
                        "Skipping malformed VEVENT in calendar '%s'",
                        self.config.name,
                        exc_info=True,
                    )

            events.sort(key=Event.sort_key)
            return events

    def _get_event_sync(self, uid: str) -> Event:
        with self._thread_lock:
            try:
                calendar = self._get_calendar()
                obj = calendar.get_event_by_uid(uid)
                component = obj.get_icalendar_component()
                return event_from_component(
                    component,
                    calendar=self.config.name,
                    calendar_label=self.config.label,
                    default_timezone=self._settings.zoneinfo,
                )
            except (ConfigError, ReadOnlyViolation) as exc:
                logger.error(
                    "CalDAV reader policy/configuration failure for calendar '%s': %s",
                    self.config.name,
                    exc,
                )
                raise CalendarReadError(
                    f"Calendar '{self.config.name}' is unavailable"
                ) from exc
            except Exception as exc:
                logger.exception(
                    "CalDAV get_event failed for calendar '%s'",
                    self.config.name,
                )
                raise CalendarReadError(
                    f"Event not found or unreadable in calendar "
                    f"'{self.config.name}'"
                ) from exc
