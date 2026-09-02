# python

[Dagger](https://dagger.io) modules for Python tooling, written in the `.dang`
module language.

Go has one module because Go has one toolchain from one supplier. Python has
many tools from many suppliers, each with its own release dates and its own
configuration. So this is not one module: it is one module per tool, over one
shared library, in one repository.

```
github.com/dagger/python
├── pyproject/    the shared library. No checks.
├── ruff/         lint, format
├── pytest/       tests, with OpenTelemetry tracing
├── uv/           lock, build, audit
├── mypy/         type check
├── ty/           type check
└── .dagger/      one end-to-end suite for all of them
```

## Install

Install one module at a time — only the tools you need:

```sh
dagger install github.com/dagger/python/ruff    # lint, format
dagger install github.com/dagger/python/pytest  # tests
dagger install github.com/dagger/python/uv      # lock, build, audit
dagger install github.com/dagger/python/mypy    # type check
dagger install github.com/dagger/python/ty      # type check, Astral's checker
```

`pyproject` is a library, not a tool. You depend on it when you write a module;
you do not install it to get checks.

The standalone `github.com/dagger/ruff` and `github.com/dagger/pytest` still
exist and still work. The modules here are the same tools rebuilt on the shared
library; see "Relationship to the standalone modules" below.

## Scoping

Every module discovers **every** project in the workspace, so a repository with
test fixtures or a vendored copy of some source will have those checked too.
Say which project roots you mean in `dagger.toml`:

```toml
[modules.ruff.settings]
scope = "sdk"
```

A bare pattern selects, a `"!"`-prefixed pattern excludes, and an exclude wins
whatever the order. `sdk` means `sdk` and every project below it; `**,!.dagger`
means everything except the projects under `.dagger`. `uv` spells its two as
`lock` and `audit` rather than `scope`.

Without this, the first `dagger check` on a repository like `dagger/python-sdk`
lints a vendored SDK copy under `.dagger/modules/e2e/fixtures` that was never
meant to be linted, and fails on it.

## The modules

### `ruff`

| Function         | Description                                              |
| ---------------- | -------------------------------------------------------- |
| `check-all`      | Lint every discovered project (a `@check`).              |
| `format-all`     | Format every discovered project (a `@generate`).         |
| `check-project`  | Lint one project.                                        |
| `fix-project`    | Apply ruff's automatic fixes to one project.             |
| `format-project` | Format one project.                                      |
| `version`        | The version of the bundled ruff binary.                  |

ruff never touches uv. It is a standalone binary that reaches the same verdicts
with no interpreter present, so it runs on a bare Alpine base with the pinned
binary on PATH. It uses the library only for the parts every Python tool
repeats: finding projects, keeping nested ones apart, and deciding what to
mount.

### `pytest`

| Function       | Description                                                    |
| -------------- | -------------------------------------------------------------- |
| `test-all`     | Test every discovered project that has tests (a `@check`).     |
| `test-project` | Test one project.                                              |
| `has-tests`    | Whether a project holds test files of its own.                 |
| `nesting`      | Whether tests may talk to a nested Dagger engine (default on). |
| `pytest-otel`  | The bundled OpenTelemetry plugin, as a `Directory`.            |

A project with no test files is skipped rather than run: bare pytest exits 5 on
an empty collection, so running it there would fail a project whose only fault
is having no tests yet.

The bundled `pytest_otel` plugin is resolved alongside pytest and the project's
own dependencies in one uv pass, rather than installed over the top of a
finished environment.

A suite that drives Dagger itself needs a nested engine, and gets one by
default, the same way Go tests do in `dagger/go`. This grants the tests access
to Dagger, not to the host. Turn it off to run test code you do not trust:

```toml
[modules.pytest.settings]
nesting = false
```

### `uv`

| Function        | Description                                                  |
| --------------- | ------------------------------------------------------------ |
| `lock-all`      | Refresh every `uv.lock` and return the changes (a `@generate`). |
| `audit-all`     | Audit every locked project's dependencies (a `@check`).      |
| `lock-project`  | Changes made by refreshing one project's `uv.lock`.          |
| `audit-project` | Audit one project's dependencies.                            |
| `build`         | Run `uv build` and return `dist` (wheel + sdist).            |

Locking is a `@generate` rather than a pass/fail check, so drift shows up in
`dagger check` *and* is repaired by `dagger generate`. Packaging is neither: an
application-only project has no build backend, and failing it would be wrong.

### `mypy` and `ty`

| Function        | Description                                            |
| --------------- | ------------------------------------------------------ |
| `check-all`     | Type check every discovered project (a `@check`).      |
| `check-project` | Type check one project.                                |
| `version-for`   | The tool version used for a project.                   |

Both run inside the project's environment. A checker that cannot see the
installed packages cannot resolve third-party imports and reports errors that
are not real, and a false error is worse than no check.

They are two modules rather than one with a setting because they spell the same
flag in different languages: `mypy --exclude` takes a regular expression and
`ty --exclude` takes a glob, so a directory named `sdk-v1.2` needs two
different escapes.

### `pyproject`

The shared library. It has no checks of its own and never will — two modules
with a check for the same tool would run that tool twice.

| Function              | Description                                                     |
| --------------------- | --------------------------------------------------------------- |
| `projects`            | Projects discovered from the caller's markers.                   |
| `project`             | The project containing a workspace path.                         |
| `base`                | The `python:<version>-slim` base with the pinned uv on PATH.     |

On a project:

| Function                 | Description                                                       |
| ------------------------ | ----------------------------------------------------------------- |
| `source`                 | The workspace source mounted for this project's commands.          |
| `container`              | That source, on the base image, with the project root as workdir.  |
| `env`                    | That container with the project's dependencies installed.          |
| `selected`               | Whether selection patterns choose this project.                    |
| `within-cwd`             | Whether this project is at or below the workspace cwd.             |
| `nested-projects`        | Project-relative roots of the projects nested inside this one.     |
| `has-own-files`          | Whether files matching a pattern are this project's, not a child's. |
| `tool-version`           | The version of a tool this project pins, or null.                  |
| `exclude-nested-flags`   | Flags that keep nested projects out of a tool run.                 |

The caller passes its own markers. A `ruff.toml` directory is a ruff project
and a `tox.ini` directory is a pytest project; both are right, so the library
owns the matching and never the meaning.

## Choices worth knowing

**Markers are never hard-coded in the library.** Each tool keeps its own
opinion about what a project is.

**Ruff never runs through uv.** It is a standalone binary that reaches the same
verdicts with no interpreter present. Giving it an environment would only make
it slower.

**There is no `pip` module.** `uv pip` does the work, and pip has no verb of
its own to hang a check on. pip is an install method inside `env`, not a
module.

**Tool versions do not float.** Every tool resolves its version from what the
project pins — `uv.lock` first, then a `required-version` declaration — and
falls back to a pinned module default. `uv run --with mypy` would otherwise
take whichever mypy shipped that morning, and a check would start failing on a
day nobody touched any code.

**One environment, not three.** pytest, mypy and ty all ask the library for the
same container, so one `uv sync` serves three checks.

## Relationship to the standalone modules

`github.com/dagger/ruff` and `github.com/dagger/pytest` came first and are
unchanged. The `ruff` and `pytest` modules here are the same tools rebuilt on
the shared library, so they gain what the library gives every module: one
notion of a project path, one exclude policy, selection patterns, nested
project isolation, and a shared environment.

Two differences are worth knowing before you switch:

- Paths are workspace-root-relative here. The standalone modules report and
  accept cwd-relative paths.
- The `pytest` module here is uv-only. The standalone module probes for pip and
  supports a container without uv; supply your own `base` image if you need
  that.

## Known problem: only one failure is reported

A batch of three failing projects reports one failure, not three. The modules
aggregate results into a directory and sync it, and the first error stops every
later report; you repair one project, run again, and find the next.

The obvious repair — collecting exit codes with `expect: ReturnType.ANY` —
does report all three, but it loses the parallel run: 6.8s becomes 19.6s for
the same work. Dang has no structured concurrency primitive of its own.

This is not a fault of these modules. `dagger/go`, `dagger/ruff` and
`dagger/pytest` all carry the same shape, and it should be repaired once, in
Dang, rather than four times.

## Development

```sh
dagger check -m .dagger/modules/e2e
```

`testdata/` holds the fixture projects the suite runs against. Several of them
fail on purpose — a failing test, a type error, a stale lockfile — and the
suite asserts those failures, so repairing a fixture would be a hole in the
coverage rather than a repair.

The design this implements is
[`hack/designs/python-modules-design.html`](hack/designs/python-modules-design.html).
