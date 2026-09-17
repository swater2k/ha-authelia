"""Konstanten der Authelia-Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "authelia"

# Config-Entry-Keys (zusätzlich zu CONF_HOST, CONF_SSL, CONF_VERIFY_SSL)
CONF_SERVER_PORT: Final = "server_port"
CONF_METRICS_PORT: Final = "metrics_port"
# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_INSTALLED_VERSION: Final = "installed_version"

DEFAULT_SERVER_PORT: Final = 9091
DEFAULT_METRICS_PORT: Final = 9959
DEFAULT_METRICS_PATH: Final = "/metrics"
DEFAULT_HEALTH_PATH: Final = "/api/health"

DEFAULT_SCAN_INTERVAL: Final = 30  # Sekunden, Metrics + Health
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300
RELEASE_INTERVAL: Final = 6 * 60 * 60

# Zeitfenster (Sekunden)
WINDOW_5M: Final = 5 * 60
WINDOW_1H: Final = 60 * 60
WINDOW_24H: Final = 24 * 60 * 60

SECOND_FACTOR_TYPES: Final = ("totp", "webauthn", "duo")

# Event-Typen der Event-Entity
EVENT_FIRST_FACTOR_FAILED: Final = "first_factor_failed"
EVENT_SECOND_FACTOR_FAILED: Final = "second_factor_failed"
EVENT_PASSKEY_FAILED: Final = "passkey_failed"
EVENT_BANNED: Final = "banned"
EVENT_TYPES: Final = (
    EVENT_FIRST_FACTOR_FAILED,
    EVENT_SECOND_FACTOR_FAILED,
    EVENT_PASSKEY_FAILED,
    EVENT_BANNED,
)
