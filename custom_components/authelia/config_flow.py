"""Config-, Reconfigure- und Options-Flow."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_SSL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from . import build_urls
from .api import (
    AutheliaAgentAuthError,
    AutheliaAgentClient,
    AutheliaAgentError,
    AutheliaClient,
    AutheliaConnectionError,
    AutheliaMetricsError,
    HealthState,
)
from .const import (
    AGENT_API_VERSION,
    CONF_AGENT_TOKEN,
    CONF_AGENT_URL,
    CONF_INSTALLED_VERSION,
    CONF_METRICS_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_PORT,
    DEFAULT_METRICS_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVER_PORT,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_PORT = NumberSelector(NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX))


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
            vol.Required(
                CONF_SERVER_PORT, default=defaults.get(CONF_SERVER_PORT, DEFAULT_SERVER_PORT)
            ): _PORT,
            vol.Required(
                CONF_METRICS_PORT, default=defaults.get(CONF_METRICS_PORT, DEFAULT_METRICS_PORT)
            ): _PORT,
            vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, False)): bool,
            vol.Required(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, True)): bool,
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_HOST] = data[CONF_HOST].strip().removeprefix("http://").removeprefix("https://")
    data[CONF_HOST] = data[CONF_HOST].rstrip("/")
    data[CONF_SERVER_PORT] = int(data[CONF_SERVER_PORT])
    data[CONF_METRICS_PORT] = int(data[CONF_METRICS_PORT])
    return data


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Gibt Fehler-Dict zurück (leer = ok)."""
    metrics_url, health_url, _ = build_urls(data)
    client = AutheliaClient(
        async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL]),
        metrics_url,
        health_url,
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    try:
        await client.fetch_metrics()
    except AutheliaConnectionError:
        return {"base": "metrics_unreachable"}
    except AutheliaMetricsError:
        return {"base": "metrics_invalid"}
    except Exception:
        _LOGGER.exception("Unerwarteter Fehler bei der Validierung")
        return {"base": "unknown"}
    if (await client.check_health(verbose=False)).state is HealthState.UNREACHABLE:
        return {"base": "server_unreachable"}
    return {}


async def validate_agent(
    hass: HomeAssistant, url: str, token: str, verify_ssl: bool
) -> dict[str, str]:
    client = AutheliaAgentClient(
        async_get_clientsession(hass, verify_ssl=verify_ssl),
        url,
        token,
        verify_ssl=verify_ssl,
        api_version=AGENT_API_VERSION,
    )
    try:
        await client.fetch_summary()
    except AutheliaAgentAuthError:
        return {CONF_AGENT_TOKEN: "agent_auth"}
    except AutheliaConnectionError:
        return {CONF_AGENT_URL: "agent_unreachable"}
    except AutheliaAgentError:
        return {CONF_AGENT_URL: "agent_invalid"}
    except Exception:
        _LOGGER.exception("Unerwarteter Fehler bei der Agent-Validierung")
        return {"base": "unknown"}
    return {}


class AutheliaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalize(user_input)
            await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_SERVER_PORT]}")
            self._abort_if_unique_id_configured()
            if not (errors := await validate_input(self.hass, data)):
                return self.async_create_entry(title=f"Authelia ({data[CONF_HOST]})", data=data)
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalize(user_input)
            await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_SERVER_PORT]}")
            self._abort_if_unique_id_mismatch(reason="different_instance")
            if not (errors := await validate_input(self.hass, data)):
                return self.async_update_reload_and_abort(entry, data_updates=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AutheliaOptionsFlow:
        return AutheliaOptionsFlow()


class AutheliaOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        opts = dict(self.config_entry.options)
        if user_input is not None:
            data = {
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                CONF_INSTALLED_VERSION: (user_input.get(CONF_INSTALLED_VERSION) or "")
                .strip()
                .removeprefix("v"),
                CONF_AGENT_URL: (user_input.get(CONF_AGENT_URL) or "").strip().rstrip("/"),
                CONF_AGENT_TOKEN: (user_input.get(CONF_AGENT_TOKEN) or "").strip(),
            }
            if data[CONF_AGENT_URL] and not data[CONF_AGENT_URL].startswith(("http://", "https://")):
                data[CONF_AGENT_URL] = f"http://{data[CONF_AGENT_URL]}"
            if data[CONF_AGENT_URL] and not data[CONF_AGENT_TOKEN]:
                errors[CONF_AGENT_TOKEN] = "agent_token_missing"
            elif data[CONF_AGENT_URL]:
                errors = await validate_agent(
                    self.hass,
                    data[CONF_AGENT_URL],
                    data[CONF_AGENT_TOKEN],
                    self.config_entry.data.get(CONF_VERIFY_SSL, True),
                )
            else:
                data[CONF_AGENT_TOKEN] = ""
            if not errors:
                return self.async_create_entry(data=data)
            opts = {**opts, **data}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_AGENT_URL,
                    description={"suggested_value": opts.get(CONF_AGENT_URL, "")},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Optional(
                    CONF_AGENT_TOKEN,
                    description={"suggested_value": opts.get(CONF_AGENT_TOKEN, "")},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Optional(
                    CONF_INSTALLED_VERSION,
                    description={"suggested_value": opts.get(CONF_INSTALLED_VERSION, "")},
                ): TextSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
