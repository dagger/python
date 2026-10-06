# Repository conventions

One repository, one module per directory:

- `pyproject/` — the shared library. It never gets `@check` functions.
- `ruff/`, `pytest/`, `uv/`, `mypy/`, `ty/` — tool modules, each with its own
  checks. `ruff/` never runs through uv; it is a standalone binary. Each one's
  `projects` is a Dagger collection keyed by project root: checks live on the
  item type, and the collection's batch functions run them over a selection.
- `.dagger/modules/e2e` — one end-to-end suite covering every module.
- `testdata/` — fixture projects shared by the suite. Several fail on purpose.

The design this implements is `hack/designs/python-modules-design.html`.

To run the tests: `dagger check -m .dagger/modules/e2e`. Collections need
engine v1.0.0-beta.15 or later; until it is released, use a dev engine.

When changing a module, always make sure the tests are up to date.
