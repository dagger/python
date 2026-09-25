"""Shared helpers, not tests: pytest collects nothing here."""


def make_greeting(name: str) -> str:
    return f"hello {name}"
