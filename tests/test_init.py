"""Setup, Entities, Events, Unload."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import METRICS_URL, REAL_METRICS


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_entities(hass: HomeAssistant, mock_authelia, config_entry) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("binary_sensor.authelia_erreichbar") is None  # Sprache = en
    assert hass.states.get("binary_sensor.authelia_reachable").state == "on"
    assert hass.states.get("binary_sensor.authelia_telemetry").state == "on"
    # verbose liefert 404 -> keine Readiness-Entity
    assert hass.states.get("binary_sensor.authelia_readiness_problem") is None

    assert hass.states.get("sensor.authelia_first_factor_successful").state == "1.0"
    assert hass.states.get("sensor.authelia_first_factor_failed").state == "1.0"
    assert hass.states.get("sensor.authelia_second_factor_successful").state == "1.0"
    # authz fehlt in der Ausgabe -> 0 statt unavailable
    ids = sorted(hass.states.async_entity_ids())
    assert "sensor.authelia_failed_logins_5_min" in ids, ids
    assert hass.states.get("sensor.authelia_started").state.startswith("2026-09-17")
    assert hass.states.get("sensor.authelia_latest_version").state == "4.39.27"
    assert hass.states.get("update.authelia").state == "off"  # aktuell

    reg = er.async_get(hass)
    requests = reg.async_get("sensor.authelia_http_requests")
    assert requests is not None and requests.disabled_by is not None


async def test_event_and_window_on_new_failures(
    hass: HomeAssistant, mock_authelia, config_entry
) -> None:
    await _setup(hass, config_entry)
    mock_authelia.clear_requests()
    newer = REAL_METRICS.replace(
        'authelia_authn{banned="false",success="false"} 1',
        'authelia_authn{banned="false",success="false"} 4\n'
        'authelia_authn{banned="true",success="false"} 1',
    )
    mock_authelia.get(METRICS_URL, text=newer)

    coordinator = config_entry.runtime_data.metrics
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.authelia_failed_logins_5_min").state == "4.0"
    assert hass.states.get("sensor.authelia_first_factor_banned").state == "1.0"
    event = hass.states.get("event.authelia_security_event")
    assert event.attributes["event_type"] in ("first_factor_failed", "banned")
    assert event.state not in ("unknown", "unavailable")


async def test_metrics_down_not_ready(hass: HomeAssistant, aioclient_mock, config_entry) -> None:
    aioclient_mock.get(METRICS_URL, exc=TimeoutError())
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_no_update_entity_without_version(
    hass: HomeAssistant, mock_authelia, config_entry
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={"scan_interval": 30})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("update.authelia") is None


async def test_unload(hass: HomeAssistant, mock_authelia, config_entry) -> None:
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics(hass: HomeAssistant, mock_authelia, config_entry) -> None:
    from custom_components.authelia.diagnostics import async_get_config_entry_diagnostics

    await _setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["entry"]["data"]["host"] == "**REDACTED**"
    assert "authelia_authn" in diag["metrics"]["raw_families"]


async def test_setup_succeeds_without_authelia_metrics(
    hass: HomeAssistant, aioclient_mock, config_entry
) -> None:
    """Frisch gestartetes Authelia: Endpoint da, Zähler noch nicht."""
    from .conftest import GITHUB_URL, HEALTH_URL, METRICS_URL, RELEASE_JSON

    fresh = "# TYPE go_goroutines gauge\ngo_goroutines 21\n"
    aioclient_mock.get(METRICS_URL, text=fresh)
    aioclient_mock.get(HEALTH_URL, text="OK")
    aioclient_mock.get(f"{HEALTH_URL}/verbose", status=404)
    aioclient_mock.get(GITHUB_URL, json=RELEASE_JSON)

    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    telemetry = hass.states.get("binary_sensor.authelia_telemetry")
    assert telemetry.state == "on"
    assert telemetry.attributes["waiting_for_first_event"] is True
    # Zähler stehen auf 0 statt "nicht verfügbar"
    assert hass.states.get("sensor.authelia_first_factor_failed").state == "0.0"
    assert hass.states.get("binary_sensor.authelia_reachable").state == "on"

    # Sobald Authelia Ereignisse zählt, verschwindet der Wartezustand
    aioclient_mock.clear_requests()
    aioclient_mock.get(METRICS_URL, text=REAL_METRICS)
    await config_entry.runtime_data.metrics.async_refresh()
    await hass.async_block_till_done()
    telemetry = hass.states.get("binary_sensor.authelia_telemetry")
    assert telemetry.attributes["waiting_for_first_event"] is False
    assert hass.states.get("sensor.authelia_first_factor_failed").state == "1.0"
