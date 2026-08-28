# Plan: a default-Python-tooling Dagger module

## Goal and boundary

`dagger/go` gives a Go workspace free defaults: discover every module, then lint,
test, and generate across all of them. This module does the same for Python
source, minus lint and format — those belong to `dagger/ruff`, which already
covers them with a standalone binary and no Python runtime. Installing both
gives a Python workspace the same "free defaults" experience a Go workspace
gets today.

What is left once lint and format are removed is the part that actually needs a
Python runtime and a resolver: **tests**, **type checking**, **dependency
lock freshness**, and **packaging**. Those are the four things this module owns.

## Discovery

Marker: `pyproject.toml`, via the native `ws.findRoots(markers: ["pyproject.toml"])`
(beta.10). No polyfill dependency. `findRoots` answers relative to the workspace
cwd — `.` for the cwd, `..` for an enclosing project — so results are resolved
back to workspace-root-relative paths before they become project roots, using the
same `workspaceRootPath` helper shape as `dagger/go` PR #42.

Discovery excludes `**/.venv/**`, `**/site-packages/**`, `**/node_modules/**`:
a virtualenv contains hundreds of vendored `pyproject.toml` files and every one
of them would otherwise become a "project".

Legacy `setup.py` / `requirements.txt` projects are **not** supported in v1.
It is not a matter of adding a marker: a `requirements.txt` directory has no
declarative project metadata, so `uv run`/`uv lock`/`uv build` do not apply and
the whole toolchain below would need a second code path (`uv pip install -r`,
no lock, no build). PEP 621 `pyproject.toml` is the modern baseline and is what
`uv`, `pytest`, `mypy`, and `ruff` all key off. Revisit if real workspaces ask.

## Toolchain

Astral-aligned, matching how `dagger/ruff` is positioned.

- **`uv`** for everything environment-shaped. Non-negotiable given the ecosystem
  choice. The binary is pinned via a Dependabot-trackable
  `images/uv/Dockerfile`, exactly like `dagger/ruff` pins the ruff binary, and
  is layered onto a `python:<version>-slim` base. Debian, not Alpine: Python
  wheels are manylinux, so musl forces source builds of half the ecosystem.
- **`pytest` via `uv run --with pytest`** for tests. `--with` means the project
  does not have to declare pytest itself to get a test run, and a project that
  *does* pin pytest still resolves to its own pin.
- **`mypy` via `uv run --with mypy`** for type checking, with `ty` selectable by
  a one-word constructor switch. mypy is the default because it is the stable,
  de-facto standard whose `[tool.mypy]` config already exists in real projects,
  and because its non-strict default only checks annotated code — so it stays
  quiet on codebases that have not opted in, which is what a "free defaults"
  module needs. `ty` is the Astral-aligned successor but is still 0.0.x/beta as
  of this writing; making it a switch rather than the default means flipping it
  later is a one-line change, not a migration.
- **`uv lock`** for dependency freshness, exposed as a `@generate` changeset
  rather than a pass/fail `uv lock --check`. Drift then shows up in
  `dagger check` *and* is fixable with `dagger generate` — strictly more useful
  than a check that only tells you it is stale.
- **`uv build`** for packaging, exposed as a plain `Directory!` of `dist/`
  rather than a `@check`. Not every `pyproject.toml` is buildable (app-only
  projects, non-packaged uv workspace members), so making it a default check
  would fail workspaces that are perfectly fine.

Each of these is gated on a real precondition so an unrelated project is never
failed by a tool it does not use: tests only run where test files exist
(bare `pytest` exits 5 on an empty collection), lock only runs where a `uv.lock`
already exists (so nothing is forced to adopt uv locking), and type checking
only runs where `.py` files exist.

## Include strategy

Deliberate v1 scope reduction: **no static import-graph analysis.** `dagger/go`
ships a compiled `go-includes` helper that walks the import graph to compute a
minimal per-module include set. Python's equivalent would be a real analyzer,
and it would buy much less: `uv` needs the whole project tree anyway (build
backends read arbitrary files, `[tool.uv.workspace]` members are path
dependencies, `conftest.py` and fixture data are loaded at runtime and are
invisible to imports). So the include set is layout-based:

    <path>/**  minus  **/.venv/**, **/site-packages/**, **/node_modules/**,
                      **/__pycache__/**, **/*.pyc, **/.pytest_cache/**,
                      **/.mypy_cache/**, **/.ruff_cache/**, **/*.egg-info/**

plus `includeExtraFiles` for workspace-root files a project needs. Including
`<path>/**` wholesale is not laziness here — it is what makes uv workspaces
work, since a workspace root genuinely needs its members' sources on disk.

`uv.lock` must be inside the include set. That is the regenerate-idempotency
trap: the changeset baseline is the project's own source, so if the lock were
excluded, a second `uv lock` would report it as newly added forever. There is an
e2e check for exactly this.

## Nested projects

A nested `pyproject.toml` is its own discovered project with its own run. The
parent therefore *mounts* the nested subtree (uv needs it) but *excludes it from
its own commands*: `pytest --ignore=<rel>` and `mypy --exclude '^<rel>/'` /
`ty check --exclude <rel>/`. Without that, a nested project's tests run twice
and a parent fails on a child whose dependencies it never synced.

## Shape

Mirrors `Go`/`GoModule`.

    Python                                  PythonProject
    ------                                  -------------
    version / base (mutually exclusive)     path
    typeChecker ("mypy" | "ty")             version
    includeExtraFiles                       includeExtraFiles
    test / typeCheck / lock  (selection)    skipTest / skipTypeCheck / skipLock
    projects(ws, include:, exclude:, ...)   hasTests / hasPythonFiles / hasLock
    project(ws, path, findUp:)              nestedProjects
                                            includeBase / include / exclude / source
    testAll        @check                   test        @check
    typeCheckAll   @check                   typeCheck   @check
    lockAll        @generate                lock        -> Changeset!
                                            build       -> Directory!

Selection patterns use `dagger/go`'s rules verbatim: bare pattern includes,
`"!"`-prefix excludes, exclude always wins regardless of order, empty list means
everything, `"**"`/`"*"` match all, `X` and `X/**` both mean "X and below".
Consistency across the two modules is worth more here than any improvement.

## Testing

`.dagger/modules/e2e` with `testdata/` fixtures, following `dagger/go`:
discovery (root / nested / deep / cwd-relative `..` resolution / `.venv`
exclusion), a passing and a failing test project, a passing and a failing type
check, both type checkers, nested-project isolation, selection patterns,
lock drift detection, and regenerate idempotency (`lockAll` twice on a current
lock reports zero added/modified/removed).
