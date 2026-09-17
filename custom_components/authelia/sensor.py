"""Sensoren."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutheliaConfigEntry
from .coordinator import (
    AutheliaHealthCoordinator,
    AutheliaMetricsCoordinator,
    AutheliaReleaseCoordinator,
)
from .entity import AutheliaEntity

PARALLEL_UPDATES = 0

TOTAL = SensorStateClass.TOTAL_INCREASING
MEAS = SensorStateClass.MEASUREMENT
DIAG = EntityCategory.DIAGNOSTIC


@dataclass(frozen=True, kw_only=True)
class AutheliaSensorDescription(SensorEntityDescription):
    """Beschreibt einen Metrics-Sensor; ``key`` = Schlüssel in MetricsData.values."""


def _d(key: str, **kw: Any) -> AutheliaSensorDescription:
    kw.setdefault("translation_key", key)
    return AutheliaSensorDescription(key=key, **kw)


_ms = {"native_unit_of_measurement": UnitOfTime.MILLISECONDS,
       "device_class": SensorDeviceClass.DURATION, "state_class": MEAS,
       "suggested_display_precision": 0}
_bytes = {"native_unit_of_measurement": UnitOfInformation.BYTES,
          "device_class": SensorDeviceClass.DATA_SIZE,
          "suggested_unit_of_measurement": UnitOfInformation.MEGABYTES,
          "suggested_display_precision": 1}

METRIC_SENSORS: tuple[AutheliaSensorDescription, ...] = (
    # Anmeldungen – Fenster (Default an)
    _d("failed_logins_5m", state_class=MEAS, icon="mdi:account-alert"),
    _d("failed_logins_1h", state_class=MEAS, icon="mdi:account-alert"),
    _d("failed_logins_24h", state_class=MEAS, icon="mdi:account-alert"),
    _d("successful_logins_24h", state_class=MEAS, icon="mdi:account-check"),
    _d("banned_attempts_24h", state_class=MEAS, icon="mdi:account-cancel"),
    _d("authz_denied_1h", state_class=MEAS, icon="mdi:shield-lock"),
    # 1FA
    _d("authn_success_total", state_class=TOTAL, icon="mdi:login"),
    _d("authn_failed_total", state_class=TOTAL, icon="mdi:login"),
    _d("authn_banned_total", state_class=TOTAL, icon="mdi:account-cancel"),
    # 2FA
    _d("second_factor_success_total", state_class=TOTAL, icon="mdi:two-factor-authentication"),
    _d("second_factor_failed_total", state_class=TOTAL, icon="mdi:two-factor-authentication"),
    _d("second_factor_banned_total", state_class=TOTAL, icon="mdi:account-cancel",
       entity_registry_enabled_default=False),
    _d("second_factor_totp_total", state_class=TOTAL, icon="mdi:cellphone-key",
       entity_registry_enabled_default=False),
    _d("second_factor_webauthn_total", state_class=TOTAL, icon="mdi:usb-flash-drive",
       entity_registry_enabled_default=False),
    _d("second_factor_duo_total", state_class=TOTAL, icon="mdi:cellphone-message",
       entity_registry_enabled_default=False),
    # Passkey
    _d("passkey_success_total", state_class=TOTAL, icon="mdi:key-variant",
       entity_registry_enabled_default=False),
    _d("passkey_failed_total", state_class=TOTAL, icon="mdi:key-variant",
       entity_registry_enabled_default=False),
    # Autorisierung
    _d("authz_granted_total", state_class=TOTAL, icon="mdi:shield-check",
       entity_registry_enabled_default=False),
    _d("authz_redirect_total", state_class=TOTAL, icon="mdi:shield-refresh",
       entity_registry_enabled_default=False),
    _d("authz_unauthorized_total", state_class=TOTAL, icon="mdi:shield-alert",
       entity_registry_enabled_default=False),
    _d("authz_forbidden_total", state_class=TOTAL, icon="mdi:shield-off",
       entity_registry_enabled_default=False),
    # Requests
    _d("requests_total", state_class=TOTAL, icon="mdi:web", entity_registry_enabled_default=False),
    _d("requests_client_errors_total", state_class=TOTAL, icon="mdi:web-remove",
       entity_registry_enabled_default=False),
    _d("requests_server_errors_total", state_class=TOTAL, icon="mdi:web-remove",
       entity_registry_enabled_default=False),
    _d("server_errors_1h", state_class=MEAS, icon="mdi:alert-circle"),
    # Laufzeiten
    _d("authn_duration_avg_1h", **_ms, entity_registry_enabled_default=False),
    _d("request_duration_avg_1h", **_ms, entity_registry_enabled_default=False),
    _d("request_duration_p95_1h", **_ms, entity_registry_enabled_default=False),
    # Prozess / Runtime
    _d("process_started", device_class=SensorDeviceClass.TIMESTAMP, entity_category=DIAG),
    _d("process_memory", **_bytes, state_class=MEAS, entity_category=DIAG),
    _d("go_heap_alloc", **_bytes, state_class=MEAS, entity_category=DIAG,
       entity_registry_enabled_default=False),
    _d("process_cpu_seconds", native_unit_of_measurement=UnitOfTime.SECONDS,
       device_class=SensorDeviceClass.DURATION, state_class=TOTAL, entity_category=DIAG,
       suggested_display_precision=1, entity_registry_enabled_default=False),
    _d("process_open_fds", state_class=MEAS, entity_category=DIAG, icon="mdi:file-multiple",
       entity_registry_enabled_default=False),
    _d("process_network_rx", **_bytes, state_class=TOTAL, entity_category=DIAG,
       entity_registry_enabled_default=False),
    _d("process_network_tx", **_bytes, state_class=TOTAL, entity_category=DIAG,
       entity_registry_enabled_default=False),
    _d("go_goroutines", state_class=MEAS, entity_category=DIAG, icon="mdi:language-go",
       entity_registry_enabled_default=False),
    _d("go_version", entity_category=DIAG, icon="mdi:language-go",
       entity_registry_enabled_default=False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutheliaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    entities: list[SensorEntity] = [
        AutheliaMetricSensor(data.metrics, entry, desc) for desc in METRIC_SENSORS
    ]
    entities.append(AutheliaHealthLatencySensor(data.health, entry))
    entities.append(AutheliaLatestVersionSensor(data.release, entry))
    async_add_entities(entities)


class AutheliaMetricSensor(AutheliaEntity[AutheliaMetricsCoordinator], SensorEntity):
    entity_description: AutheliaSensorDescription

    def __init__(
        self,
        coordinator: AutheliaMetricsCoordinator,
        entry: AutheliaConfigEntry,
        description: AutheliaSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.values.get(self.entity_description.key)


class AutheliaHealthLatencySensor(AutheliaEntity[AutheliaHealthCoordinator], SensorEntity):
    _attr_translation_key = "health_latency"
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = MEAS
    _attr_entity_category = DIAG
    _attr_suggested_display_precision = 0
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: AutheliaHealthCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "health_latency")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.latency_ms


class AutheliaLatestVersionSensor(AutheliaEntity[AutheliaReleaseCoordinator], SensorEntity):
    _attr_translation_key = "latest_version"
    _attr_entity_category = DIAG
    _attr_icon = "mdi:tag"

    def __init__(self, coordinator: AutheliaReleaseCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "latest_version")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.version if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not (rel := self.coordinator.data):
            return None
        return {"release_url": rel.url, "published_at": rel.published_at}


