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

## Requirements

Every module requires Dagger v1.0.0-beta.15 or later.

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
second one under it, `pytest-test-file`, keyed by test file. For a repository
with projects `app` and `libs/core`:

```console
$ dagger list ruff-projects -a
$ dagger list pytest-test-files --pytest-project=app -a
$ dagger check --ruff --check lint --ruff-project=app
$ dagger check --check type-check              # mypy and ty together
$ dagger check --pytest --pytest-project=app --pytest-test-file=tests/test_api.py
$ dagger generate --ruff --ruff-project=app     # ruff format
$ dagger check -l --all --ruff -f=cli           # one line per project, as flags
```

`dagger check --help` lists the flags in effect: `--ruff-project`,
`--pytest-project`, `--pytest-test-file`, `--mypy-project`, `--ty-project` and
`--uv-project` select keys (`--ruff-projects`, `--pytest-tests` and so on select
a whole dimension); `--ruff`, `--pytest`, `--mypy`, `--ty` and `--uv` select a
module; and `--check <name>` selects a check by name across modules: `lint`,
`test`, `type-check`, `audit`, or `stale` for the generators' staleness checks.

`dagger call` cannot step into a collection yet. To call a function on one
project, use the shell form:

```console
$ dagger -c 'ruff | projects | get app | version'
```

Run checks with `dagger check`, in CI above all: calling a check function
(`lint`, `test`, `type-check`, `audit`) with `dagger call` or `dagger -c` does
not fail the command when the check fails. Other functions — `format`, `fix`,
`lock`, `build`, `version` — are fine to call.

### Where you stand selects the project

Keys are workspace-root-relative project roots, and they follow the directory
you run the command from:

- from a project root: that project and the projects below it;
- from inside a project, below its root: that project, and any projects below
  where you stand;
- from a directory in no project: the projects below it.

So there is nothing to select when you are already in the project you mean:

```console
$ cd app/src && dagger check        # app's checks, and only app's
$ dagger -W ./app check             # the same, from anywhere
```

### How projects are found

Keys are computed every time anything is listed, so discovery never runs a
container or a Python tool. It reads the workspace directly:

| Module   | A project is a key when it                                | Found with |
| -------- | --------------------------------------------------------- | ---------- |
| `ruff`   | holds a `pyproject.toml`, `ruff.toml` or `.ruff.toml`      | one `findRoots` |
| `mypy`   | holds a non-empty `*.py` file of its own                   | one `findRoots`, one ripgrep search |
| `ty`     | holds a non-empty `*.py` file of its own                   | one `findRoots`, one ripgrep search |
| `pytest` | holds a test file of its own (see below)                   | one `findRoots`, one ripgrep search |
| `uv`     | holds a `uv.lock`                                         | two `findRoots` |

One more ripgrep search finds the few `pyproject.toml` files that declare uv
workspace members or path sources (see below). Each search and walk prunes the
library's `exclude` list — `.venv`,
`site-packages`, `node_modules`, `__pycache__`, `.git` and the tool caches — so a
virtualenv with thousands of files costs nothing. A file belongs to the deepest
project holding it, so a nested project's files are never its parent's. From
inside a project, one more `findRoots` finds that project's nested projects.

pytest's test files are `test_*.py` and `*_test.py` files holding a line that
declares a test pytest collects by default: `def test…`, `async def test…` or
`class Test…`. A helper module named like a test file is not listed, since
running it alone collects nothing. What a search cannot see is not listed
either: a test built at runtime, or one found through a project's own
`python_files`, `python_classes`, `python_functions` or `testpaths`. The
whole-project run still collects those, because it runs pytest the way the
project configures it.

On a tree with 40 projects and 16,000 files in their virtualenvs, discovery
for `dagger check -l --all` with all five modules installed takes 4–8 seconds,
down from 12–25 seconds when each project walked its own tree.

A uv workspace member, or a `path` source in `[tool.uv.sources]`, that sits
inside the project declaring it is part of that project: it is not a key of
its own, and it is not excluded from the project's runs as a nested project.
It is installed into the project's environment and checked there, where its
imports resolve. Standing inside one selects the project that owns it. A path
source outside the declaring project stays a project of its own.

### The Python environment

mypy, ty and pytest run in the project's own environment, built with uv in
steps:

1. `uv sync --locked --no-install-workspace --no-install-local`, with only the
   files uv reads mounted: the project's `pyproject.toml`, `uv.lock`,
   `.python-version` and `uv.toml`, and the `pyproject.toml` of each uv
   workspace member or path source it owns. The three tools share this layer.
