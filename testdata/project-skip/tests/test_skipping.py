import pytest


@pytest.mark.skip(reason="needs a database")
def test_marked_skip() -> None:
    raise AssertionError("a skipped test must not run")


def test_called_skip() -> None:
    pytest.skip("no credentials in CI")


def test_runs() -> None:
    assert True
