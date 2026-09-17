"""Update-Entity.

Authelia stellt seine Version über keinen unauthentifizierten Endpoint bereit.
Die installierte Version kommt daher vom Agent (``authelia --version``) oder
– ohne Agent – aus den Optionen.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutheliaConfigEntry
from .const import CONF_INSTALLED_VERSION
from .coordinator import AutheliaAgentCoordinator, AutheliaReleaseCoordinator
from .entity import AutheliaEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutheliaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    manual = (entry.options.get(CONF_INSTALLED_VERSION) or "").strip().removeprefix("v")
    if manual or data.agent is not None:
        async_add_entities([AutheliaUpdate(data.release, entry, manual or None, data.agent)])


class AutheliaUpdate(AutheliaEntity[AutheliaReleaseCoordinator], UpdateEntity):
    _attr_name = None  # Entity heißt wie das Gerät
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self,
        coordinator: AutheliaReleaseCoordinator,
        entry: AutheliaConfigEntry,
        manual_version: str | None,
        agent: AutheliaAgentCoordinator | None,
    ) -> None:
        super().__init__(coordinator, entry, "update")
        self._manual_version = manual_version
        self._agent = agent

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._agent is not None:
            self.async_on_remove(self._agent.async_add_listener(self._handle_coordinator_update))

    @property
    def installed_version(self) -> str | None:
        """Vom Agent ermittelt (automatisch) – sonst manuell aus den Optionen."""
        agent = self._agent
        if agent is not None and agent.data is not None and agent.data.authelia_version:
            return agent.data.authelia_version
        return self._manual_version

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
