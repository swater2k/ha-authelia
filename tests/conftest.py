"""Gemeinsame Fixtures."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.authelia.const import (
    CONF_METRICS_PORT,
    CONF_SERVER_PORT,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_METRICS = (FIXTURES / "metrics_real_4.39.27.txt").read_text()

HOST = "192.0.2.10"
METRICS_URL = f"http://{HOST}:9959/metrics"
HEALTH_URL = f"http://{HOST}:9091/api/health"
GITHUB_URL = "https://api.github.com/repos/authelia/authelia/releases/latest"

ENTRY_DATA = {
    "host": HOST,
    CONF_SERVER_PORT: 9091,
    CONF_METRICS_PORT: 9959,
    "ssl": False,
    "verify_ssl": True,
}

RELEASE_JSON = {
    "tag_name": "v4.39.27",
    "name": "v4.39.27",
    "html_url": "https://github.com/authelia/authelia/releases/tag/v4.39.27",
    "published_at": "2026-09-15T00:00:00Z",
    "body": "Bug fixes",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_authelia(aioclient_mock):
    """Authelia-Endpunkte mit echter 4.39.27-Ausgabe."""
    aioclient_mock.get(METRICS_URL, text=REAL_METRICS)
    aioclient_mock.get(HEALTH_URL, text="OK")
    aioclient_mock.get(f"{HEALTH_URL}/verbose", status=404)
    aioclient_mock.get(GITHUB_URL, json=RELEASE_JSON)
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Authelia ({HOST})",
        data=ENTRY_DATA,
        unique_id=f"{HOST}:9091",
        options={"scan_interval": 30, "installed_version": "4.39.27"},
    )
