# 0001 - Config Loading via Layered pydantic-settings Sources

**Illustrative example ADR - not a real decision for this project.** It exists so
`app-architect` and `/adr-write` have a fully-formed record to read as a style and
depth reference before this project has written one of its own - an empty `docs/adr/`
gives them nothing to learn from. **Delete this file and its diagram in
`assets/0001-config-source-precedence.mmd` once this project has written its own
first real ADR.** Leaving it in place afterward risks worse than clutter: a future
`/adr-write` run or `app-architect` read could cite this fictional decision as prior
art, or chain a real ADR's `Supersedes` link to it. It is fine for your first real ADR
to land as `0002`, leaving a gap at `0001` - see the Naming conventions note in
[README.md](README.md) about superseded/removed records; MADR numbering does not need
to stay contiguous.

> **Status:** Accepted
>
> **Date:** 2026-01-15
>
> **Supersedes:** _(none)_
>
> **Superseded by:** _(none)_

## Context

Milestone 0001's first task ([`01-config-model.md`](/docs/roadmap/0001-working-implementation/01.0-hello-world-endpoint/01-config-model.md))
adds a `HealthConfig` settings model and says to "load it the same way other config
sections are loaded in this project" - but at that point in the project's life there
*is* no established way yet. Every subsequent feature will need its own config
section (a database URL, a queue connection, a feature flag), and each one hitting
this same fork - bespoke parsing vs. a shared pattern - independently is how
projects end up with three different ways to read an environment variable by their
fifth feature.

The requirements are ordinary but need picking once, explicitly:

- Config must be typed and validated at startup, not discovered wrong at first use
  three requests into production.
- Local development (`.env` file), CI, and deployed environments (real process env
  vars) all need to set the same values through different mechanisms.
- Tests need to override a value without mutating real process environment state
  (parallel test runs would otherwise clobber each other's env vars).
- New config sections should not require inventing a new loading mechanism each time.

## Decision

**Every config section is a `pydantic_settings.BaseSettings` subclass**, one class per
subsystem (`HealthConfig` is the first). Each resolves its fields from three layered
sources, in ascending precedence:

1. **Class defaults** - the field's `default=` in the class body.
2. **A `.env` file** at the project root, if present (via `model_config =
   SettingsConfigDict(env_file=".env")`).
3. **Process environment variables** - highest precedence, so a deployment can always
   override a checked-in `.env` without editing it.

See [assets/0001-config-source-precedence.mmd](assets/0001-config-source-precedence.mmd)
for the resolution flow, including the test-only bypass (constructor kwargs skip all
three sources, so unit tests set values directly without touching `os.environ`).

Sections are instantiated independently where they are used (`HealthConfig()` in the
health route module) rather than composed under one root `Settings` object - there is
only one section today, and a shared root is easy to introduce later by having each
section's call site read from it instead; collapsing three sections into one object
prematurely is harder to undo.

## Alternatives Considered

| Alternative | Pros | Cons | Reason rejected |
|-------------|------|------|-----------------|
| Bespoke parsing per section (`os.environ.get("SERVICE_NAME", "default")`) | Zero dependencies; obvious to a first-time reader | No type coercion or validation; a typo'd env var name fails silently with the default; every section reinvents the same three lines | Rejected - doesn't scale past one value, and silent-wrong-default is exactly the startup-time failure this decision needs to prevent |
| A single hand-written `Settings` dataclass covering all sections up front | One object to pass around | Forces every future feature's config into a shared class before those features exist; grows into a merge-conflict magnet as sections are added independently | Rejected - couples unrelated features' config through one file for no present benefit |
| A third-party layered-config framework (e.g. Dynaconf) with its own file formats | Supports more source types (TOML/YAML/JSON) than we need yet | A second validation paradigm alongside the pydantic models already used for API/domain schemas; new API to learn for no capability this project currently needs | Rejected - `pydantic-settings` reuses a modeling style this codebase already has, at zero conceptual cost |
| `pydantic-settings` `BaseSettings`, one class per section (chosen) | Typed and validated at startup; env / `.env` / defaults for free; testable via constructor kwargs; same modeling style as the rest of the codebase | One more dependency beyond a bare `os.environ` read; precedence order must be documented somewhere so a new section's author doesn't have to guess | **Accepted** |

## Consequences

### Positive

- New config sections get typed validation, `.env` support, and env-var overrides for
  free by subclassing `BaseSettings` - no loading code to write per section.
- A misconfigured value (wrong type, missing required field) fails at process
  startup with a clear `pydantic.ValidationError`, not three requests into
  production when the bad value is finally read.
- Tests override values via constructor kwargs (`HealthConfig(service_name="test")`)
  - no `monkeypatch.setenv` required, and no risk of parallel tests clobbering each
    other's environment variables.
- Every future task that needs new config answers the "how do I load this"
  question by pointing at `HealthConfig`, not by re-deriving a pattern.

### Negative

- Introduces `pydantic-settings` as an explicit direct dependency (beyond the
  `pydantic` the API layer already uses for request/response schemas).
- The three-source precedence order is a fact someone has to know; it is documented
  here and in the diagram, but a new contributor skimming a section's source file
  alone won't see it - link back to this ADR from any section docstring that
  overrides the default `.env`/env-var behavior.
- Because sections are instantiated independently rather than under one root object,
  there is currently no single place listing "every config value this service
  reads." Acceptable while there is one section; revisit (introduce a root
  `Settings` aggregating each section) once there are enough sections that this
  becomes a real discovery problem, not before.

## Validation / Rollout

- `HealthConfig` ([`01-config-model.md`](/docs/roadmap/0001-working-implementation/01.0-hello-world-endpoint/01-config-model.md))
  is the first section built on this pattern; its default-value-vs-override test
  doubles as the acceptance check for this decision - if that test needs
  environment mutation instead of a constructor kwarg, this ADR's Decision isn't
  actually being followed.
- Implementation: `python-expert`. Tests: `testing-expert` (unit: default value,
  constructor override, and a missing-required-field validation error). Docs:
  `docs-updater` should link future config-section docs back here rather than
  re-explaining the precedence order.
- Rollout is immediate and low-risk: the first config section in the codebase has no
  prior behavior to migrate away from.

## Links

- **Roadmap task:** [`01-config-model.md`](/docs/roadmap/0001-working-implementation/01.0-hello-world-endpoint/01-config-model.md) - the first (and, at this milestone, only) consumer.
- **Diagrams:** [assets/0001-config-source-precedence.mmd](assets/0001-config-source-precedence.mmd)
