"""Basis-Entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from . import AutheliaConfigEntry, build_urls
from .const import CONF_INSTALLED_VERSION, DOMAIN


class AutheliaEntity[C: DataUpdateCoordinator](CoordinatorEntity[C]):
    """Gemeinsame Device-Info und Unique-ID."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: C, entry: AutheliaConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        _, _, server_url = build_urls(dict(entry.data))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Authelia",
            manufacturer="Authelia",
            model="Authelia Server",
            sw_version=entry.options.get(CONF_INSTALLED_VERSION) or None,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=server_url,
        )
