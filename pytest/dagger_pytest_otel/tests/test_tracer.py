"""Tests for the tracer module."""

from pathlib import Path
from unittest.mock import Mock

from opentelemetry.trace import StatusCode

from dagger_pytest_otel.tracer import SpanContextManager, TestNode as OtelTestNode


class TestParseNodeid:
    """Tests for nodeid parsing."""

    def test_module_only(self):
        """Test parsing a module-only nodeid."""
        ctx = SpanContextManager()
        module, cls, func = ctx._parse_nodeid("tests/test_foo.py")

        assert module == "tests/test_foo.py"
        assert cls is None
        assert func is None

    def test_module_function(self):
        """Test parsing a module::function nodeid."""
        ctx = SpanContextManager()
        module, cls, func = ctx._parse_nodeid("tests/test_foo.py::test_bar")

        assert module == "tests/test_foo.py"
        assert cls is None
        assert func == "test_bar"

    def test_module_class_function(self):
        """Test parsing a module::class::function nodeid."""
        ctx = SpanContextManager()
        module, cls, func = ctx._parse_nodeid("tests/test_foo.py::TestClass::test_method")

        assert module == "tests/test_foo.py"
        assert cls == "TestClass"
        assert func == "test_method"

    def test_parametrized_test(self):
        """Test parsing a parametrized test nodeid."""
        ctx = SpanContextManager()
        module, cls, func = ctx._parse_nodeid("tests/test_foo.py::test_bar[param1-param2]")

        assert module == "tests/test_foo.py"
        assert cls is None
        assert func == "test_bar[param1-param2]"

    def test_parametrized_id_with_separator(self):
        """A "::" inside a parameter id does not split the nodeid."""
        ctx = SpanContextManager()
        module, cls, func = ctx._parse_nodeid("tests/test_foo.py::test_bar[a::b]")

        assert module == "tests/test_foo.py"
        assert cls is None
        assert func == "test_bar[a::b]"
        assert ctx._test_suite_name("tests/test_foo.py::test_bar[a::b]") == "tests/test_foo.py"

    def test_nested_class(self):
        """Test parsing a nested class nodeid."""
        ctx = SpanContextManager()
        module, cls, func = ctx._parse_nodeid(
            "tests/test_foo.py::TestOuter::TestInner::test_method"
        )

        assert module == "tests/test_foo.py"
        assert cls == "TestOuter"
        assert func == "TestInner::test_method"


class TestSemconvMappings:
    """Tests for OTel test semconv value mappings."""

    def test_case_result_status_mapping(self):
        """Verify pytest outcomes map to semconv test case result statuses."""
        from opentelemetry.semconv._incubating.attributes.test_attributes import (
            TestCaseResultStatusValues,
        )

        ctx = SpanContextManager()

        assert ctx._case_result_status("passed") == TestCaseResultStatusValues.PASS.value
        assert ctx._case_result_status("failed") == TestCaseResultStatusValues.FAIL.value
        assert ctx._case_result_status("error") == TestCaseResultStatusValues.FAIL.value
        assert ctx._case_result_status("skipped") == "skipped"

    def test_suite_run_status_mapping(self):
        """Verify pytest exit statuses map to semconv test suite run statuses."""
        from opentelemetry.semconv._incubating.attributes.test_attributes import (
            TestSuiteRunStatusValues,
        )

        ctx = SpanContextManager()

        assert ctx._suite_run_status(0) == TestSuiteRunStatusValues.SUCCESS.value
        assert ctx._suite_run_status(1) == TestSuiteRunStatusValues.FAILURE.value
        assert ctx._suite_run_status(2) == TestSuiteRunStatusValues.ABORTED.value
        assert ctx._suite_run_status(5) == TestSuiteRunStatusValues.SKIPPED.value


class TestStatusDescriptions:
    """Tests for low-cardinality span status descriptions."""

    def test_session_failure_status_is_static(self):
        """Verify session failures do not include dynamic exit status text."""
        ctx = SpanContextManager()
        span = Mock()
        ctx._session_node = OtelTestNode(
            nodeid="session",
            name="pytest session",
            kind="session",
            span=span,
        )

        ctx.end_session(1)

        status = span.set_status.call_args.args[0]
        assert status.status_code == StatusCode.ERROR
        assert status.description == "test session failed"

    def test_test_failure_status_is_static(self):
        """Verify test failures do not include dynamic assertion text."""
        ctx = SpanContextManager()
        span = Mock()
        item = Mock()
        item.nodeid = "tests/test_foo.py::test_bar"
        ctx._tests[item.nodeid] = OtelTestNode(
            nodeid=item.nodeid,
            name="test_bar",
            kind="function",
            span=span,
        )

        ctx.end_test(item, "failed")

        status = span.set_status.call_args.args[0]
        assert status.status_code == StatusCode.ERROR
        assert status.description == "test failed"


