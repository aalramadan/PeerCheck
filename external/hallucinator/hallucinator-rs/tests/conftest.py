"""Shared pytest configuration for hallucinator tests."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "network: marks tests that require network access")
