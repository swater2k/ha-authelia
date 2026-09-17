"""Integration mit Datenbank-Agent."""

from __future__ import annotations

import copy

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.authelia.const import DOMAIN
from custom_components.authelia.coordinator import classify_login

from .conftest import ENTRY_DATA, HOST, REAL_METRICS

AGENT_URL = f"http://{HOST}:9960"
SUMMARY_URL = f"{AGENT_URL}/api/v1/summary"
TOKEN = "x" * 43

SUMMARY = {
    "api_version": 1,
    "agent_version": "1.0.0",
    "authelia_version": "4.39.27",
    "schema": {"version": 29, "application_version": "v4.39.27"},
    "bans": {"supported": True, "users": [], "ips": [], "latest_id": "banned_user:0,banned_ip:0"},
    "logins": {
        "supported": True,
        "latest_id": 98,
        "events": [],
        "events_truncated": False,
        "last_24h": {
            "total": 5, "successful": 3, "failed": 2, "banned": 0,
            "unique_failed_ips": 1, "unique_failed_users": 1,
            "by_type": {"1FA": {"successful": 2, "failed": 2}, "TOTP": {"successful": 1, "failed": 0}},
        },
        "last_successful": {"id": 97, "time": "2026-09-17T09:38:00+00:00", "successful": True,
                            "banned": False, "username": "micha", "auth_type": "TOTP",
                            "remote_ip": "192.168.178.20", "request_method": "POST"},
        "last_failed": {"id": 98, "time": "2026-09-17T09:39:17+00:00", "successful": False,
                        "banned": False, "username": "micha", "auth_type": "1FA",
                        "remote_ip": "203.0.113.7", "request_method": "POST"},
        "per_user": {},
    },
    "second_factor": {
        "totp": [{"username": "micha", "created_at": None, "last_used_at": None}],
        "webauthn": [{"username": "micha", "description": "YubiKey", "passkey": True,
                      "clone_warning": False, "backup_state": False}],
        "duo": [],
    },
}


def _summary_with_new_activity() -> dict:
    data = copy.deepcopy(SUMMARY)
    data["logins"]["latest_id"] = 100
    data["logins"]["events"] = [
        {"id": 99, "time": "2026-09-17T10:00:00+00:00", "successful": False, "banned": False,
         "username": "admin", "auth_type": "1FA", "remote_ip": "203.0.113.9", "request_method": "POST"},
        {"id": 100, "time": "2026-09-17T10:00:05+00:00", "successful": False, "banned": True,
         "username": "admin", "auth_type": "1FA", "remote_ip": "203.0.113.9", "request_method": "POST"},
    ]
    data["bans"]["users"] = [{"id": 1, "username": "admin", "since": "2026-09-17T10:00:05+00:00",
                              "expires": "2026-09-17T10:05:05+00:00", "permanent": False,
                              "source": "regulation", "reason": None}]
    return data


@pytest.fixture
def agent_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=f"{HOST}:9091",
        options={"scan_interval": 30, "installed_version": "", "agent_url": AGENT_URL,
                 "agent_token": TOKEN},
    )


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"successful": True, "auth_type": "TOTP"}, "login_successful"),
        ({"successful": False, "banned": True, "auth_type": "1FA"}, "banned"),
        ({"successful": False, "auth_type": "1FA"}, "first_factor_failed"),
        ({"successful": False, "auth_type": "TOTP"}, "second_factor_failed"),
        ({"successful": False, "auth_type": "WebAuthn"}, "second_factor_failed"),
        ({"successful": False, "auth_type": "Passkey"}, "passkey_failed"),
    ],
)
def test_classify(row, expected) -> None:
    assert classify_login(row) == expected


async def test_agent_entities(hass: HomeAssistant, mock_authelia, agent_entry) -> None:
    mock_authelia.get(SUMMARY_URL, json=SUMMARY)
    agent_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(agent_entry.entry_id)
    await hass.async_block_till_done()

    # Token wird gesendet
    call = next(c for c in mock_authelia.mock_calls if str(c[1]).startswith(SUMMARY_URL))
    assert call[3]["Authorization"] == f"Bearer {TOKEN}"

    assert hass.states.get("binary_sensor.authelia_database_agent").state == "on"
    assert hass.states.get("binary_sensor.authelia_ban_active").state == "off"
    assert hass.states.get("binary_sensor.authelia_webauthn_clone_warning").state == "off"
    assert hass.states.get("sensor.authelia_active_user_bans").state == "0"
    assert hass.states.get("sensor.authelia_users_with_totp").state == "1"
    assert hass.states.get("sensor.authelia_webauthn_credentials").state == "1"
    assert hass.states.get("sensor.authelia_authelia_version").state == "4.39.27"

    last_failed = hass.states.get("sensor.authelia_last_failed_login")
    assert last_failed.state == "2026-09-17T09:39:17+00:00"
    assert last_failed.attributes["remote_ip"] == "203.0.113.7"

    # 24-h-Werte kommen aus der Datenbank
    failed = hass.states.get("sensor.authelia_failed_logins_24_h")
    assert failed.state == "2" and failed.attributes["source"] == "database"
    assert hass.states.get("sensor.authelia_successful_logins_24_h").state == "2"  # nur 1FA

    # Update-Entity ohne manuelle Version, dank Agent
    update = hass.states.get("update.authelia")
    assert update.attributes["installed_version"] == "4.39.27"
    assert update.state == "off"


