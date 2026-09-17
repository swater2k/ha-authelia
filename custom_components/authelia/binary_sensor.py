"""Binary-Sensoren."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutheliaConfigEntry
from .api import HealthState
from .coordinator import AutheliaHealthCoordinator, AutheliaMetricsCoordinator
from .entity import AutheliaEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutheliaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        AutheliaReachableSensor(data.health, entry),
        AutheliaMetricsSensor(data.metrics, entry),
    ]
    if data.health.data.verbose_available:
        entities.append(AutheliaReadinessSensor(data.health, entry))
    async_add_entities(entities)


class AutheliaReachableSensor(AutheliaEntity[AutheliaHealthCoordinator], BinarySensorEntity):
    """Liveness über /api/health."""

    _attr_translation_key = "reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: AutheliaHealthCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "reachable")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.state is not HealthState.UNREACHABLE

    @property
    def extra_state_attributes(self) -> dict[str, int | None]:
        return {"status_code": self.coordinator.data.status_code}


class AutheliaReadinessSensor(AutheliaEntity[AutheliaHealthCoordinator], BinarySensorEntity):
    """Readiness über /api/health/verbose (nur falls vorhanden). on = Problem."""

    _attr_translation_key = "readiness_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: AutheliaHealthCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "readiness_problem")

    @property
    def is_on(self) -> bool | None:
        ok = self.coordinator.data.verbose_ok
        return None if ok is None else not ok


class AutheliaMetricsSensor(AutheliaEntity[AutheliaMetricsCoordinator], BinarySensorEntity):
    """Ob der Telemetry-Endpoint Daten liefert (bleibt verfügbar, wenn nicht)."""

    _attr_translation_key = "metrics_ok"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AutheliaMetricsCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "metrics_ok")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success
