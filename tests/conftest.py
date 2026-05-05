"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


def pytest_configure(config: pytest.Config) -> None:
    """Remove editable-install path placeholders from custom_components.__path__.

    The editable install adds a virtual PATH_PLACEHOLDER string to
    custom_components.__path__ so the namespace-finder hook is invoked.
    The HA loader iterates __path__ and calls pathlib.Path(p).iterdir() on
    every entry, which raises FileNotFoundError for the fake placeholder.
    Stripping it here prevents the crash without affecting import resolution.
    """
    try:
        import custom_components  # noqa: PLC0415

        custom_components.__path__ = [
            p for p in custom_components.__path__ if not str(p).startswith("__editable__")
        ]
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield
