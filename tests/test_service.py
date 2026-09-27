from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mcp_caldav.config import (
    AppConfig,
    CalendarConfig,
    CredentialProfile,
    Settings,
)
from mcp_caldav.models import Event
from mcp_caldav.service import CalendarService, ServiceError


class FakeReader:
    def __init__(self, events):
        self.events = events

    async def list_events(self, start, end, *, query=""):
        return self.events

    async def get_event(self, uid):
        return next(event for event in self.events if event.uid == uid)


def _service() -> CalendarService:
    config = AppConfig(
        settings=Settings(timezone="Europe/Paris", max_results=10),
        credentials={
            "x": CredentialProfile(
                name="x",
                username_env="U",
                password_env="P",
            )
        },
        calendars={
            "a": CalendarConfig(
                name="a",
                label="A",
                url="https://example.test/cal/a/",
                credentials="x",
            ),
            "b": CalendarConfig(
                name="b",
                label="B",
                url="https://example.test/cal/b/",
                credentials="x",
            ),
        },
    )
    service = CalendarService(config)
    zone = ZoneInfo("Europe/Paris")
    service._readers = {
        "a": FakeReader(
            [
                Event(
                    uid="2",
                    calendar="a",
                    calendar_label="A",
                    title="Later",
                    start=datetime(2026, 9, 28, 11, tzinfo=zone),
                    end=datetime(2026, 9, 28, 12, tzinfo=zone),
                    all_day=False,
                )
            ]
        ),
        "b": FakeReader(
            [
                Event(
                    uid="1",
                    calendar="b",
                    calendar_label="B",
                    title="Earlier",
                    start=datetime(2026, 9, 28, 9, tzinfo=zone),
                    end=datetime(2026, 9, 28, 10, tzinfo=zone),
                    all_day=False,
                )
            ]
        ),
    }
    return service


@pytest.mark.asyncio
async def test_multi_calendar_results_are_merged_and_sorted() -> None:
    service = _service()
    result = await service.list_events(
        calendars=None,
        start="2026-09-28",
        end="2026-09-28",
        query="",
        limit=10,
        include_description=False,
    )
    assert [event["uid"] for event in result["events"]] == ["1", "2"]
    assert result["content_is_untrusted"] is True


@pytest.mark.asyncio
async def test_unknown_calendar_is_rejected() -> None:
    service = _service()
    with pytest.raises(ServiceError, match="Unknown calendar"):
        await service.list_events(
            calendars=["missing"],
            start="2026-09-28",
            end="2026-09-28",
            query="",
            limit=10,
            include_description=False,
        )


def test_date_only_end_includes_whole_day() -> None:
    service = _service()
    start, end = service._parse_range("2026-09-28", "2026-09-28")
    assert (end - start).days == 1
