"""Diagnose-Download."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import AutheliaConfigEntry

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AutheliaConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data
    metrics = data.metrics.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "metrics": {
            "last_update_success": data.metrics.last_update_success,
            "fetched_at": metrics.fetched_at.isoformat() if metrics else None,
            "window_coverage_seconds": metrics.window_coverage if metrics else None,
            "counter_resets": metrics.counter_resets if metrics else None,
            "raw_families": metrics.metrics.raw_family_names if metrics else None,
            "values": {k: str(v) for k, v in metrics.values.items()} if metrics else None,
        },
        "health": asdict(data.health.data) if data.health.data else None,
        "release": (
            {"version": data.release.data.version, "published_at": data.release.data.published_at}
            if data.release.data
            else None
        ),
    }
