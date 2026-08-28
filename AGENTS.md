# Repository conventions

One repository, one module per directory:

- `pyproject/` — the shared library. It never gets `@check` functions.
- `ruff/`, `pytest/`, `uv/`, `mypy/`, `ty/` — tool modules, each with its own
  checks. `ruff/` never runs through uv; it is a standalone binary.
- `.dagger/modules/e2e` — one end-to-end suite covering every module.
- `testdata/` — fixture projects shared by the suite. Several fail on purpose.

The design this implements is `.agent/docs/python-modules-design.html`.

To run the tests: `dagger check -m .dagger/modules/e2e`

When changing a module, always make sure the tests are up to date.
