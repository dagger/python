# Repository conventions

One repository, one module per directory:

- `pyproject/` — the shared library. It never gets `@check` functions.
- `ruff/`, `pytest/`, `uv/`, `mypy/`, `ty/` — tool modules, each with its own
  checks. `ruff/` never runs through uv; it is a standalone binary. Each one's
  `projects` is a Dagger collection keyed by project root, and checks live on
  item types only: collection-level functions are plain helpers, never checks
  or generators. There is no `.batch` namespace. pytest's leaves are
  top-level tests (project > test file > test); every test check of a project
  takes the engine-filtered `tests` collection as its `selection` and shares
  one pytest command, whose report `pytest/helpers/pytest-report` indexes into
  one result per check. Keep that command byte-identical for every check of a
  project: build it only from the sorted selection, never from the check's
  own name.
- `.dagger/modules/e2e` — one end-to-end suite covering every module.
- `testdata/` — fixture projects shared by the suite. Several fail on purpose.

The design this implements is `hack/designs/python-modules-design.html`.

To run the tests: `dagger check --e-2-e`. The modules need engine
v1.0.0-beta.22 or later, for selected collection arguments on checks. Direct
Dang calls do not apply the engine's filtered collection view, so selection
and per-test attribution are tested through the CLI, by the suite's
`selected-*` checks.

When changing a module, always make sure the tests are up to date.
