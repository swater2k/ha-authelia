"""Binary-Sensoren."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutheliaConfigEntry
from .api import HealthState
from .coordinator import (
    AutheliaAgentCoordinator,
    AutheliaHealthCoordinator,
    AutheliaMetricsCoordinator,
)
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
    if data.agent is not None:
        entities.extend(
            [
                AutheliaAgentReachableSensor(data.agent, entry),
                AutheliaBanActiveSensor(data.agent, entry),
                AutheliaCloneWarningSensor(data.agent, entry),
            ]
        )
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

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        data = self.coordinator.data
        return {"waiting_for_first_event": data.metrics_pending if data else None}


class AutheliaAgentReachableSensor(AutheliaEntity[AutheliaAgentCoordinator], BinarySensorEntity):
    """Ob der Datenbank-Agent antwortet."""

    _attr_translation_key = "agent_ok"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AutheliaAgentCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "agent_ok")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class AutheliaBanActiveSensor(AutheliaEntity[AutheliaAgentCoordinator], BinarySensorEntity):
    """An, solange mindestens eine Benutzer- oder IP-Sperre aktiv ist."""

    _attr_translation_key = "ban_active"
    _attr_icon = "mdi:lock-alert"

    def __init__(self, coordinator: AutheliaAgentCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "ban_active")

    @property
    def is_on(self) -> bool | None:
        bans = self.coordinator.data.bans
        if not bans.get("supported"):
            return None
        return bool(bans.get("users") or bans.get("ips"))


class AutheliaCloneWarningSensor(AutheliaEntity[AutheliaAgentCoordinator], BinarySensorEntity):
    """WebAuthn-Klonwarnung: Signaturzähler eines Sicherheitsschlüssels ist inkonsistent."""

    _attr_translation_key = "webauthn_clone_warning"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: AutheliaAgentCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "webauthn_clone_warning")

    def _affected(self) -> list[dict]:
        creds = self.coordinator.data.second_factor.get("webauthn") or []
        return [c for c in creds if c.get("clone_warning")]

    @property
    def is_on(self) -> bool:
        return bool(self._affected())

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "credentials": [
                {"username": c.get("username"), "description": c.get("description")}
                for c in self._affected()
            ]
        }
