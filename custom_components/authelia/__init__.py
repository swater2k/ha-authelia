"""Authelia-Integration für Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SSL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AutheliaAgentClient, AutheliaClient
from .const import (
    AGENT_API_VERSION,
    CONF_AGENT_TOKEN,
    CONF_AGENT_URL,
    CONF_METRICS_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_PORT,
    DEFAULT_HEALTH_PATH,
    DEFAULT_METRICS_PATH,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import (
    AutheliaAgentCoordinator,
    AutheliaHealthCoordinator,
    AutheliaMetricsCoordinator,
    AutheliaReleaseCoordinator,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.UPDATE,
]


@dataclass(slots=True)
class AutheliaRuntimeData:
    client: AutheliaClient
    metrics: AutheliaMetricsCoordinator
    health: AutheliaHealthCoordinator
    release: AutheliaReleaseCoordinator
    agent: AutheliaAgentCoordinator | None = None


type AutheliaConfigEntry = ConfigEntry[AutheliaRuntimeData]


def build_urls(data: dict) -> tuple[str, str, str]:
    """(metrics_url, health_url, server_url) aus den Entry-Daten."""
    host = data[CONF_HOST]
    scheme = "https" if data.get(CONF_SSL) else "http"
    server = f"{scheme}://{host}:{data[CONF_SERVER_PORT]}"
    # Telemetry spricht immer HTTP
    metrics = f"http://{host}:{data[CONF_METRICS_PORT]}{DEFAULT_METRICS_PATH}"
    return metrics, f"{server}{DEFAULT_HEALTH_PATH}", server


async def async_setup_entry(hass: HomeAssistant, entry: AutheliaConfigEntry) -> bool:
    metrics_url, health_url, _ = build_urls(dict(entry.data))
    client = AutheliaClient(
        async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)),
        metrics_url,
        health_url,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
    )
    interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    metrics = AutheliaMetricsCoordinator(hass, entry, client, interval)
    health = AutheliaHealthCoordinator(hass, entry, client, interval)
    release = AutheliaReleaseCoordinator(hass, entry, client)

    # Metrics müssen beim Start funktionieren (sonst ConfigEntryNotReady),
    # Health liefert immer ein Ergebnis, GitHub darf fehlen.
    await metrics.async_config_entry_first_refresh()
    await health.async_config_entry_first_refresh()
    await release.async_refresh()

    agent: AutheliaAgentCoordinator | None = None
    if (agent_url := entry.options.get(CONF_AGENT_URL)) and entry.options.get(CONF_AGENT_TOKEN):
        agent_client = AutheliaAgentClient(
            async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)),
            agent_url,
            entry.options[CONF_AGENT_TOKEN],
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
            api_version=AGENT_API_VERSION,
        )
        agent = AutheliaAgentCoordinator(hass, entry, agent_client, interval)
        # Agent ist optional: ein Ausfall blockiert die Metrics-Entitäten nicht.
        await agent.async_refresh()

    entry.runtime_data = AutheliaRuntimeData(client, metrics, health, release, agent)

    if agent is not None:
        from .issues import async_update_issues

        @callback
        def _update_issues() -> None:
            async_update_issues(hass, entry, agent)

        entry.async_on_unload(agent.async_add_listener(_update_issues))
        _update_issues()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AutheliaConfigEntry) -> bool:
    from .issues import async_remove_issues

    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        async_remove_issues(hass, entry)
    return unloaded
