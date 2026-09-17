"""Update-Entity (nur wenn die installierte Version in den Optionen gepflegt ist).

Authelia stellt seine Version über keinen unauthentifizierten Endpoint bereit.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutheliaConfigEntry
from .const import CONF_INSTALLED_VERSION
from .coordinator import AutheliaReleaseCoordinator
from .entity import AutheliaEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutheliaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if version := (entry.options.get(CONF_INSTALLED_VERSION) or "").strip():
        async_add_entities(
            [AutheliaUpdate(entry.runtime_data.release, entry, version.removeprefix("v"))]
        )


class AutheliaUpdate(AutheliaEntity[AutheliaReleaseCoordinator], UpdateEntity):
    _attr_name = None  # Entity heißt wie das Gerät
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self, coordinator: AutheliaReleaseCoordinator, entry: AutheliaConfigEntry, installed: str
    ) -> None:
        super().__init__(coordinator, entry, "update")
        self._attr_installed_version = installed

    @property
    def latest_version(self) -> str | None:
        return self.coordinator.data.version if self.coordinator.data else None

    @property
    def release_url(self) -> str | None:
        return self.coordinator.data.url if self.coordinator.data else None

    @property
    def release_summary(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.body[:255] or None
