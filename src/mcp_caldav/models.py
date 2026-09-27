from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_BIDI_AND_ZERO_WIDTH = re.compile(
    "[\u200b\u200c\u200d\u2060\u202a-\u202e\u2066-\u2069\ufeff]"
)


@dataclass(frozen=True, slots=True)
class Event:
    uid: str
    calendar: str
    calendar_label: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str = ""
    description: str = ""
    organizer: str = ""
    status: str = ""
    recurrence_id: str = ""

    def sort_key(self) -> tuple[datetime, str, str]:
        return (self.start, self.calendar, self.uid)

    def to_dict(
        self,
        *,
        include_description: bool,
        max_text_length: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "uid": self.uid,
            "calendar": self.calendar,
            "calendar_label": self.calendar_label,
            "title": sanitize_text(self.title, max_text_length),
            "start": _render_datetime(self.start, self.all_day),
            "end": _render_datetime(self.end, self.all_day),
            "all_day": self.all_day,
            "location": sanitize_text(self.location, max_text_length),
            "organizer": sanitize_text(self.organizer, max_text_length),
            "status": sanitize_text(self.status, 128),
            "recurrence_id": self.recurrence_id,
            "content_is_untrusted": True,
        }
        if include_description:
            payload["description"] = sanitize_text(
                self.description,
                max_text_length,
            )
        return payload


def event_from_component(
    component: Any,
    *,
    calendar: str,
    calendar_label: str,
    default_timezone: ZoneInfo,
) -> Event:
    start_value = _decoded_datetime(component, "DTSTART")
    if start_value is None:
        raise ValueError("VEVENT has no DTSTART")

    all_day = isinstance(start_value, date) and not isinstance(
        start_value, datetime
    )
    start = _as_datetime(start_value, default_timezone)

    end_value = _decoded_datetime(component, "DTEND")
    if end_value is not None:
        end = _as_datetime(end_value, default_timezone)
    else:
        duration = _decoded_duration(component)
        end = start + duration if duration is not None else start

    uid = _text(component, "UID")
    if not uid:
        raise ValueError("VEVENT has no UID")

    recurrence = _decoded_datetime(component, "RECURRENCE-ID")
    recurrence_id = ""
    if recurrence is not None:
        recurrence_id = (
            recurrence.isoformat()
            if isinstance(recurrence, (date, datetime))
            else str(recurrence)
        )

    return Event(
        uid=uid,
        calendar=calendar,
        calendar_label=calendar_label,
        title=_text(component, "SUMMARY") or "(untitled)",
        start=start,
        end=end,
        all_day=all_day,
        location=_text(component, "LOCATION"),
        description=_text(component, "DESCRIPTION"),
        organizer=_organizer(component),
        status=_text(component, "STATUS"),
        recurrence_id=recurrence_id,
    )


def sanitize_text(value: str, limit: int) -> str:
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = _BIDI_AND_ZERO_WIDTH.sub("", normalized)

    cleaned: list[str] = []
    for char in normalized:
        code = ord(char)
        if char in "\n\t":
            cleaned.append(char)
        elif code < 32 or 0x7F <= code < 0xA0:
            cleaned.append(" ")
        else:
            cleaned.append(char)

    compact = " ".join("".join(cleaned).split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)] + "…"


def matches_query(event: Event, query: str) -> bool:
    needle = query.casefold().strip()
    if not needle:
        return True
    haystack = "\n".join(
        (
            event.title,
            event.location,
            event.description,
            event.organizer,
        )
    ).casefold()
    return needle in haystack


def _text(component: Any, key: str) -> str:
    value = component.get(key)
    return str(value) if value is not None else ""


def _organizer(component: Any) -> str:
    organizer = component.get("ORGANIZER")
    if organizer is None:
        return ""
    params = getattr(organizer, "params", {})
    common_name = params.get("CN") if params else None
    if common_name:
        return f"{common_name} <{organizer}>"
    return str(organizer)


def _decoded_datetime(component: Any, key: str) -> date | datetime | None:
    value = component.get(key)
    if value is None:
        return None
    decoded = getattr(value, "dt", None)
    if isinstance(decoded, (date, datetime)):
        return decoded
    return None


def _decoded_duration(component: Any) -> timedelta | None:
    value = component.get("DURATION")
    if value is None:
        return None
    decoded = getattr(value, "dt", None)
    return decoded if isinstance(decoded, timedelta) else None


def _as_datetime(value: date | datetime, zone: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=zone)
        return value
    return datetime.combine(value, time.min, tzinfo=zone)


def _render_datetime(value: datetime, all_day: bool) -> str:
    if all_day:
        return value.date().isoformat()
    return value.isoformat()