2. The tool is resolved against those dependencies: `mypy==…`, `ty==…`, or
   `pytest==…` with the bundled `pytest_otel` plugin.
3. The source is mounted. For pytest, `uv sync --locked` then installs the
   project and its local path dependencies. mypy and ty skip the project
   itself — they read first-party code from the source — and install only its
   uv workspace members and path sources, when it has any.

A source edit leaves steps 1 and 2 cached. For mypy and ty nothing is
installed after it, so only the checker runs again, and a project whose build
needs a compiler or a slow build backend is type checked without one. An edit
to an unrelated project's `pyproject.toml`, or to the workspace's
`dagger.toml` or `dagger.lock`, which are never mounted as project source,
leaves the environment cached too.

`--locked` is dropped for a project with no `uv.lock`; with one, a stale
lockfile fails the environment rather than being re-resolved behind the
check's back — `dagger generate --uv` refreshes it. `.git` is not mounted,
except for a project whose version comes from version control
(setuptools-scm, hatch-vcs and the like), which cannot be built without it.

The default base is `python:<version>-slim` with git, for dependencies
sourced from a git repository, and no C/C++ compiler: a compiler would add
several hundred megabytes to every tool's image, and only a project that
builds a native extension, under pytest, needs one. For such a project, give
pytest a base that has one:

```console
$ dagger settings pytest base ghcr.io/astral-sh/uv:python3.14-bookworm
```

A failure names the step: the environment, or the tool, with its command, exit
code and the end of its output.

```
mypy type check failed:
- src/app: environment failed (uv sync --locked --no-install-workspace --no-install-local, exit code 1):
    error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.
- src/lib: mypy failed (uv run --no-sync --with mypy==2.3.1 mypy ., exit code 1):
    lib/core.py:3: error: Incompatible return value type (got "str", expected "int")
    Found 1 error in 1 file (checked 4 source files)
```

### Batches

Every check runs once per selected set of keys, through the collection's batch
function, rather than once per project. A batch runs the projects in parallel
and, when some fail, names every failing project:

```
ruff lint failed:
- testdata/project-lint-fail: exit code: 1
- testdata/project-ruff-toml: exit code: 2
```

Generators return one changeset over the selected projects, rooted at the cwd,
where `dagger generate` applies it. From inside a project, that changeset holds
only the part of the project below the cwd, since a changeset applied there
cannot reach the rest. A `uv.lock` sits at the project root, so refresh it from
there.

### Calling the modules from another module

A check called through a dependency returns a `Check` that has not run yet, so
wrap it:

```dang
let run(check: Check!): Void {
  if (check.pass == false) {
    raise check.error.message ?? "check failed"
  }
  null
}

run(ruff.projects(ws).batch.lint(ws))                              # every project
run(ruff.projects(ws).subset(keys: ["app", "libs/core"]).batch.lint(ws))
run(ruff.projects(ws).get(key: "app").lint(ws))                    # one project
let changes = ruff.projects(ws).batch.format(ws)                   # a Changeset
run(mypy.project(ws, "app/src").typeCheck(ws))                     # by any path inside
pytest.projects(ws).batch.test(ws)                                  # plain: raises on failure
run(pytest.project(ws, "app").tests(ws).subset(keys: ["tests/test_api.py"]).batch.test(ws))
```

`projects(ws).keys` lists the keys, `get(key:)` builds one item, and
`subset(keys:)` narrows the batch. `dagger call` cannot step into a collection
yet; use `dagger check`, `dagger list`, `dagger -c`, or a module.

## Scoping

Every module discovers **every** project in the workspace, so a repository with
test fixtures or a vendored copy of some source will have those checked too.
Say which project roots you mean in `dagger.toml`:

```toml
[modules.ruff.settings]
scope = ["**", "!.dagger"]
```

or from the command line, where `-u` unsets it again:

```console
$ dagger settings ruff scope '["**", "!.dagger"]'
$ dagger settings -u ruff scope
```

A bare pattern selects, a `"!"`-prefixed pattern excludes, and an exclude wins
whatever the order. `sdk` means `sdk` and every project below it; `["**",
"!.dagger"]` means everything except the projects under `.dagger`. `**` and
`*` mean every project; other glob shapes are not interpreted. `uv` spells its
two as `lock` and `audit` rather than `scope`.

Without this, the first `dagger check` on a repository like `dagger/python-sdk`
lints a vendored SDK copy under `.dagger/modules/e2e/fixtures` that was never
meant to be linted, and fails on it.

