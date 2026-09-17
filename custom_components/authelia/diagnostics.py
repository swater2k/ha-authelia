"""Diagnose-Download."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import AutheliaConfigEntry
from .const import CONF_AGENT_TOKEN, CONF_AGENT_URL

TO_REDACT = {CONF_HOST, CONF_AGENT_TOKEN, CONF_AGENT_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AutheliaConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data
    metrics = data.metrics.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "metrics": {
            "last_update_success": data.metrics.last_update_success,
            "fetched_at": metrics.fetched_at.isoformat() if metrics else None,
            "window_coverage_seconds": metrics.window_coverage if metrics else None,
            "counter_resets": metrics.counter_resets if metrics else None,
            "raw_families": metrics.metrics.raw_family_names if metrics else None,
            "values": {k: str(v) for k, v in metrics.values.items()} if metrics else None,
        },
        "agent": _agent_diagnostics(data.agent),
        "health": asdict(data.health.data) if data.health.data else None,
        "release": (
            {"version": data.release.data.version, "published_at": data.release.data.published_at}
            if data.release.data
            else None
        ),
    }


def _agent_diagnostics(agent: Any) -> dict[str, Any] | None:
    """Nur Strukturen und Zähler – keine Benutzernamen, IPs oder Gerätenamen."""
    if agent is None:
        return None
    result: dict[str, Any] = {"last_update_success": agent.last_update_success}
    if (a := agent.data) is None:
        return result
    summary = a.summary
    result.update(
        {
            "api_version": summary.get("api_version"),
            "agent_version": summary.get("agent_version"),
            "authelia_version": summary.get("authelia_version"),
            "schema": summary.get("schema"),
            "logins_supported": a.logins.get("supported"),
            "latest_log_id": a.logins.get("latest_id"),
            "last_24h": {
                k: v for k, v in a.last_24h.items() if k != "by_type"
            } | {"auth_types": sorted((a.last_24h.get("by_type") or {}).keys())},
            "bans_supported": a.bans.get("supported"),
            "active_bans": {
                "users": len(a.bans.get("users") or []),
                "ips": len(a.bans.get("ips") or []),
            },
            "second_factor": {
                k: len(v or []) for k, v in a.second_factor.items()
            },
            "users": {
                "supported": a.users.get("supported"),
                "error": a.users.get("error"),
                "backend": a.users.get("backend"),
                "total": len(a.user_list()),
                "without_2fa": len(a.users_without_2fa()),
                "legacy_hash": len(a.users_with_legacy_hash()),
                "groups": len(a.users.get("groups") or {}),
                "hash_algorithms": sorted({u.get("password_algorithm") for u in a.user_list()}),
            },
            "config": a.config,  # nur Allow-List-Werte, keine Secrets
        }
    )
    return result
