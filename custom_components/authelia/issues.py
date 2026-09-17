"""Repair-Hinweise (Einstellungen → Reparaturen) auf Basis der Agent-Daten."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import CONF_REPAIR_USERS_WITHOUT_2FA, DOMAIN
from .coordinator import AutheliaAgentCoordinator

ISSUE_AGENT_AUTH = "agent_auth_failed"
ISSUE_USERS_WITHOUT_2FA = "users_without_2fa"
ISSUE_LEGACY_HASH = "legacy_password_hash"
ISSUE_DEFAULT_POLICY = "default_policy_not_deny"
ISSUE_CLONE_WARNING = "webauthn_clone_warning"

ALL_ISSUES = (
    ISSUE_AGENT_AUTH,
    ISSUE_USERS_WITHOUT_2FA,
    ISSUE_LEGACY_HASH,
    ISSUE_DEFAULT_POLICY,
    ISSUE_CLONE_WARNING,
)


def _issue_id(entry: ConfigEntry, key: str) -> str:
    return f"{key}_{entry.entry_id}"


def _set(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    active: bool,
    severity: ir.IssueSeverity = ir.IssueSeverity.WARNING,
    placeholders: dict[str, str] | None = None,
) -> None:
    issue_id = _issue_id(entry, key)
    if not active:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=severity,
        translation_key=key,
        translation_placeholders={"title": entry.title, **(placeholders or {})},
    )


@callback
def async_update_issues(
    hass: HomeAssistant, entry: ConfigEntry, agent: AutheliaAgentCoordinator
) -> None:
    """Legt Hinweise an bzw. entfernt sie, sobald das Problem behoben ist."""
    _set(hass, entry, ISSUE_AGENT_AUTH, agent.auth_failed, ir.IssueSeverity.ERROR)

    data = agent.data
    if data is None or not agent.last_update_success:
        return  # Kein aktueller Stand – bestehende Hinweise nicht verwerfen

    without_2fa = data.users_without_2fa()
    _set(
        hass,
        entry,
        ISSUE_USERS_WITHOUT_2FA,
        bool(without_2fa) and entry.options.get(CONF_REPAIR_USERS_WITHOUT_2FA, True),
        placeholders={"users": ", ".join(without_2fa)},
    )

    legacy = data.users_with_legacy_hash()
    _set(hass, entry, ISSUE_LEGACY_HASH, bool(legacy), placeholders={"users": ", ".join(legacy)})

    policy = (data.config.get("access_control") or {}).get("default_policy")
    _set(
        hass,
        entry,
        ISSUE_DEFAULT_POLICY,
        data.config.get("supported") is True and policy is not None and policy != "deny",
        placeholders={"policy": str(policy)},
    )

    clones = data.clone_warnings()
    _set(
        hass,
        entry,
        ISSUE_CLONE_WARNING,
        bool(clones),
        ir.IssueSeverity.ERROR,
        placeholders={
            "credentials": ", ".join(
                f"{c.get('username')} ({c.get('description')})" for c in clones
            )
        },
    )


@callback
def async_remove_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    for key in ALL_ISSUES:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry, key))
