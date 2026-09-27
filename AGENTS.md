# Agent instructions

- Keep the server strictly read-only: do not add write tools, business APIs, or
  HTTP write requests.
- Never add secrets, real identifiers, personal names, or real infrastructure
  URLs to examples, tests, or documentation.
- Use reserved domains (`example.test`, `example.invalid`) and fictional data
  in all examples.
- Every change to the CalDAV reader must have a test that simulates server
  responses without depending on an external service.
- Run `make test` before proposing a change.
- Always generate a commit message at the end of an action which updates code or docs (format: `feat: ...`, `fix: ...`, `docs: ...`, etc.).
