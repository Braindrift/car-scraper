"""Trivial smoke tests confirming the package and its subpackages import cleanly."""

import importlib


def test_package_imports() -> None:
    assert importlib.import_module("carscraper") is not None


def test_subpackages_import() -> None:
    for module_name in [
        "carscraper.config",
        "carscraper.main",
        "carscraper.db",
        "carscraper.schemas",
        "carscraper.scrapers",
        "carscraper.scrapers.dealers",
        "carscraper.services",
        "carscraper.api",
        "carscraper.web",
        "carscraper.cli",
        "carscraper.cli.main",
    ]:
        assert importlib.import_module(module_name) is not None


def test_app_instance_exists() -> None:
    from carscraper.main import app

    assert app.title == "CarScraper 2.0"