class TestAttributeNames:
    """Tests for attribute name constants."""

    def test_attribute_names(self):
        """Verify attribute names for Dagger UI and OTel test semconv integration."""
        from dagger_pytest_otel import tracer

        from opentelemetry.semconv._incubating.attributes import test_attributes

        assert tracer.ATTR_UI_BOUNDARY == "dagger.io/ui.boundary"
        assert not hasattr(tracer, "ATTR_UI_REVEAL")
        assert not hasattr(tracer, "ATTR_PYTEST_NODEID")
        assert not hasattr(tracer, "ATTR_PYTEST_MODULE")
        assert not hasattr(tracer, "ATTR_PYTEST_CLASS")
        assert not hasattr(tracer, "ATTR_PYTEST_FUNCTION")
        assert not hasattr(tracer, "ATTR_PYTEST_OUTCOME")
        assert tracer.TEST_CASE_NAME == test_attributes.TEST_CASE_NAME
        assert tracer.TEST_CASE_RESULT_STATUS == test_attributes.TEST_CASE_RESULT_STATUS
        assert tracer.TEST_SUITE_NAME == test_attributes.TEST_SUITE_NAME
        assert tracer.TEST_SUITE_RUN_STATUS == test_attributes.TEST_SUITE_RUN_STATUS


class TestSessionSuiteName:
    """The session is named by its rootdir relative to the workspace root.

    The workspace root is the nearest ancestor holding .git, as Dagger defines
    it, so the name matches the project's path in a Dagger workspace and does
    not carry a machine-specific absolute path.
    """

    @staticmethod
    def name_for(rootpath):
        session = Mock()
        session.config.rootpath = rootpath
        return SpanContextManager()._session_suite_name(session)

    def test_a_project_below_the_workspace_root(self, tmp_path):
        (tmp_path / "ws" / ".git").mkdir(parents=True)
        rootdir = tmp_path / "ws" / "apps" / "web"
        rootdir.mkdir(parents=True)

        assert self.name_for(rootdir) == "apps/web"

    def test_the_workspace_root_itself(self, tmp_path):
        rootdir = tmp_path / "ws"
        (rootdir / ".git").mkdir(parents=True)

        assert self.name_for(rootdir) == "ws"

    def test_outside_a_git_workspace(self, tmp_path, monkeypatch):
        rootdir = tmp_path / "plain" / "proj"
        rootdir.mkdir(parents=True)
        # tmp_path itself may sit inside a checkout, for example with --basetemp.
        exists = Path.exists
        inside = tmp_path.resolve()
        monkeypatch.setattr(
            Path,
            "exists",
            lambda path, *args, **kwargs: exists(path, *args, **kwargs)
            and (path.name != ".git" or inside in path.parents),
        )

        assert self.name_for(rootdir) == "proj"

    def test_an_unreadable_ancestor_falls_back_to_the_name(self, tmp_path, monkeypatch):
        rootdir = tmp_path / "ws" / "apps" / "web"
        rootdir.mkdir(parents=True)

        def denied(path, *args, **kwargs):
            raise PermissionError(path)

        monkeypatch.setattr(Path, "exists", denied)

        assert self.name_for(rootdir) == "web"

    def test_a_worktree_git_file(self, tmp_path):
        (tmp_path / "wt").mkdir()
        (tmp_path / "wt" / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
        rootdir = tmp_path / "wt" / "pkg"
        rootdir.mkdir()

        assert self.name_for(rootdir) == "pkg"

    def test_the_nearest_git_wins(self, tmp_path):
        (tmp_path / "outer" / ".git").mkdir(parents=True)
        submodule = tmp_path / "outer" / "vendor" / "lib"
        submodule.mkdir(parents=True)
        (submodule / ".git").write_text("gitdir: ../../.git/modules/lib\n")
        rootdir = submodule / "src"
        rootdir.mkdir()

        assert self.name_for(rootdir) == "src"

    def test_a_symlinked_rootdir(self, tmp_path):
        (tmp_path / "ws" / ".git").mkdir(parents=True)
        target = tmp_path / "ws" / "apps" / "web"
        target.mkdir(parents=True)
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)

        assert self.name_for(link) == "apps/web"
