from __future__ import annotations

import inspect

import pytest

from mcp_caldav.reader import CalendarReader, ReadOnlyDAVClient, ReadOnlyViolation


def test_reader_exposes_no_mutation_methods() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(
            CalendarReader,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert public_methods == {"get_event", "list_events"}


def test_http_guard_rejects_put_before_network_access() -> None:
    client = object.__new__(ReadOnlyDAVClient)
    with pytest.raises(ReadOnlyViolation, match="PUT"):
        client.request("https://example.test/calendar/event.ics", method="PUT")
