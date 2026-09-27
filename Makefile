.PHONY: build run test

build:
	uv build

run:
	uv run mcp-caldav

test:
	uv run pytest
