"""Sensoren."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AutheliaConfigEntry
from .coordinator import (
    AgentData,
    AutheliaAgentCoordinator,
    AutheliaHealthCoordinator,
    AutheliaMetricsCoordinator,
    AutheliaReleaseCoordinator,
)
from .entity import AutheliaEntity

PARALLEL_UPDATES = 0

TOTAL = SensorStateClass.TOTAL_INCREASING
MEAS = SensorStateClass.MEASUREMENT
DIAG = EntityCategory.DIAGNOSTIC


@dataclass(frozen=True, kw_only=True)
class AutheliaSensorDescription(SensorEntityDescription):
    """Beschreibt einen Metrics-Sensor; ``key`` = Schlüssel in MetricsData.values.

    ``agent_value`` liefert – falls der Agent eingerichtet ist – einen Wert aus
    der Datenbank, der den Metrics-Wert ersetzt (übersteht HA-Neustarts).
    """

    agent_value: Callable[[AgentData], Any] | None = None


def _d(key: str, **kw: Any) -> AutheliaSensorDescription:
    kw.setdefault("translation_key", key)
    return AutheliaSensorDescription(key=key, **kw)


_ms = {"native_unit_of_measurement": UnitOfTime.MILLISECONDS,
       "device_class": SensorDeviceClass.DURATION, "state_class": MEAS,
       "suggested_display_precision": 0}
_bytes = {"native_unit_of_measurement": UnitOfInformation.BYTES,
          "device_class": SensorDeviceClass.DATA_SIZE,
          "suggested_unit_of_measurement": UnitOfInformation.MEGABYTES,
          "suggested_display_precision": 1}

METRIC_SENSORS: tuple[AutheliaSensorDescription, ...] = (
    # Anmeldungen – Fenster (Default an)
    _d("failed_logins_5m", state_class=MEAS, icon="mdi:account-alert"),
    _d("failed_logins_1h", state_class=MEAS, icon="mdi:account-alert"),
    _d("failed_logins_24h", state_class=MEAS, icon="mdi:account-alert",
       agent_value=lambda a: a.last_24h.get("failed") if a.logins.get("supported") else None),
    _d("successful_logins_24h", state_class=MEAS, icon="mdi:account-check",
       agent_value=lambda a: a.logins_24h()),
    _d("banned_attempts_24h", state_class=MEAS, icon="mdi:account-cancel",
       agent_value=lambda a: a.last_24h.get("banned") if a.logins.get("supported") else None),
    _d("authz_denied_1h", state_class=MEAS, icon="mdi:shield-lock"),
    # 1FA
    _d("authn_success_total", state_class=TOTAL, icon="mdi:login"),
    _d("authn_failed_total", state_class=TOTAL, icon="mdi:login"),
    _d("authn_banned_total", state_class=TOTAL, icon="mdi:account-cancel"),
    # 2FA
    _d("second_factor_success_total", state_class=TOTAL, icon="mdi:two-factor-authentication"),
    _d("second_factor_failed_total", state_class=TOTAL, icon="mdi:two-factor-authentication"),
    _d("second_factor_banned_total", state_class=TOTAL, icon="mdi:account-cancel",
       entity_registry_enabled_default=False),
    _d("second_factor_totp_total", state_class=TOTAL, icon="mdi:cellphone-key",
       entity_registry_enabled_default=False),
    _d("second_factor_webauthn_total", state_class=TOTAL, icon="mdi:usb-flash-drive",
       entity_registry_enabled_default=False),
    _d("second_factor_duo_total", state_class=TOTAL, icon="mdi:cellphone-message",
       entity_registry_enabled_default=False),
    # Passkey
    _d("passkey_success_total", state_class=TOTAL, icon="mdi:key-variant",
       entity_registry_enabled_default=False),
    _d("passkey_failed_total", state_class=TOTAL, icon="mdi:key-variant",
       entity_registry_enabled_default=False),
    # Autorisierung
    _d("authz_granted_total", state_class=TOTAL, icon="mdi:shield-check",
       entity_registry_enabled_default=False),
    _d("authz_redirect_total", state_class=TOTAL, icon="mdi:shield-refresh",
       entity_registry_enabled_default=False),
    _d("authz_unauthorized_total", state_class=TOTAL, icon="mdi:shield-alert",
       entity_registry_enabled_default=False),
    _d("authz_forbidden_total", state_class=TOTAL, icon="mdi:shield-off",
       entity_registry_enabled_default=False),
    # Requests
    _d("requests_total", state_class=TOTAL, icon="mdi:web", entity_registry_enabled_default=False),
    _d("requests_client_errors_total", state_class=TOTAL, icon="mdi:web-remove",
       entity_registry_enabled_default=False),
    _d("requests_server_errors_total", state_class=TOTAL, icon="mdi:web-remove",
       entity_registry_enabled_default=False),
    _d("server_errors_1h", state_class=MEAS, icon="mdi:alert-circle"),
    # Laufzeiten
    _d("authn_duration_avg_1h", **_ms, entity_registry_enabled_default=False),
    _d("request_duration_avg_1h", **_ms, entity_registry_enabled_default=False),
    _d("request_duration_p95_1h", **_ms, entity_registry_enabled_default=False),
    # Prozess / Runtime
    _d("process_started", device_class=SensorDeviceClass.TIMESTAMP, entity_category=DIAG),
    _d("process_memory", **_bytes, state_class=MEAS, entity_category=DIAG),
    _d("go_heap_alloc", **_bytes, state_class=MEAS, entity_category=DIAG,
       entity_registry_enabled_default=False),
    _d("process_cpu_seconds", native_unit_of_measurement=UnitOfTime.SECONDS,
       device_class=SensorDeviceClass.DURATION, state_class=TOTAL, entity_category=DIAG,
       suggested_display_precision=1, entity_registry_enabled_default=False),
    _d("process_open_fds", state_class=MEAS, entity_category=DIAG, icon="mdi:file-multiple",
       entity_registry_enabled_default=False),
    _d("process_network_rx", **_bytes, state_class=TOTAL, entity_category=DIAG,
       entity_registry_enabled_default=False),
    _d("process_network_tx", **_bytes, state_class=TOTAL, entity_category=DIAG,
       entity_registry_enabled_default=False),
    _d("go_goroutines", state_class=MEAS, entity_category=DIAG, icon="mdi:language-go",
       entity_registry_enabled_default=False),
    _d("go_version", entity_category=DIAG, icon="mdi:language-go",
       entity_registry_enabled_default=False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutheliaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    entities: list[SensorEntity] = [
        AutheliaMetricSensor(data.metrics, entry, desc, data.agent) for desc in METRIC_SENSORS
    ]
    if data.agent is not None:
        entities.extend(AutheliaAgentSensor(data.agent, entry, desc) for desc in AGENT_SENSORS)
    entities.append(AutheliaHealthLatencySensor(data.health, entry))
    entities.append(AutheliaLatestVersionSensor(data.release, entry))
    async_add_entities(entities)


class AutheliaMetricSensor(AutheliaEntity[AutheliaMetricsCoordinator], SensorEntity):
    entity_description: AutheliaSensorDescription

    def __init__(
        self,
        coordinator: AutheliaMetricsCoordinator,
        entry: AutheliaConfigEntry,
        description: AutheliaSensorDescription,
        agent: AutheliaAgentCoordinator | None = None,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description
        self._agent = agent if description.agent_value else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._agent is not None:
            self.async_on_remove(self._agent.async_add_listener(self._handle_coordinator_update))

    def _agent_value(self) -> Any:
        agent = self._agent
        if agent is None or not agent.last_update_success or agent.data is None:
            return None
        return self.entity_description.agent_value(agent.data)  # type: ignore[misc]

    @property
    def native_value(self) -> Any:
        if (value := self._agent_value()) is not None:
            return value
        return self.coordinator.data.values.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._agent is None:
            return None
        return {"source": "database" if self._agent_value() is not None else "metrics"}


class AutheliaHealthLatencySensor(AutheliaEntity[AutheliaHealthCoordinator], SensorEntity):
    _attr_translation_key = "health_latency"
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = MEAS
    _attr_entity_category = DIAG
    _attr_suggested_display_precision = 0
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: AutheliaHealthCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "health_latency")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.latency_ms


class AutheliaLatestVersionSensor(AutheliaEntity[AutheliaReleaseCoordinator], SensorEntity):
    _attr_translation_key = "latest_version"
    _attr_entity_category = DIAG
    _attr_icon = "mdi:tag"

    def __init__(self, coordinator: AutheliaReleaseCoordinator, entry: AutheliaConfigEntry) -> None:
        super().__init__(coordinator, entry, "latest_version")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.version if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not (rel := self.coordinator.data):
            return None
        return {"release_url": rel.url, "published_at": rel.published_at}




# --------------------------------------------------------------------------- #
# Agent-Sensoren (Authelia-Datenbank)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class AutheliaAgentSensorDescription(SensorEntityDescription):
    value_fn: Callable[[AgentData], Any]
    attrs_fn: Callable[[AgentData], dict[str, Any] | None] | None = None


def _ts(value: str | None) -> Any:
    return dt_util.parse_datetime(value) if value else None


def _login_attrs(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    return {
        "username": entry.get("username"),
        "remote_ip": entry.get("remote_ip"),
        "auth_type": entry.get("auth_type"),
    }


def _ban_list(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return {
        "bans": [
            {
                key: b.get(key),
                "since": b.get("since"),
                "expires": b.get("expires"),
                "permanent": b.get("permanent"),
                "source": b.get("source"),
                "reason": b.get("reason"),
            }
            for b in items
        ]
    }


def _password_policy(a: AgentData) -> str | None:
    if not a.config.get("supported"):
        return None
    policy = a.config.get("password_policy") or {}
    if policy.get("zxcvbn"):
        return "zxcvbn"
    if policy.get("standard"):
        return "standard"
    return "disabled"


def _webauthn(a: AgentData) -> list[dict[str, Any]]:
    return a.second_factor.get("webauthn") or []


AGENT_SENSORS: tuple[AutheliaAgentSensorDescription, ...] = (
    AutheliaAgentSensorDescription(
        key="active_banned_users",
        translation_key="active_banned_users",
        icon="mdi:account-lock",
        state_class=MEAS,
        value_fn=lambda a: len(a.bans.get("users") or []) if a.bans.get("supported") else None,
        attrs_fn=lambda a: _ban_list(a.bans.get("users") or [], "username"),
    ),
    AutheliaAgentSensorDescription(
        key="active_banned_ips",
        translation_key="active_banned_ips",
        icon="mdi:ip-network-outline",
        state_class=MEAS,
        value_fn=lambda a: len(a.bans.get("ips") or []) if a.bans.get("supported") else None,
        attrs_fn=lambda a: _ban_list(a.bans.get("ips") or [], "ip"),
    ),
    AutheliaAgentSensorDescription(
        key="last_successful_login",
        translation_key="last_successful_login",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda a: _ts((a.logins.get("last_successful") or {}).get("time")),
        attrs_fn=lambda a: _login_attrs(a.logins.get("last_successful")),
    ),
    AutheliaAgentSensorDescription(
        key="last_failed_login",
        translation_key="last_failed_login",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda a: _ts((a.logins.get("last_failed") or {}).get("time")),
        attrs_fn=lambda a: _login_attrs(a.logins.get("last_failed")),
    ),
    AutheliaAgentSensorDescription(
        key="unique_failed_ips_24h",
        translation_key="unique_failed_ips_24h",
        icon="mdi:ip-network",
        state_class=MEAS,
        value_fn=lambda a: a.last_24h.get("unique_failed_ips"),
    ),
    AutheliaAgentSensorDescription(
        key="unique_failed_users_24h",
        translation_key="unique_failed_users_24h",
        icon="mdi:account-multiple-remove",
        state_class=MEAS,
        entity_registry_enabled_default=False,
        value_fn=lambda a: a.last_24h.get("unique_failed_users"),
    ),
    AutheliaAgentSensorDescription(
        key="totp_users",
        translation_key="totp_users",
        icon="mdi:cellphone-key",
        state_class=MEAS,
        value_fn=lambda a: len(a.second_factor.get("totp") or []),
        attrs_fn=lambda a: {
            "users": [
                {"username": t.get("username"), "created_at": t.get("created_at"),
                 "last_used_at": t.get("last_used_at")}
                for t in a.second_factor.get("totp") or []
            ]
        },
    ),
    AutheliaAgentSensorDescription(
        key="webauthn_credentials",
        translation_key="webauthn_credentials",
        icon="mdi:usb-flash-drive",
        state_class=MEAS,
        value_fn=lambda a: len(_webauthn(a)),
        attrs_fn=lambda a: {
            "credentials": [
                {k: c.get(k) for k in ("username", "description", "passkey", "created_at",
                                        "last_used_at", "backup_state", "clone_warning")}
                for c in _webauthn(a)
            ]
        },
    ),
    AutheliaAgentSensorDescription(
        key="passkeys",
        translation_key="passkeys",
        icon="mdi:key-variant",
        state_class=MEAS,
        entity_registry_enabled_default=False,
        value_fn=lambda a: sum(1 for c in _webauthn(a) if c.get("passkey")),
    ),
    # --- Benutzer (users.yml) -------------------------------------------- #
    AutheliaAgentSensorDescription(
        key="users_total",
        translation_key="users_total",
        icon="mdi:account-group",
        state_class=MEAS,
        value_fn=lambda a: len(a.user_list()) if a.users.get("supported") else None,
        attrs_fn=lambda a: {
            "users": [
                {k: u.get(k) for k in ("username", "displayname", "groups", "disabled",
                                        "has_second_factor", "password_algorithm")}
                for u in a.user_list()
            ]
        },
    ),
    AutheliaAgentSensorDescription(
        key="users_without_2fa",
        translation_key="users_without_2fa",
        icon="mdi:shield-account-outline",
        state_class=MEAS,
        value_fn=lambda a: len(a.users_without_2fa()) if a.users.get("supported") else None,
        attrs_fn=lambda a: {"users": a.users_without_2fa()},
    ),
    AutheliaAgentSensorDescription(
        key="users_disabled",
        translation_key="users_disabled",
        icon="mdi:account-off",
        state_class=MEAS,
        value_fn=lambda a: (
            sum(1 for u in a.user_list() if u.get("disabled")) if a.users.get("supported") else None
        ),
        attrs_fn=lambda a: {"users": [u["username"] for u in a.user_list() if u.get("disabled")]},
    ),
    AutheliaAgentSensorDescription(
        key="users_legacy_password_hash",
        translation_key="users_legacy_password_hash",
        icon="mdi:lock-alert-outline",
        state_class=MEAS,
        value_fn=lambda a: len(a.users_with_legacy_hash()) if a.users.get("supported") else None,
        attrs_fn=lambda a: {"users": a.users_with_legacy_hash()},
    ),
    AutheliaAgentSensorDescription(
        key="users_without_email",
        translation_key="users_without_email",
        icon="mdi:email-off-outline",
        state_class=MEAS,
        entity_registry_enabled_default=False,
        value_fn=lambda a: (
            sum(1 for u in a.active_users() if not u.get("has_email"))
            if a.users.get("supported") else None
        ),
        attrs_fn=lambda a: {
            "users": [u["username"] for u in a.active_users() if not u.get("has_email")]
        },
    ),
    AutheliaAgentSensorDescription(
        key="user_groups",
        translation_key="user_groups",
        icon="mdi:account-multiple",
        entity_category=DIAG,
        value_fn=lambda a: len(a.users.get("groups") or {}) if a.users.get("supported") else None,
        attrs_fn=lambda a: {"groups": a.users.get("groups") or {}},
    ),
    # --- Sicherheitskonfiguration (configuration.yml) --------------------- #
    AutheliaAgentSensorDescription(
        key="default_policy",
        translation_key="default_policy",
        icon="mdi:shield-lock-outline",
        entity_category=DIAG,
        device_class=SensorDeviceClass.ENUM,
        options=["deny", "one_factor", "two_factor", "bypass"],
        value_fn=lambda a: (a.config.get("access_control") or {}).get("default_policy"),
    ),
    AutheliaAgentSensorDescription(
        key="access_control_rules",
        translation_key="access_control_rules",
        icon="mdi:format-list-checks",
        entity_category=DIAG,
        value_fn=lambda a: (a.config.get("access_control") or {}).get("rules"),
        attrs_fn=lambda a: {
            "by_policy": (a.config.get("access_control") or {}).get("rules_by_policy") or {}
        },
    ),
    AutheliaAgentSensorDescription(
        key="bypass_rules",
        translation_key="bypass_rules",
        icon="mdi:shield-off-outline",
        entity_category=DIAG,
        value_fn=lambda a: (
            ((a.config.get("access_control") or {}).get("rules_by_policy") or {}).get("bypass", 0)
            if a.config.get("supported") else None
        ),
    ),
    AutheliaAgentSensorDescription(
        key="regulation_max_retries",
        translation_key="regulation_max_retries",
        icon="mdi:timer-lock-outline",
        entity_category=DIAG,
        value_fn=lambda a: (a.config.get("regulation") or {}).get("max_retries"),
        attrs_fn=lambda a: {
            k: v for k, v in (a.config.get("regulation") or {}).items() if k != "max_retries"
        },
    ),
    AutheliaAgentSensorDescription(
        key="session_expiration",
        translation_key="session_expiration",
        icon="mdi:timer-sand",
        entity_category=DIAG,
        value_fn=lambda a: (a.config.get("session") or {}).get("expiration"),
        attrs_fn=lambda a: {
            k: v for k, v in (a.config.get("session") or {}).items() if k != "expiration"
        },
    ),
    AutheliaAgentSensorDescription(
        key="password_policy",
        translation_key="password_policy",
        icon="mdi:form-textbox-password",
        entity_category=DIAG,
        device_class=SensorDeviceClass.ENUM,
        options=["zxcvbn", "standard", "disabled"],
        value_fn=lambda a: _password_policy(a),
    ),
    AutheliaAgentSensorDescription(
        key="notifier",
        translation_key="notifier",
        icon="mdi:email-fast-outline",
        entity_category=DIAG,
        entity_registry_enabled_default=False,
        value_fn=lambda a: a.config.get("notifier"),
        attrs_fn=lambda a: {
            "startup_check_disabled": a.config.get("notifier_startup_check_disabled"),
            "storage": a.config.get("storage"),
            "log_level": a.config.get("log_level"),
            "telemetry_metrics": a.config.get("telemetry_metrics"),
        },
    ),
    AutheliaAgentSensorDescription(
        key="authelia_version",
        translation_key="authelia_version",
        icon="mdi:tag-check",
        entity_category=DIAG,
        value_fn=lambda a: a.authelia_version,
    ),
    AutheliaAgentSensorDescription(
        key="schema_version",
        translation_key="schema_version",
        icon="mdi:database-cog",
        entity_category=DIAG,
        entity_registry_enabled_default=False,
        value_fn=lambda a: (a.summary.get("schema") or {}).get("version"),
    ),
)


class AutheliaAgentSensor(AutheliaEntity[AutheliaAgentCoordinator], SensorEntity):
    entity_description: AutheliaAgentSensorDescription

    def __init__(
        self,
        coordinator: AutheliaAgentCoordinator,
        entry: AutheliaConfigEntry,
        description: AutheliaAgentSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
