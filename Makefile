.PHONY: build run test release

build:
	uv build

run:
	uv run mcp-caldav

test:
	uv run pytest

release:
	sh scripts/release.sh
