"""Read one shared pytest report and write a bounded result for each test check.

    python -I dagger_pytest_index.py --report FILE --stdout FILE --stderr FILE \
        --selection FILE --exit-code N --output DIR

The selection is a JSON list of {"path", "names"}: the test files of one
project, relative to its root, and the top-level tests of each that are
checks. The report is the JSON lines dagger_pytest_report.py wrote.

Every check gets a file at DIR/<file rank>/<test rank>, ranks counted in byte
order, so a file or test name never becomes a path. An empty file is a pass;
anything else is the check's failure message, at most 96 KiB however large the
report is.
"""

import argparse
import json
import os
import sys

DIAGNOSTIC_LIMIT = 32 << 10


class Tail:
    """The last DIAGNOSTIC_LIMIT characters written, whatever was written."""

    def __init__(self):
        self.data = ""
        self.truncated = False

    def add(self, text):
        if not text:
            return
        self.data += text if text.endswith("\n") else text + "\n"
        if len(self.data) > DIAGNOSTIC_LIMIT:
            self.data = self.data[-DIAGNOSTIC_LIMIT:]
            self.truncated = True

    def __str__(self):
        if self.truncated:
            return "[earlier output omitted; showing diagnostic tail]\n" + self.data
        return self.data


class Test:
    def __init__(self):
        self.observed = False
        self.failed = False
        self.started = set()
        self.finished = set()
        self.log = Tail()


class File:
    def __init__(self, names):
        self.tests = {name: Test() for name in names}
        self.failed = False  # failed outside every selected test
        self.skipped = False
        self.log = Tail()


def failure_text(event):
    text = event.get("longrepr") or ""
    for title, body in event.get("sections") or []:
        text += "\n" + "-" * 8 + " " + title + " " + "-" * 8 + "\n" + body
    return event["nodeid"] + " " + event.get("when", "collection") + " failed\n" + text


def summarize(events, selections, exit_code, stdout, stderr):
    files = {}
    for s in selections:
        if not s["path"] or s["path"] in files:
            raise ValueError("invalid or duplicate selected file %r" % s["path"])
        if len(set(s["names"])) != len(s["names"]) or not all(s["names"]):
            raise ValueError("invalid or duplicate selected test in %s" % s["path"])
        files[s["path"]] = File(s["names"])

    outside = []
    outside_log = Tail()
    any_failure = False
    stopped = False
    for e in events:
        kind = e.get("type")
        if kind == "finish":
            stopped = bool(e.get("stopped"))
            continue
        f = files.get(e.get("path"))
        t = f.tests.get(e.get("name")) if f is not None else None
        if kind == "deselected":
            # Left out by the project's own -k, -m or addopts.
            if t is not None:
                t.observed = True
            continue
        failed = e.get("outcome") == "failed"
        any_failure = any_failure or failed
        if kind == "collect":
            if t is not None:
                # A test class that failed to collect.
                t.observed = True
                if failed:
                    t.failed = True
                    t.log.add(failure_text(e))
            elif f is not None and e.get("name") is None:
                if failed:
                    f.failed = True
                    f.log.add(failure_text(e))
                else:
                    f.skipped = True
            elif failed:
                outside.append(e.get("nodeid") or "<session>")
                outside_log.add(failure_text(e))
            continue
        if t is None:
            if failed:
                if f is not None:
                    # A test the discovery missed, in a file it found.
                    f.failed = True
                    f.log.add(failure_text(e))
                else:
                    outside.append(e["nodeid"])
                    outside_log.add(failure_text(e))
            continue
        t.observed = True
        if e.get("when") == "setup":
            t.started.add(e["nodeid"])
        if e.get("when") == "teardown" or (e.get("when") == "setup" and e.get("outcome") != "passed"):
            t.finished.add(e["nodeid"])
        if failed:
            t.failed = True
            t.log.add(failure_text(e))

    tails = str(stdout) + str(stderr)
    global_failure = ""
    if outside:
        global_failure = (
            "failures outside the selected test checks: " + ", ".join(sorted(set(outside))) + "\n"
            + str(outside_log) + tails
        )
    elif exit_code != 0 and not any_failure:
        global_failure = "shared pytest command failed (pytest exit %d)\n%s" % (exit_code, tails)

    results = {}
    for s in selections:
        f = files[s["path"]]
        for name in s["names"]:
            t = f.tests[name]
            failure = global_failure
            if not failure:
                if t.failed:
                    failure = name + " failed\n" + str(t.log)
                elif f.failed:
                    failure = "%s failed outside a selected test check (pytest exit %d)\n%s" % (
                        s["path"], exit_code, str(f.log))
                elif t.observed and t.started - t.finished:
                    failure = "%s did not finish (pytest exit %d)\n%s" % (name, exit_code, tails)
                elif t.observed or f.skipped:
                    pass
                elif exit_code == 0:
                    # pytest left the test out: discovery read a declaration that
                    # pytest does not collect, such as a test class with __init__.
                    failure = "%s did not run: pytest passed %s without it\n%s" % (name, s["path"], str(stdout))
                elif stopped and any_failure:
                    # -x or --maxfail stopped the session at a reported failure,
                    # so later tests have no result. That failure is not theirs.
                    pass
                else:
                    failure = "no result for %s (pytest exit %d)\n%s" % (name, exit_code, tails)
            if len(failure) > 3 * DIAGNOSTIC_LIMIT:
                failure = failure[: 3 * DIAGNOSTIC_LIMIT] + "\n[remaining diagnostics omitted]\n"
            results[(s["path"], name)] = failure
    return results


def read_events(path):
    events = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    # A report cut short by a crash ends in a partial line.
                    pass
    return events


def read_tail(path, header):
    tail = Tail()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            while True:
                chunk = f.read(1 << 16)
                if not chunk:
                    break
                tail.add(chunk)
    except FileNotFoundError:
        pass
    if not tail.data:
        return ""
    tail.data = header + "\n" + tail.data
    return tail


def main():
    parser = argparse.ArgumentParser()
    for flag in ("--report", "--stdout", "--stderr", "--selection", "--output"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    args = parser.parse_args()
    with open(args.selection, encoding="utf-8") as f:
        selections = json.load(f)
    results = summarize(
        read_events(args.report),
        selections,
        args.exit_code,
        read_tail(args.stdout, "-------- pytest output --------"),
        read_tail(args.stderr, "-------- pytest stderr --------"),
    )
    # The same byte-order ranks PytestResults.assertPassed counts.
    key = lambda text: text.encode("utf-8")
    for file_rank, s in enumerate(sorted(selections, key=lambda s: key(s["path"]))):
        for test_rank, name in enumerate(sorted(s["names"], key=key)):
            out = os.path.join(args.output, str(file_rank), str(test_rank))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(results[(s["path"], name)])


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # noqa: BLE001 - one line, not a traceback
        print("pytest report indexer: %s" % err, file=sys.stderr)
        sys.exit(1)
