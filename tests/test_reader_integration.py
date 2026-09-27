from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import ClassVar
from zoneinfo import ZoneInfo

import pytest

from mcp_caldav.config import CalendarConfig, CredentialProfile, Settings
from mcp_caldav.reader import CalendarReader

ICALENDAR = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:mock-event-1
DTSTART:20260928T090000Z
DTEND:20260928T100000Z
SUMMARY:Mock meeting
LOCATION:Virtual room
END:VEVENT
END:VCALENDAR
"""


class _MockCalDAVHandler(BaseHTTPRequestHandler):
    methods: ClassVar[list[str]] = []

    def do_REPORT(self) -> None:
        self.__class__.methods.append(self.command)
        length = int(self.headers["Content-Length"])
        request_body = self.rfile.read(length).decode()
        assert "calendar-query" in request_body
        response = f"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/calendars/mock-event-1.ics</d:href>
    <d:propstat><d:prop><c:calendar-data><![CDATA[{ICALENDAR}]]></c:calendar-data></d:prop>
    <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
</d:multistatus>""".encode()
        self.send_response(207)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def mock_caldav_server():
    _MockCalDAVHandler.methods.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCalDAVHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/calendars/"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.asyncio
async def test_reader_parses_event_from_mock_caldav_response(
    mock_caldav_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CALDAV_TEST_USERNAME", "test-user")
    monkeypatch.setenv("CALDAV_TEST_PASSWORD", "test-password")
    reader = CalendarReader(
        calendar=CalendarConfig(
            name="mock",
            label="Mock calendar",
            url=mock_caldav_server,
            credentials="test",
        ),
        credentials=CredentialProfile(
            name="test",
            username_env="CALDAV_TEST_USERNAME",
            password_env="CALDAV_TEST_PASSWORD",
        ),
        settings=Settings(require_https=False),
    )

    events = await reader.list_events(
        datetime(2026, 9, 28, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 9, 29, tzinfo=ZoneInfo("UTC")),
    )

    assert _MockCalDAVHandler.methods == ["REPORT"]
    assert [(event.uid, event.title, event.location) for event in events] == [
        ("mock-event-1", "Mock meeting", "Virtual room")
    ]
