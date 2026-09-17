"""DataUpdateCoordinators: Metrics, Health, GitHub-Release."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AutheliaClient,
    AutheliaConnectionError,
    AutheliaError,
    HealthResult,
    ReleaseInfo,
)
from .const import (
    DOMAIN,
    EVENT_BANNED,
    EVENT_FIRST_FACTOR_FAILED,
    EVENT_PASSKEY_FAILED,
    EVENT_SECOND_FACTOR_FAILED,
    RELEASE_INTERVAL,
    SECOND_FACTOR_TYPES,
    WINDOW_1H,
    WINDOW_5M,
    WINDOW_24H,
)
from .metrics import AutheliaMetrics
from .window import CounterWindow, HistogramWindow

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MetricsData:
    """Aufbereitete Werte eines Abrufs."""

    values: dict[str, Any]
    events: dict[str, int]
    metrics: AutheliaMetrics
    fetched_at: datetime
    window_coverage: float = 0.0
    counter_resets: int = 0


def _zero(value: float | None) -> float:
    """Fehlende Authelia-Familie = noch kein Ereignis = 0."""
    return 0.0 if value is None else value


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000, 1)


@dataclass(slots=True)
class _Windows:
    failed_logins: CounterWindow = field(default_factory=lambda: CounterWindow(WINDOW_24H))
    successful_logins: CounterWindow = field(default_factory=lambda: CounterWindow(WINDOW_24H))
    banned: CounterWindow = field(default_factory=lambda: CounterWindow(WINDOW_24H))
    authz_denied: CounterWindow = field(default_factory=lambda: CounterWindow(WINDOW_1H))
    server_errors: CounterWindow = field(default_factory=lambda: CounterWindow(WINDOW_1H))
    authn_duration: HistogramWindow = field(default_factory=lambda: HistogramWindow(WINDOW_1H))
    request_duration: HistogramWindow = field(
        default_factory=lambda: HistogramWindow(WINDOW_1H)
    )


class AutheliaMetricsCoordinator(DataUpdateCoordinator[MetricsData]):
    """Liest /metrics und berechnet abgeleitete Werte."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AutheliaClient,
        interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_metrics",
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self._windows = _Windows()
        self._previous_event_counters: dict[str, float] | None = None

    async def _async_update_data(self) -> MetricsData:
        try:
            metrics = await self.client.fetch_metrics()
        except AutheliaConnectionError as err:
            raise UpdateFailed(f"Authelia-Metrics nicht erreichbar: {err}") from err
        except AutheliaError as err:
            raise UpdateFailed(str(err)) from err
        return self._process(metrics, time.monotonic())

    # ------------------------------------------------------------------ #

    def _process(self, m: AutheliaMetrics, now: float) -> MetricsData:
        v: dict[str, Any] = {}

        # --- 1FA ---------------------------------------------------------
        v["authn_success_total"] = _zero(m.value("authn", success="true"))
        v["authn_failed_total"] = _zero(m.value("authn", success="false"))
        v["authn_banned_total"] = _zero(m.value("authn", banned="true"))

        # --- 2FA ---------------------------------------------------------
        v["second_factor_success_total"] = _zero(m.value("authn_second_factor", success="true"))
        v["second_factor_failed_total"] = _zero(m.value("authn_second_factor", success="false"))
        v["second_factor_banned_total"] = _zero(m.value("authn_second_factor", banned="true"))
        for sf_type in SECOND_FACTOR_TYPES:
            v[f"second_factor_{sf_type}_total"] = _zero(
                m.value("authn_second_factor", success="true", type=sf_type)
            )

        # --- Passkey -----------------------------------------------------
        v["passkey_success_total"] = _zero(m.value("authn_passkey", success="true"))
        v["passkey_failed_total"] = _zero(m.value("authn_passkey", success="false"))

        # --- Autorisierung (Forward-Auth) --------------------------------
        v["authz_granted_total"] = _zero(m.value("authz", code="200"))
        v["authz_redirect_total"] = _zero(m.value("authz", code="302"))
        v["authz_unauthorized_total"] = _zero(m.value("authz", code="401"))
        v["authz_forbidden_total"] = _zero(m.value("authz", code="403"))

        # --- HTTP-Requests -----------------------------------------------
        v["requests_total"] = _zero(m.value("request"))
        client_err = server_err = 0.0
        for code in m.label_values("request", "code"):
            if code.startswith("4"):
                client_err += _zero(m.value("request", code=code))
            elif code.startswith("5"):
                server_err += _zero(m.value("request", code=code))
        v["requests_client_errors_total"] = client_err
        v["requests_server_errors_total"] = server_err

        # --- Fenster -----------------------------------------------------
        w = self._windows
        failed = (
            v["authn_failed_total"] + v["second_factor_failed_total"] + v["passkey_failed_total"]
        )
        w.failed_logins.add(now, failed)
        w.successful_logins.add(now, v["authn_success_total"] + v["passkey_success_total"])
        w.banned.add(now, v["authn_banned_total"] + v["second_factor_banned_total"])
        w.authz_denied.add(now, v["authz_unauthorized_total"] + v["authz_forbidden_total"])
        w.server_errors.add(now, server_err)

        v["failed_logins_5m"] = w.failed_logins.delta(WINDOW_5M, now)
        v["failed_logins_1h"] = w.failed_logins.delta(WINDOW_1H, now)
        v["failed_logins_24h"] = w.failed_logins.delta(WINDOW_24H, now)
        v["successful_logins_24h"] = w.successful_logins.delta(WINDOW_24H, now)
        v["banned_attempts_24h"] = w.banned.delta(WINDOW_24H, now)
        v["authz_denied_1h"] = w.authz_denied.delta(WINDOW_1H, now)
        v["server_errors_1h"] = w.server_errors.delta(WINDOW_1H, now)

        if (hist := m.histogram("authn_duration")) is not None:
            w.authn_duration.add(now, hist)
        if (hist := m.histogram("request_duration")) is not None:
            w.request_duration.add(now, hist)
        authn_1h = w.authn_duration.over(WINDOW_1H, now)
        req_1h = w.request_duration.over(WINDOW_1H, now)
        v["authn_duration_avg_1h"] = _ms(authn_1h.average) if authn_1h else None
        v["request_duration_avg_1h"] = _ms(req_1h.average) if req_1h else None
        v["request_duration_p95_1h"] = _ms(req_1h.quantile(0.95)) if req_1h else None

        # --- Prozess / Go-Runtime ----------------------------------------
        start = m.value("process_start_time_seconds")
        v["process_started"] = (
            datetime.fromtimestamp(start, tz=UTC) if start else None
        )
        v["process_memory"] = m.value("process_resident_memory_bytes")
        v["process_cpu_seconds"] = m.value("process_cpu_seconds_total")
        v["process_open_fds"] = m.value("process_open_fds")
        v["process_network_rx"] = m.value("process_network_receive_bytes_total")
        v["process_network_tx"] = m.value("process_network_transmit_bytes_total")
        v["go_goroutines"] = m.value("go_goroutines")
        v["go_heap_alloc"] = m.value("go_memstats_heap_alloc_bytes")
        go_versions = m.label_values("go_info", "version")
        v["go_version"] = next(iter(go_versions)) if go_versions else None

        # --- Ereignisse seit letztem Abruf -------------------------------
        current = {
            EVENT_FIRST_FACTOR_FAILED: v["authn_failed_total"],
            EVENT_SECOND_FACTOR_FAILED: v["second_factor_failed_total"],
            EVENT_PASSKEY_FAILED: v["passkey_failed_total"],
            EVENT_BANNED: v["authn_banned_total"] + v["second_factor_banned_total"],
        }
        events: dict[str, int] = {}
        if self._previous_event_counters is not None:
            for key, value in current.items():
                prev = self._previous_event_counters[key]
                diff = value - prev if value >= prev else value  # Reset
                if diff > 0:
                    events[key] = int(diff)
        self._previous_event_counters = current

        return MetricsData(
            values=v,
            events=events,
            metrics=m,
            fetched_at=datetime.now(UTC),
            window_coverage=w.failed_logins.covered_seconds,
            counter_resets=w.failed_logins.resets,
        )


class AutheliaHealthCoordinator(DataUpdateCoordinator[HealthResult]):
    """/api/health – schlägt nie fehl, ,unreachable' ist ein gültiger Zustand."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: AutheliaClient, interval: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_health",
            update_interval=timedelta(seconds=interval),
        )
        self.client = client

    async def _async_update_data(self) -> HealthResult:
        return await self.client.check_health()


class AutheliaReleaseCoordinator(DataUpdateCoordinator[ReleaseInfo]):
    """Neueste Authelia-Version von GitHub."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AutheliaClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_release",
            update_interval=timedelta(seconds=RELEASE_INTERVAL),
        )
        self.client = client

    async def _async_update_data(self) -> ReleaseInfo:
        try:
            return await self.client.fetch_latest_release()
        except AutheliaError as err:
            raise UpdateFailed(str(err)) from err
