# mcp-caldav

A small, **read-only** CalDAV MCP server that exposes an explicit set of
CalDAV calendars to an agent.

The project is designed for CalDAV installations where collection URLs are
already known, for example:

```text
https://caldav.example.test/calendars/calendar-user/personal/
https://caldav.example.test/calendars/team/shared/
https://caldav.example.test/calendars/rooms/room-123/
```

It performs **no autodiscovery**.

## Principles

- read-only by design: no MCP write tools and no mutation business methods;
- calendar URLs are explicitly declared in YAML;
- credentials are referenced through environment variables and never stored in YAML;
- an allowlist of URL prefixes bounds network destinations;
- HTTPS is required by default and TLS validation is enabled;
- requests run concurrently across calendars, but are serialized per calendar;
- CalDAV searches and returned result sets are bounded;
- event content is explicitly marked as **untrusted**;
- long descriptions and control characters are sanitized before reaching the LLM;
- logs go exclusively to stderr, which is compatible with MCP stdio transport.

The code is new. Its general organization is informed by patterns found in
existing calendar MCP servers, particularly explicitly configured multi-calendar
setups, without reusing their implementation.

## Installation

Requirements: Python 3.12+ and `uv`.

```bash
cp config.example.yaml config.yaml
cp .env.example .env

# Load your secrets using your usual process.
export CALDAV_USERNAME="calendar-user"
export CALDAV_PASSWORD="..."
export MCP_CALDAV_CONFIG="$PWD/config.yaml"

uv sync
uv run mcp-caldav
```

The server uses `stdio`, the natural transport for OpenCode, OMP, Claude
Desktop, and other local MCP hosts.

## Configuration

Minimal example:

```yaml
version: 1

settings:
  timezone: Europe/Paris
  allowed_url_prefixes:
    - "https://caldav.example.test/calendars/"

credentials:
  example:
    username_env: CALDAV_USERNAME
    password_env: CALDAV_PASSWORD
    auth_type: basic

calendars:
  - name: me
    label: "My calendar"
    url: "https://caldav.example.test/calendars/calendar-user/personal/"
    credentials: example

  - name: room-a
    label: "Room A"
    url: "https://caldav.example.test/calendars/rooms/room-123/"
    credentials: example
```

`name` is the stable identifier used by the LLM. `label` is the human-readable
name. `url` must always be the exact CalDAV collection URL.

### Network security

`allowed_url_prefixes` is strongly recommended. Matching compares the scheme,
host, port, and normalized path; it does not use a naïve `startswith()` check.

URLs containing a username, password, query string, or fragment are rejected.

`require_https: true` is the default. Disable it only in an isolated development
environment.

### Credentials

Each profile contains the **names** of environment variables:

```yaml
credentials:
  example:
    username_env: CALDAV_USERNAME
    password_env: CALDAV_PASSWORD
    auth_type: basic
```

Passwords are never serialized in MCP responses or written to logs.

## MCP tools

The server exposes exactly three tools:

### `list_calendars`

Returns the explicitly configured calendars.

### `list_events`

Parameters:

- `calendars`: optional list of names; empty means all calendars;
- `start`, `end`: ISO 8601; empty means today in the configured time zone;
- `query`: optional local text filter for title, location, description, and organizer;
- `limit`: maximum number of returned results;
- `include_description`: defaults to `false` to limit exposed context.

Recurrences are requested with `expand=True` over a closed time range.

### `get_event`

Retrieves an event by `calendar` and `uid`.

For a recurring event, `list_events` is the most reliable view for retrieving a
specific occurrence in a time window.

## OpenCode / OMP configuration

Generic example:

```json
{
  "mcp": {
    "caldav": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-caldav",
        "run",
        "mcp-caldav"
      ],
      "env": {
        "MCP_CALDAV_CONFIG": "/path/to/mcp-caldav/config.yaml",
        "CALDAV_USERNAME": "calendar-user",
        "CALDAV_PASSWORD": "..."
      }
    }
  }
}
```

Adjust the exact syntax for your chosen MCP client.

## Development

```bash
uv sync --group dev
make test
uv run ruff check .
```

## Releases

Run `make release` from a clean branch to run the test suite, update
`CHANGELOG.md`, create an annotated release tag, and push the release commit
and tag to `origin` in one atomic publication.

Tags use the current date (`YYYYMMDD`). When a tag for that date already
exists locally or on `origin`, the command chooses the next available suffix,
such as `YYYYMMDD-1`. Changelog entries are generated from commit subjects
since the preceding dated release tag.

The default remote is `origin`. To publish to a different configured remote,
set `RELEASE_REMOTE`, for example `RELEASE_REMOTE=upstream make release`.

For the MCP Inspector:

```bash
uv run --with "mcp[cli]" mcp dev src/mcp_caldav/server.py
```

## Trust boundary

Calendar data is external input. An appointment's title, description, or
location can contain text hostile to an LLM.

The server therefore returns:

```json
{
  "content_is_untrusted": true
}
```

and bounds and sanitizes text. This reduces the attack surface but **is not a
complete defense against prompt injection**.

The real protection is structural:

1. no MCP write tools;
2. no write business functions and an HTTP guard for DAV methods;
3. no arbitrary URL supplied by the model;
4. ideally, a dedicated CalDAV account with read-only ACLs on the server.

Point 4 remains the strongest barrier.