A project outside the scope is still a key, so `dagger list` shows the whole
workspace and addresses do not move when the settings change; its checks and
generators do nothing, and pytest lists no test files for it. Its checks
report as passed: a check has no way yet to report itself skipped. Narrow a
run with a dimension flag, such as `--mypy-project=app`, to leave it out of
the report. `uv` needs this:
its one set of keys serves both `lock` and `audit`, which select separately.
Pass `includeSkipped: false` to `projects` to leave such projects out.

## The modules

### `ruff`

| Function   | Description                                                   |
| ---------- | ------------------------------------------------------------- |
| `projects` | ruff projects discovered from the workspace, as a collection. |
| `project`  | The project containing a workspace path.                      |
| `version`  | The version of the bundled ruff binary.                       |

| Setting     | Default  | Meaning                                                  |
| ----------- | -------- | -------------------------------------------------------- |
| `scope`     | `["**"]` | Project roots to lint and format (see [Scoping](#scoping)). |
| `args`      | `[]`     | Extra arguments for every ruff invocation.               |
| `container` | none     | Base image with ruff on PATH, used as it is for every project. |

On a project: `lint` (a `@check`, `ruff check`), `format` (a `@generate`,
`ruff format`), `fix` (`ruff check --fix --exit-zero`, returns a changeset),
`version`, `pinned-version` and `skip`. The collection's batch `lint`, `format` and `fix` run once over the
selected projects.

`format` is a generator, so `dagger generate` applies it and `dagger check`
fails when a project is not formatted, as ruff's `stale` check. `fix` is not a
generator and has no staleness check: a fixable violation already fails `lint`.

ruff runs the release the project pins: the `ruff` version in its `uv.lock`,
else an exact `required-version` in `ruff.toml`, `.ruff.toml` or
`[tool.ruff]` in `pyproject.toml`. That release's binary comes from its
official image, `ghcr.io/astral-sh/ruff:<version>`. A project pinning nothing gets
the bundled release (0.16.5), and so does one whose `required-version` is a
range the bundled release satisfies, such as `>=0.15`. A range it does not
satisfy fails with a message asking for an exact `required-version` or a
`uv.lock` pin, rather than ruff's own version-mismatch error. A project's `version`
reports the ruff that runs on it; the module's `version` reports the bundled
one. A custom `container` is used as it is, pins or not. Either way ruff's
cache lives in a cache volume, never in the project.

ruff never touches uv. It is a standalone binary that reaches the same verdicts
with no interpreter present, so it runs on a bare Alpine base with the ruff
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

| Setting          | Default   | Meaning                                                     |
| ---------------- | --------- | ----------------------------------------------------------- |
| `scope`          | `["**"]`  | Project roots to test.                                      |
| `args`           | `["-v"]`  | Extra arguments for pytest.                                 |
| `defaultVersion` | `9.1.1`   | pytest for a project that pins none.                        |
| `tracing`        | `true`    | Load the bundled OpenTelemetry plugin.                      |
| `nesting`        | `true`    | Let tests reach a nested Dagger engine.                     |
| `version`        | `3.14`    | Python version of the default base image.                   |
| `base`           | none      | Base image with Python and uv, instead of the default one.  |

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

Test files are found as described in [How projects are
found](#how-projects-are-found): by name and by a test declaration, without
running pytest.

`test` on a project and on `projects` are plain functions rather than checks,
so that `dagger check` does not run the same tests twice. The `projects` batch
`test` runs every selected project even after one fails, then lists each
failing project by path.

A project with no test files is not a key, and its `test` does nothing: bare
pytest exits 5 on an empty collection, so running it there would fail a project
whose only fault is having no tests yet.

The bundled `pytest_otel` plugin is resolved with pytest against the project's
dependencies while the environment is built (see [The Python
environment](#the-python-environment)), rather than installed over the top of a
finished one.

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

| Setting   | Default  | Meaning                                                    |
| --------- | -------- | ---------------------------------------------------------- |
| `lock`    | `["**"]` | Project roots to lock.                                     |
| `audit`   | `["**"]` | Project roots to audit.                                    |
| `auditArgs` | `[]`   | Extra arguments for `uv audit`, e.g. `["--no-dev"]`.       |
| `version` | `3.14`   | Python version of the default base image.                  |
| `base`    | none     | Base image with Python and uv, instead of the default one. |

On a project: `audit` (a `@check`, `uv audit`), `lock` (a `@generate`,
`uv lock`), `build` (`uv build`, returns `dist` with the wheel and sdist),
`has-lockfile`, `skip-lock` and `skip-audit`. The collection's batch `audit`,
`lock` and `build` run once over the selected projects; the batch `build`
places each `dist` under its project root.

`audit` runs `uv audit --locked` over the lockfile. To leave dependency groups
out, pass uv's own flags: `["--no-dev"]` for the `dev` group,
`["--no-group", "typing"]` for one named group, `["--no-default-groups"]` for
every group in `default-groups`. `--no-dev` leaves out only `dev`: a group a
project adds to `default-groups`, such as flask's `typing`, needs
`--no-group` or `--no-default-groups`.

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

| Setting          | Default                   | Meaning                                    |
| ---------------- | ------------------------- | ------------------------------------------ |
| `scope`          | `["**"]`                  | Project roots to type check.               |
| `defaultVersion` | mypy `2.3.1`, ty `0.0.78` | The checker for a project that pins none.  |
| `args`           | `[]`                      | Extra arguments for every run, e.g. `["--strict"]`. |
| `version`        | `3.14`                    | Python version of the default base image.  |
| `base`           | none                      | Base image with Python and uv.             |

On a project: `type-check` (a `@check`), `has-sources`, `version`, `skip`, and
for mypy `configures-files`. Both modules name the check `type-check`, so
`dagger check --check type-check` runs them together and `--mypy --check
type-check` runs one.

mypy runs as the project configures it. When the project's mypy config names
its files — `files` in `mypy.ini`, `.mypy.ini`, `[tool.mypy]` in
`pyproject.toml` or `[mypy]` in `setup.cfg`, whichever mypy reads first — it
runs bare `mypy`, so the config decides what is checked; otherwise it runs
`mypy .`. ty always runs bare `ty check` and honours `[tool.ty.src]`. Nested
projects are excluded either way.

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
| `projects`            | Projects discovered from the caller's markers, as tools key them. |
| `roots`               | Their roots, workspace-root-relative, in byte order.             |
| `roots-owning`        | The roots owning a file that matches a glob and a pattern.       |
| `owned-files`         | Those files, workspace-root-relative, from the same one search.  |
| `roots-with`          | The roots holding a named file, such as `uv.lock`.               |
| `project`             | The project containing a workspace path.                         |
| `at`                  | The project rooted at a path, with no lookup.                    |
| `base`                | The `python:<version>-slim` base with the pinned uv on PATH.     |

On a project:

| Function                 | Description                                                       |
| ------------------------ | ----------------------------------------------------------------- |
| `source`                 | The workspace source mounted for this project's commands.          |
| `container`              | That source, on the base image, with the project root as workdir.  |
| `dependencies`           | The base with the project's dependencies installed, from `install-inputs` alone. |
| `env`                    | `dependencies` with the source mounted and the project installed (or, with `installProject: false`, only its local members). |
| `install-inputs`         | The files `uv sync` reads: the project's and its members' `pyproject.toml`, `uv.lock`, `.python-version`, `uv.toml`. |
| `has-local-dependencies` | Whether the project has uv workspace members or path sources.      |
| `required-spec`          | The `required-version` a project declares for a tool, exact or a range. |
| `version-satisfies`      | Whether a version satisfies a PEP 440 specifier set.               |
| `sync-flags`             | `--locked` when the project has a `uv.lock`.                       |
| `uv-run`                 | The start of a `uv run` command for a tool in `env`.               |
| `step`                   | Run a command, failing with its name, command, exit code and output. |
| `absorbed`               | uv workspace members and path sources below this project that belong to it. |
| `version-from-vcs`       | Whether the project's version comes from version control.          |
| `sets-key`               | Whether a config file sets a key in a section.                     |
| `selected`               | Whether selection patterns choose this project.                    |
| `within-cwd`             | Whether this project is at or below the workspace cwd.             |
| `nested-projects`        | Project-relative roots of the projects nested inside this one.     |
| `roots-below`            | This root and every project root below it.                         |
| `search-files`           | Files below this root matching a glob and a pattern (one search).  |
| `has-own-files`          | Whether files matching a glob are this project's, not a child's.   |
| `own-files`              | Those files, project-relative, unique and in byte order.           |
| `cwd-path`               | Where this project's changes land in a changeset rooted at the cwd. |
| `cwd-subpath`            | The part of this project such a changeset can hold.                |
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
same dependency layer, so one `uv sync` serves three checks.

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

The suite requires Dagger v1.0.0-beta.15 or later, as the modules do.

`testdata/` holds the fixture projects the suite runs against. Several of them
fail on purpose — a failing test, a type error, a stale lockfile — and the
suite asserts those failures, so repairing a fixture would be a hole in the
coverage rather than a repair.

The design this implements is
[`hack/designs/python-modules-design.html`](hack/designs/python-modules-design.html).
