"""Event-Entity für fehlgeschlagene Anmeldungen und Sperren."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutheliaConfigEntry
from .const import EVENT_TYPES
from .coordinator import AutheliaMetricsCoordinator
from .entity import AutheliaEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutheliaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AutheliaSecurityEvent(entry.runtime_data.metrics, entry)])


class AutheliaSecurityEvent(AutheliaEntity[AutheliaMetricsCoordinator], EventEntity):
    """Feuert pro Abruf, wenn neue Fehlversuche/Sperren gezählt wurden.

    Die Metriken enthalten weder Benutzer noch IP – das Event trägt nur die
    Anzahl seit dem letzten Abruf.
    """

    _attr_translation_key = "security"
    def __init__(self, coordinator: AutheliaMetricsCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "security_event")
        self._attr_event_types = list(EVENT_TYPES)

    @callback
    def _handle_coordinator_update(self) -> None:
        for event_type, count in self.coordinator.data.events.items():
            self._trigger_event(event_type, {"count": count})
        super()._handle_coordinator_update()
