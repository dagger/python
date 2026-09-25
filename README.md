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

## Projects and selection

Each tool module's `projects` is a Dagger collection keyed by project root, so
it adds a dimension — `ruff-project`, `pytest-project`, `mypy-project`,
`ty-project`, `uv-project` — that checks and generators select on. pytest adds a
second one under it, `pytest-test-file`, keyed by test file. A check's name is a
flag too:

```console
$ dagger list ruff-projects
$ dagger list pytest-test-files --pytest-project=testdata/project-pass
$ dagger check --ruff --lint --ruff-project=sdk
$ dagger check --type-check                    # mypy and ty together
$ dagger check --pytest --pytest-project=sdk --pytest-test-file=tests/test_api.py
$ dagger generate --ruff --ruff-project=sdk     # ruff format
$ dagger check -l --all --ruff -f=cli           # one line per project, as flags
```

Keys are workspace-root-relative project roots at or below the cwd — an
enclosing project above the cwd is not one — so `dagger -W ./sdk check` scopes
every tool to `sdk` without a dimension flag. They are found with the
library's `findRoots` and a glob, so listing runs no container. Each tool keeps
only the projects it has something to do in:

| Module   | A project is a key when it                                 |
| -------- | ---------------------------------------------------------- |
| `ruff`   | holds a `pyproject.toml`, `ruff.toml` or `.ruff.toml`       |
| `pytest` | holds test files of its own (`test_*.py`, `*_test.py`)      |
| `mypy`   | holds Python source of its own                              |
| `ty`     | holds Python source of its own                              |
| `uv`     | holds a `uv.lock`                                           |

Every check runs once per selected set of keys, through the collection's batch
function, rather than once per project. A batch runs the projects in parallel
and, when some fail, names every failing project:

```
ruff lint failed:
- testdata/project-lint-fail: exit code: 1
- testdata/project-ruff-toml: exit code: 2
```

Generators return one changeset over the selected projects, rooted at the cwd,
where `dagger generate` applies it.

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

A project outside the scope is still a key, so `dagger list` shows the whole
workspace and addresses do not move when the settings change; its checks and
generators do nothing, and pytest lists no test files for it. `uv` needs this:
its one set of keys serves both `lock` and `audit`, which select separately.
Pass `includeSkipped: false` to `projects` to leave such projects out.

## The modules

### `ruff`

| Function   | Description                                                   |
| ---------- | ------------------------------------------------------------- |
| `projects` | ruff projects discovered from the workspace, as a collection. |
| `project`  | The project containing a workspace path.                      |
| `version`  | The version of the bundled ruff binary.                       |

On a project: `lint` (a `@check`, `ruff check`), `format` (a `@generate`,
`ruff format`), `fix` (`ruff check --fix --exit-zero`, returns a changeset) and
`skip`. The collection's batch `lint`, `format` and `fix` run once over the
selected projects.

`format` is a generator, so `dagger generate` applies it and `dagger check`
fails when a project is not formatted, as ruff's `stale` check. `fix` is not a
generator and has no staleness check: a fixable violation already fails `lint`.

ruff never touches uv. It is a standalone binary that reaches the same verdicts
with no interpreter present, so it runs on a bare Alpine base with the pinned
binary on PATH. It uses the library only for the parts every Python tool
repeats: finding projects, keeping nested ones apart, and deciding what to
mount.

### `pytest`

| Function      | Description                                                    |
| ------------- | -------------------------------------------------------------- |
| `projects`    | Projects that hold test files, as a collection.                |
| `project`     | The project containing a workspace path.                       |
| `has-tests`   | Whether a project holds test files of its own.                 |
| `version-for` | The pytest version used for a project.                         |
| `nesting`     | Whether tests may talk to a nested Dagger engine (default on). |
| `pytest-otel` | The bundled OpenTelemetry plugin, as a `Directory`.            |

