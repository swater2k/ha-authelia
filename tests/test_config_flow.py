"""Config-, Reconfigure- und Options-Flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.authelia.const import DOMAIN

from .conftest import ENTRY_DATA, HEALTH_URL, HOST, METRICS_URL


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def test_user_flow_success(hass: HomeAssistant, mock_authelia) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, "host": f" http://{HOST}/ "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == HOST
    assert result["result"].unique_id == f"{HOST}:9091"


async def test_user_flow_errors(hass: HomeAssistant, aioclient_mock) -> None:
    result = await _start(hass)

    aioclient_mock.get(METRICS_URL, exc=TimeoutError())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["errors"] == {"base": "metrics_unreachable"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(METRICS_URL, text="go_goroutines 3\n")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["errors"] == {"base": "metrics_invalid"}

    aioclient_mock.clear_requests()
    from .conftest import REAL_METRICS

    aioclient_mock.get(METRICS_URL, text=REAL_METRICS)
    aioclient_mock.get(HEALTH_URL, exc=TimeoutError())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["errors"] == {"base": "server_unreachable"}


async def test_duplicate(hass: HomeAssistant, mock_authelia, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant, mock_authelia, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, "verify_ssl": False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["verify_ssl"] is False


async def test_options(hass: HomeAssistant, mock_authelia, config_entry) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 60, "installed_version": " v4.39.26 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "scan_interval": 60,
        "installed_version": "4.39.26",
        "agent_url": "",
        "agent_token": "",
        "repair_users_without_2fa": True,
    }