async def test_agent_events(hass: HomeAssistant, mock_authelia, agent_entry) -> None:
    mock_authelia.get(SUMMARY_URL, json=SUMMARY)
    agent_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(agent_entry.entry_id)
    await hass.async_block_till_done()

    seen: list[tuple[str, dict]] = []

    @callback
    def _listener(event) -> None:
        new = event.data["new_state"]
        if (
            new
            and new.entity_id == "event.authelia_security_event"
            and "event_type" in new.attributes
        ):
            seen.append((new.attributes["event_type"], dict(new.attributes)))

    hass.bus.async_listen("state_changed", _listener)

    mock_authelia.clear_requests()
    mock_authelia.get(f"http://{HOST}:9959/metrics", text=REAL_METRICS)
    mock_authelia.get(SUMMARY_URL, json=_summary_with_new_activity())
    await agent_entry.runtime_data.agent.async_refresh()
    await hass.async_block_till_done()

    types = [t for t, _ in seen]
    assert types == ["first_factor_failed", "banned", "ban_created"]
    assert seen[0][1]["username"] == "admin"
    assert seen[0][1]["remote_ip"] == "203.0.113.9"
    assert seen[2][1]["kind"] == "user" and seen[2][1]["subject"] == "admin"
    assert hass.states.get("binary_sensor.authelia_ban_active").state == "on"

    # since_id wird mitgeschickt
    call = next(c for c in mock_authelia.mock_calls if str(c[1]).startswith(SUMMARY_URL))
    assert "since_id=98" in str(call[1])


async def test_agent_down_does_not_block(hass: HomeAssistant, mock_authelia, agent_entry) -> None:
    mock_authelia.get(SUMMARY_URL, exc=TimeoutError())
    agent_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(agent_entry.entry_id)
    await hass.async_block_till_done()
    assert agent_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.authelia_database_agent").state == "off"
    assert hass.states.get("sensor.authelia_active_user_bans").state == "unavailable"
    # Metrics funktionieren weiter, 24-h-Wert fällt auf Metrics zurück
    failed = hass.states.get("sensor.authelia_failed_logins_24_h")
    assert failed.attributes["source"] == "metrics"


async def test_options_agent_validation(hass: HomeAssistant, mock_authelia, config_entry) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    async def configure(agent_url: str, token: str):
        flow = await hass.config_entries.options.async_init(config_entry.entry_id)
        return await hass.config_entries.options.async_configure(
            flow["flow_id"],
            {"scan_interval": 30, "agent_url": agent_url, "agent_token": token},
        )

    result = await configure(AGENT_URL, "")
    assert result["errors"] == {"agent_token": "agent_token_missing"}

    mock_authelia.get(SUMMARY_URL, status=401, json={"error": "unauthorized"})
    result = await configure(AGENT_URL, "wrong")
    assert result["errors"] == {"agent_token": "agent_auth"}

    mock_authelia.clear_requests()
    mock_authelia.get(f"http://{HOST}:9959/metrics", text=REAL_METRICS)
    mock_authelia.get(f"http://{HOST}:9091/api/health", text="OK")
    mock_authelia.get(f"http://{HOST}:9091/api/health/verbose", status=404)
    mock_authelia.get("https://api.github.com/repos/authelia/authelia/releases/latest", json={"tag_name": "v4.39.27"})
    mock_authelia.get(SUMMARY_URL, json={**SUMMARY, "api_version": 2})
    result = await configure(AGENT_URL, TOKEN)
    assert result["errors"] == {"agent_url": "agent_invalid"}

    mock_authelia.clear_requests()
    mock_authelia.get(f"http://{HOST}:9959/metrics", text=REAL_METRICS)
    mock_authelia.get(f"http://{HOST}:9091/api/health", text="OK")
    mock_authelia.get(f"http://{HOST}:9091/api/health/verbose", status=404)
    mock_authelia.get("https://api.github.com/repos/authelia/authelia/releases/latest", json={"tag_name": "v4.39.27"})
    mock_authelia.get(SUMMARY_URL, json=SUMMARY)
    result = await configure(f"{HOST}:9960/", TOKEN)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options["agent_url"] == AGENT_URL


async def test_diagnostics_redacts_agent(hass: HomeAssistant, mock_authelia, agent_entry) -> None:
    from custom_components.authelia.diagnostics import async_get_config_entry_diagnostics

    mock_authelia.get(SUMMARY_URL, json=SUMMARY)
    agent_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(agent_entry.entry_id)
    await hass.async_block_till_done()
    diag = await async_get_config_entry_diagnostics(hass, agent_entry)
    assert diag["entry"]["options"]["agent_token"] == "**REDACTED**"
    assert diag["agent"]["active_bans"] == {"users": 0, "ips": 0}
    text = str(diag)
    assert "micha" not in text and "203.0.113.7" not in text
