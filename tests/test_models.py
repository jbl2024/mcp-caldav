from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from icalendar import Event as ICalEvent

from mcp_caldav.models import event_from_component, sanitize_text


def test_sanitize_text_removes_control_and_bidi_chars() -> None:
    value = "hello\u202eworld\x00\n next"
    assert sanitize_text(value, 100) == "helloworld next"


def test_event_parsing() -> None:
    component = ICalEvent()
    component.add("uid", "abc-123")
    component.add("summary", "Meeting")
    component.add(
        "dtstart",
        datetime(2026, 9, 28, 10, 0, tzinfo=ZoneInfo("Europe/Paris")),
    )
    component.add(
        "dtend",
        datetime(2026, 9, 28, 11, 0, tzinfo=ZoneInfo("Europe/Paris")),
    )
    component.add("location", "Room A")

    event = event_from_component(
        component,
        calendar="work",
        calendar_label="Travail",
        default_timezone=ZoneInfo("Europe/Paris"),
    )

    assert event.uid == "abc-123"
    assert event.calendar == "work"
    assert event.title == "Meeting"
    assert event.location == "Room A"
    assert not event.all_day
