# Story 01.0 - Hello World Endpoint

**Parent milestone:** [plan.md](../plan.md)
**Status:** ⬜ Not started

## Scope

Add a minimal `GET /health` endpoint that returns `{"status": "ok"}`, backed
by a small config model for the service name, with a regression test.

## Tasks

| #  | Document                                  | Status         | Blocks |
|----|--------------------------------------------|----------------|--------|
| 01 | [Config model](01-config-model.md)         | ⬜ Not started | 02     |
| 02 | [Health endpoint](02-health-endpoint.md)   | ⬜ Not started | 03     |
| 03 | [Tests](03-tests.md)                       | ⬜ Not started | -      |

## Key constraints

- No new third-party dependencies.
- Follows this project's existing config-loading convention (see
  `@docs/dev/python_coding_standard.md`).