On a project: `tests`, `test`, `has-tests`, `version`, `skip`. `tests` is a
collection of the project's test files, keyed by project-relative path, and its
`test` is the check:

```console
$ dagger check --pytest --pytest-project=sdk                                # whole project
$ dagger check --pytest --pytest-project=sdk --pytest-test-file=tests/test_api.py
```

With every test file of a project selected, the batch runs `pytest` over the
whole project, as pytest collects it; with some filtered out, it runs `pytest`
over the selected files only. One run happens per project either way.

Test files are the project's own files matching `test_*.py` and `*_test.py`,
found with a glob, so listing them runs no container. A nested project's files
are its own. A project that changes `python_files` or `testpaths` is still
listed by the default patterns; its whole-project run honours its config.

`test` on a project and on `projects` are plain functions rather than checks,
so that `dagger check` does not run the same tests twice. The `projects` batch
`test` runs every selected project even after one fails, then lists each
failing project by path.

A project with no test files is not a key, and its `test` does nothing: bare
pytest exits 5 on an empty collection, so running it there would fail a project
whose only fault is having no tests yet.

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

| Function   | Description                                              |
| ---------- | -------------------------------------------------------- |
| `projects` | Projects that have a `uv.lock`, as a collection.         |
| `project`  | The project containing a workspace path.                 |

On a project: `audit` (a `@check`, `uv audit`), `lock` (a `@generate`,
`uv lock`), `build` (`uv build`, returns `dist` with the wheel and sdist),
`has-lockfile`, `skip-lock` and `skip-audit`. The collection's batch `audit`,
`lock` and `build` run once over the selected projects; the batch `build`
places each `dist` under its project root.

Locking is a `@generate` rather than a pass/fail check, so drift shows up in
`dagger check`, as uv's `stale` check, *and* is repaired by `dagger generate`.
Packaging is neither: an application-only project has no build backend, and
failing it would be wrong.

### `mypy` and `ty`

| Function      | Description                                                 |
| ------------- | ----------------------------------------------------------- |
| `projects`    | Projects that hold Python source, as a collection.          |
| `project`     | The project containing a workspace path.                    |
| `version-for` | The tool version used for a project.                        |

On a project: `type-check` (a `@check`), `has-sources`, `version`, `skip`. Both
modules name the check `type-check`, so `dagger check --type-check` runs them
together and `--mypy --type-check` runs one.

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
| `roots-within-cwd`    | Roots of the projects at or below the cwd, in byte order.        |
| `project`             | The project containing a workspace path.                         |
| `at`                  | The project rooted at a path, with no lookup.                    |
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
| `own-files`              | Those files, project-relative, unique and in byte order.           |
| `cwd-path`               | This project's root relative to the cwd, where changesets apply.   |
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

The defaults, for a project that pins nothing:

| | default | where |
| --- | --- | --- |
| Python | 3.14 | `pyproject`, `version` |
| uv | 0.12.9 | `pyproject/images/uv/Dockerfile` |
| ruff | 0.16.5 | `ruff/images/ruff/Dockerfile` |
| mypy | 2.3.1 | `mypy`, `defaultVersion` |
| ty | 0.0.78 | `ty`, `defaultVersion` |
| pytest | 9.1.1 | `pytest`, `defaultVersion` |

The two in Dockerfiles are there so Dependabot can raise a pull request for
them. The rest are plain arguments, so a project that wants a different version
either pins it in its own metadata or sets `defaultVersion`.

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

## Development

```sh
dagger check -m .dagger/modules/e2e
```

Every module needs engine v1.0.0-beta.15 or later for collections; until that
is released, use a dev engine build.

`testdata/` holds the fixture projects the suite runs against. Several of them
fail on purpose — a failing test, a type error, a stale lockfile — and the
suite asserts those failures, so repairing a fixture would be a hole in the
coverage rather than a repair.

The design this implements is
[`hack/designs/python-modules-design.html`](hack/designs/python-modules-design.html).
