import importlib

import pytest

PACKAGES = [
    "api",
    "core",
    "db",
    "ingest",
    "features",
    "ml",
    "cases",
    "agent",
    "notify",
    "jobs",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_app_package_importable(name: str) -> None:
    assert importlib.import_module(f"app.{name}")
