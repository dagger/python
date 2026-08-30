"""A skipped test must carry the reason it was skipped.

The Dagger UI renders a skipped test case's logs in the Tests tab, so a skip
whose reason is never emitted shows there as a bare "skipped" with nothing to
explain it.

These tests drive real pytest reports rather than hand-built stubs: the reason
lives in longrepr, whose shape is pytest's to choose, and a fixture that agreed
with the implementation would prove nothing.
"""

from typing import List

import pytest
from _pytest.reports import TestReport

pytest_plugins = ["pytester"]

SKIP_SOURCE = """
    import pytest

    @pytest.mark.skip(reason="needs a database")
    def test_marked():
        assert False

    def test_called():
        pytest.skip("no credentials")

    @pytest.mark.xfail(reason="known bug", strict=False)
    def test_expected_failure():
        assert False

    def test_plain():
        assert True
"""


@pytest.fixture
def reports(pytester: pytest.Pytester) -> List[TestReport]:
    """Real reports from a real run of the skips above."""
    pytester.makepyfile(test_skips=SKIP_SOURCE)
    # Disable this plugin for the inner run: it is the subject, not the harness.
    recorder = pytester.inline_run("-p", "no:pytest_otel", "-p", "no:cacheprovider")
    return recorder.getreports("pytest_runtest_logreport")


def report_for(reports: List[TestReport], name: str) -> TestReport:
    """The report that decided `name`'s outcome."""
    for report in reports:
        if report.nodeid.endswith(name) and (report.skipped or report.failed):
            return report
    raise AssertionError(f"no skipped or failed report for {name}")


class TestSkipReasonExtraction:
    """The reason is read out of what pytest actually reports."""

    def test_marker_skip_carries_its_reason(self, reports):
        from pytest_otel import plugin

        reason = plugin._skip_reason(report_for(reports, "test_marked"))

        assert reason is not None
        assert "needs a database" in reason

    def test_called_skip_carries_its_reason(self, reports):
        from pytest_otel import plugin

        reason = plugin._skip_reason(report_for(reports, "test_called"))

        assert reason is not None
        assert "no credentials" in reason

    def test_xfail_carries_its_reason(self, reports):
        from pytest_otel import plugin

        reason = plugin._skip_reason(report_for(reports, "test_expected_failure"))

        assert reason is not None
        assert "known bug" in reason

    def test_a_marker_skip_is_reported_during_setup(self, reports):
        """The regression this fixes.

        A test skipped by a marker never runs, so its only skipped report comes
        from the setup phase. Capturing output from the call phase alone is what
        left these skips with no reason attached.
        """
        report = report_for(reports, "test_marked")

        assert report.when == "setup"
        assert report.skipped


class TestSkipReasonOnSpan:
    """The reason reaches the span as an attribute."""

    @pytest.fixture
    def exporter(self, monkeypatch):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        monkeypatch.setattr(
            "pytest_otel.tracer.get_tracer",
            lambda: provider.get_tracer("test"),
        )
        return exporter

    def test_span_records_the_skip_reason(self, exporter, reports):
        from pytest_otel import plugin, tracer

        item = _ItemStub("test_skips.py::test_marked")
        reason = plugin._skip_reason(report_for(reports, "test_marked"))

        tracer.start_test(item)
        tracer.end_test(item, "skipped", reason)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attributes = dict(spans[0].attributes or {})
        assert attributes["test.case.result.status"] == "skipped"
        assert "needs a database" in attributes["test.case.result.reason"]

    def test_a_passing_test_records_no_reason(self, exporter):
        from pytest_otel import tracer

        item = _ItemStub("test_skips.py::test_plain")

        tracer.start_test(item)
        tracer.end_test(item, "passed")

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert "test.case.result.reason" not in dict(spans[0].attributes or {})


class TestSkipReasonAsOutput:
    """The reason is emitted as output, which is what the Tests tab renders."""

    def test_a_skip_emits_its_reason(self, monkeypatch, reports):
        from pytest_otel import plugin

        import pytest_otel.logging_handler as logging_handler
        from pytest_otel import tracer

        emitted = []
        monkeypatch.setattr(
            logging_handler,
            "emit_stdio_log",
            lambda text, stream, span=None: emitted.append(text),
        )
        monkeypatch.setattr(tracer, "get_test_span", lambda item: None)

        report = report_for(reports, "test_marked")
        plugin._capture_test_output(_ItemStub(report.nodeid), report)

        assert any("needs a database" in text for text in emitted)

    def test_a_passing_test_emits_no_reason(self, monkeypatch, reports):
        from pytest_otel import plugin

        import pytest_otel.logging_handler as logging_handler
        from pytest_otel import tracer

        emitted = []
        monkeypatch.setattr(
            logging_handler,
            "emit_stdio_log",
            lambda text, stream, span=None: emitted.append(text),
        )
        monkeypatch.setattr(tracer, "get_test_span", lambda item: None)

        passing = [
            report
            for report in reports
            if report.nodeid.endswith("test_plain") and report.when == "call"
        ][0]
        plugin._capture_test_output(_ItemStub(passing.nodeid), passing)

        assert emitted == []


class _ItemStub:
    """A stand-in for a pytest item.

    Real items come from a nested pytest run, which starts spans of its own and
    makes the exporter's contents ambiguous. Only the nodeid and the name are
    read here.
    """

    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.name = nodeid.rpartition("::")[2]
