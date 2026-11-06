"""Run pytest once for many Dagger test checks, recording every outcome.

    python dagger_pytest_report.py --report FILE [--selection FILE] -- PYTEST_ARGS

Each test check is a top-level test of a file: a module-level test function
or a test class. Every report pytest makes is written to FILE as a JSON line
naming the file, relative to the directory pytest runs in, and the top-level
test it belongs to, so the indexer can give each check its own result.

With --selection, a JSON list of {"path", "names"}, only those top-level tests
of those files run; the others are deselected, as `go test -run` leaves them
out.

The runner loads this same file as a plugin by name, with `-p`, and hands it
the report and selection through the environment, so pytest-xdist workers,
which are separate processes that collect for themselves, load it and apply
the selection too. Workers only filter and record what they deselect; the
controller records the reports, which xdist forwards to it.

Only the standard library and pytest are imported: this runs in the project's
own environment.
"""

import json
import os
import sys

import pytest

REPORT = "DAGGER_PYTEST_REPORT"
SELECTION = "DAGGER_PYTEST_SELECTION"

_state = {}


def _write(record):
    # Every process appends one line per write, so the controller and xdist
    # workers never cut into each other's records.
    with open(_state["report"], "a", encoding="utf-8") as out:
        out.write(json.dumps(record) + "\n")


def _locate(nodeid):
    """The file, relative to the cwd, and top-level test of a node id."""
    parts = nodeid.split("::")
    path = os.path.relpath(os.path.join(_state["rootdir"], parts[0]), _state["cwd"])
    path = path.replace(os.sep, "/")
    # A parametrized function's id is name[params]; the check is the name.
    name = parts[1].split("[", 1)[0] if len(parts) > 1 else None
    return path, name


def _worker(config):
    return hasattr(config, "workerinput")


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    report = os.environ.get(REPORT)
    if not report:
        return
    selection = None
    if os.environ.get(SELECTION):
        with open(os.environ[SELECTION], encoding="utf-8") as f:
            selection = {s["path"]: set(s["names"]) for s in json.load(f)}
    root = getattr(config, "rootpath", None) or config.rootdir
    _state.update(
        report=report,
        selection=selection,
        cwd=str(config.invocation_params.dir) if hasattr(config, "invocation_params") else os.getcwd(),
        rootdir=str(root),
        worker=_worker(config),
        dropped=set(),
    )


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    if not _state or _state["selection"] is None:
        return
    keep, drop = [], []
    for item in items:
        path, name = _locate(item.nodeid)
        (keep if name in _state["selection"].get(path, ()) else drop).append(item)
    if drop:
        _state["dropped"].update(item.nodeid for item in drop)
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def pytest_deselected(items):
    # Deselected by the project's own -k, -m or addopts rather than by the
    # selection: reported, so a check whose tests all are is not taken for one
    # that never ran. Under xdist only workers collect, so they write these.
    if not _state:
        return
    for item in items:
        if item.nodeid not in _state["dropped"]:
            path, name = _locate(item.nodeid)
            _write({"type": "deselected", "nodeid": item.nodeid, "path": path, "name": name})


def pytest_collectreport(report):
    # A file that fails to import, or skips itself at module level. xdist
    # forwards workers' collection reports to the controller.
    if not _state or _state["worker"]:
        return
    if report.failed or report.skipped:
        path, name = _locate(report.nodeid) if report.nodeid else ("", None)
        _write({
            "type": "collect",
            "nodeid": report.nodeid,
            "path": path,
            "name": name,
            "outcome": report.outcome,
            "longrepr": report.longreprtext,
        })


def pytest_runtest_logreport(report):
    if not _state or _state["worker"]:
        return
    path, name = _locate(report.nodeid)
    record = {
        "type": "test",
        "nodeid": report.nodeid,
        "path": path,
        "name": name,
        "when": report.when,
        "outcome": report.outcome,
    }
    if report.failed:
        record["longrepr"] = report.longreprtext
        record["sections"] = [[title, text] for title, text in report.sections]
    _write(record)


def pytest_sessionfinish(session, exitstatus):
    if not _state or _state["worker"]:
        return
    _write({
        "type": "finish",
        "exitstatus": int(exitstatus),
        # -x and --maxfail stop the session after a failure.
        "stopped": bool(session.shouldfail or session.shouldstop),
    })


def main(argv):
    env = {}
    while argv and argv[0] != "--":
        flag, value, argv = argv[0], argv[1], argv[2:]
        if flag == "--report":
            env[REPORT] = value
        elif flag == "--selection":
            env[SELECTION] = value
        else:
            sys.exit("unknown flag " + flag)
    if REPORT not in env:
        sys.exit("--report is required")
    os.environ.update(env)
    # Workers import the plugin by name, so it must be on their path; keep
    # whatever path the base already sets.
    here = os.path.dirname(os.path.abspath(__file__))
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in [here, os.environ.get("PYTHONPATH", "")] if p)
    return int(pytest.main(["-p", "dagger_pytest_report"] + argv[1:]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
