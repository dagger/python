"""Only a failure becomes an exception event on a test span.

A trace backend highlights a span that carries an exception event, so a skip or
an xfail recorded as one reads as a failure. Their reasons already reach the
span as test.case.result.reason.

The reports come from a real pytest run and the calls from real CallInfo, for
the same reason as in test_skip_reason: their shape is pytest's to choose.
"""

from typing import Callable, List

import pytest
from _pytest.reports import TestReport

from dagger_pytest_otel import plugin, tracer

pytest_plugins = ["pytester"]

SOURCE = """
    import pytest

    def test_fails():
        assert False

    def test_skips():
        pytest.skip("no credentials")

    @pytest.mark.xfail(reason="known bug")
    def test_xfails():
        assert False
"""


@pytest.fixture
def reports(pytester: pytest.Pytester) -> List[TestReport]:
    pytester.makepyfile(test_source=SOURCE)
    recorder = pytester.inline_run("-p", "no:dagger_pytest_otel", "-p", "no:cacheprovider")
    return recorder.getreports("pytest_runtest_logreport")


@pytest.fixture
def recorded(monkeypatch) -> List[BaseException]:
    exceptions: List[BaseException] = []
    monkeypatch.setattr(plugin, "_enabled", True)
    monkeypatch.setattr(plugin, "_test_outcomes", {})
    monkeypatch.setattr(plugin, "_test_reasons", {})
    monkeypatch.setattr(plugin, "_capture_test_output", lambda item, report: None)
    monkeypatch.setattr(tracer, "record_exception", lambda item, exc: exceptions.append(exc))
    return exceptions


def report_for(reports: List[TestReport], name: str, when: str) -> TestReport:
    for report in reports:
        if report.nodeid.endswith(name) and report.when == when:
            return report
    raise AssertionError(f"no {when} report for {name}")


def raising(fn: Callable[[], None], when: str) -> "pytest.CallInfo[None]":
    return pytest.CallInfo.from_call(fn, when=when)


def make_report(report: TestReport, call: "pytest.CallInfo[None]") -> None:
    hook = plugin.pytest_runtest_makereport(_ItemStub(report.nodeid), call)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(report)


def fail() -> None:
    assert False


def skip() -> None:
    pytest.skip("no credentials")


class TestExceptionEvents:
    def test_a_failure_is_recorded(self, reports, recorded):
        call = raising(fail, "call")

        make_report(report_for(reports, "test_fails", "call"), call)

        assert recorded == [call.excinfo.value]

    def test_a_runtime_skip_is_not_recorded(self, reports, recorded):
        make_report(report_for(reports, "test_skips", "call"), raising(skip, "call"))

        assert recorded == []

    def test_an_xfail_is_not_recorded(self, reports, recorded):
        make_report(report_for(reports, "test_xfails", "call"), raising(fail, "call"))

        assert recorded == []


class _ItemStub:
    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.name = nodeid.rpartition("::")[2]
