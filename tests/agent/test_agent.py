"""Tests für den Authelia HA Agent (reine Standardbibliothek)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from agent.authelia_ha_agent import (
    AutheliaStore,
    Settings,
    make_server,
    parse_authelia_version,
    parse_timestamp,
)

SCHEMA = (Path(__file__).parent / "schema_v29.sql").read_text()
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
TOKEN = "t" * 40


def _ts(delta: timedelta, fmt: str = "go") -> str:
    dt = NOW + delta
    if fmt == "go":  # Format des Go-SQLite-Treibers
        return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond:06d}123+00:00"
    if fmt == "berlin":
        return (dt + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S+02:00")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO migrations (version_before, version_after, application_version) VALUES (28, 29, 'v4.39.27')"
    )
    logs = [
        (_ts(-timedelta(days=2)), 1, 0, "micha", "1FA", "192.168.178.20"),
        (_ts(-timedelta(hours=3)), 0, 0, "micha", "1FA", "203.0.113.7"),
        (_ts(-timedelta(hours=3), "berlin"), 0, 0, "admin", "1FA", "203.0.113.8"),
        (_ts(-timedelta(hours=2)), 0, 1, "admin", "1FA", "203.0.113.8"),
        (_ts(-timedelta(hours=1), "plain"), 1, 0, "micha", "1FA", "192.168.178.20"),
        (_ts(-timedelta(minutes=59)), 1, 0, "micha", "TOTP", "192.168.178.20"),
    ]
    conn.executemany(
        "INSERT INTO authentication_logs (time, successful, banned, username, auth_type, remote_ip, request_uri, request_method)"
        " VALUES (?, ?, ?, ?, ?, ?, 'https://secret.example/?x=1', 'POST')",
        logs,
    )
    conn.executemany(
        "INSERT INTO banned_user (time, expires, expired, revoked, username, source, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (_ts(-timedelta(minutes=2)), _ts(timedelta(minutes=3)), None, 0, "admin", "regulation", "too many"),
            (_ts(-timedelta(hours=1)), _ts(-timedelta(minutes=30)), None, 0, "old", "regulation", None),
            (_ts(-timedelta(hours=1)), None, None, 1, "revoked", "cli", None),
        ],
    )
    conn.execute(
        "INSERT INTO banned_ip (time, expires, revoked, ip, source) VALUES (?, NULL, 0, '203.0.113.9', 'cli')",
        (_ts(-timedelta(minutes=5)),),
    )
    conn.execute(
        "INSERT INTO totp_configurations (created_at, last_used_at, username, secret) VALUES (?, ?, 'micha', X'00')",
        (_ts(-timedelta(days=30)), _ts(-timedelta(minutes=59))),
    )
    conn.execute(
        "INSERT INTO webauthn_credentials (rpid, username, description, kid, discoverable, clone_warning, public_key)"
        " VALUES ('auth.robben.tech', 'micha', 'YubiKey', 'kid1', 1, 0, X'01')"
    )
    conn.commit()
    conn.close()
    return path


def test_parse_timestamp_formats() -> None:
    assert parse_timestamp("2026-09-17 09:39:17.428771123+00:00") == datetime(
        2026, 9, 17, 9, 39, 17, 428771, tzinfo=UTC
    )
    assert parse_timestamp("2026-09-17 11:39:17+02:00") == datetime(2026, 9, 17, 9, 39, 17, tzinfo=UTC)
    assert parse_timestamp("2026-09-17T09:39:17Z").tzinfo is UTC
    assert parse_timestamp("2026-09-17 09:39:17") == datetime(2026, 9, 17, 9, 39, 17, tzinfo=UTC)
    assert parse_timestamp(None) is None
    assert parse_timestamp("garbage") is None


def test_parse_version() -> None:
    assert parse_authelia_version("authelia version v4.39.27\n") == "4.39.27"
    assert parse_authelia_version("nope") is None


def test_summary(db: Path) -> None:
    data = AutheliaStore(str(db)).summary(since_id=None, now=NOW)

    assert data["schema"] == {"version": 29, "application_version": "v4.39.27"}

    bans = data["bans"]
    assert [b["username"] for b in bans["users"]] == ["admin"]  # abgelaufen/revoked gefiltert
    assert bans["users"][0]["permanent"] is False
    assert bans["ips"][0]["ip"] == "203.0.113.9" and bans["ips"][0]["permanent"] is True

    logins = data["logins"]
    assert logins["latest_id"] == 6
    assert logins["events"] == []  # ohne since_id keine Events
    stats = logins["last_24h"]
    assert stats["total"] == 5
    assert stats["successful"] == 2
    assert stats["failed"] == 3
    assert stats["banned"] == 1
    assert stats["unique_failed_ips"] == 2
    assert stats["unique_failed_users"] == 2
    assert stats["by_type"]["TOTP"] == {"successful": 1, "failed": 0}
    assert logins["last_successful"]["auth_type"] == "TOTP"
    assert logins["last_failed"]["username"] == "admin"
    assert logins["per_user"]["micha"]["failed_24h"] == 1
    assert "request_uri" not in json.dumps(data)

    sf = data["second_factor"]
    assert sf["totp"][0]["username"] == "micha"
    assert "secret" not in sf["totp"][0]
    assert sf["webauthn"][0]["passkey"] is True
    assert "public_key" not in sf["webauthn"][0]


def test_events_since(db: Path) -> None:
    store = AutheliaStore(str(db))
    data = store.summary(since_id=4, now=NOW)
    assert [e["id"] for e in data["logins"]["events"]] == [5, 6]
    assert store.summary(since_id=6, now=NOW)["logins"]["events"] == []


def test_missing_tables(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite3"
    sqlite3.connect(path).close()
    data = AutheliaStore(str(path)).summary(since_id=0, now=NOW)
    assert data["logins"]["supported"] is False
    assert data["bans"]["supported"] is False


def test_database_is_read_only(db: Path) -> None:
    store = AutheliaStore(str(db))
    with pytest.raises(sqlite3.OperationalError), store._connect() as conn:
        conn.execute("DELETE FROM authentication_logs")


@pytest.fixture
def server(db: Path, socket_enabled):
    srv = make_server(
        Settings(token=TOKEN, bind="127.0.0.1", port=0, db_path=str(db), config_path=str(db) + ".missing.yml")
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url: str, token: str | None = None) -> tuple[int, dict]:
    req = Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as err:
        return err.code, json.loads(err.read())


def test_http_auth_and_summary(server: str) -> None:
    assert _get(f"{server}/health")[0] == 200
    assert _get(f"{server}/api/v1/summary")[0] == 401
    assert _get(f"{server}/api/v1/summary", "wrong")[0] == 401
    assert _get(f"{server}/api/v1/summary?since_id=x", TOKEN)[0] == 400
    status, body = _get(f"{server}/api/v1/summary?since_id=5", TOKEN)
    assert status == 200
    assert body["api_version"] == 1
    assert body["users"] == {"supported": False, "error": "config_not_found"}
    assert [e["id"] for e in body["logins"]["events"]] == [6]
    assert _get(f"{server}/nope", TOKEN)[0] == 404


def test_token_too_short(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TOKEN", "short")
    with pytest.raises(SystemExit):
        Settings.from_env()


# --------------------------------------------------------------------------- #
# Benutzer und Konfiguration
# --------------------------------------------------------------------------- #

from agent.authelia_ha_agent import AutheliaConfigReader, hash_algorithm  # noqa: E402

USERS_YML = """
users:
  micha:
    disabled: false
    displayname: 'Micha'
    password: '$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA'
    email: 'micha@example.com'
    given_name: 'Micha'
    family_name: 'R'
    locale: 'de-DE'
    groups: ['admins', 'dev']
  anna:
    displayname: 'Anna'
    password: '$6$rounds=50000$salt$hash'
    email: 'anna@example.com'
    groups: ['family']
  gast:
    displayname: 'Gast'
    password: '$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA'
    email: ''
    disabled: true
    groups: []
"""

CONFIG_YML = """
log:
  level: 'info'
telemetry:
  metrics:
    enabled: true
totp:
  issuer: 'robben.tech'
webauthn:
  disable: false
  enable_passkey_login: true
session:
  secret: 'SUPER-SECRET-DO-NOT-LEAK'
  inactivity: '5m'
  cookies:
    - domain: 'robben.tech'
      authelia_url: 'https://auth.robben.tech'
      expiration: '1h'
      remember_me: '1M'
regulation:
  max_retries: 3
  find_time: '2m'
  ban_time: '5m'
  modes: ['user', 'ip']
authentication_backend:
  password_reset:
    disable: false
  file:
    path: '{users}'
password_policy:
  zxcvbn:
    enabled: true
access_control:
  default_policy: 'deny'
  rules:
    - domain: 'ha.robben.tech'
      policy: 'two_factor'
    - domain: 'public.robben.tech'
      policy: 'bypass'
    - domain: 'pbs.robben.dev'
      policy: 'two_factor'
storage:
  encryption_key: 'ANOTHER-SECRET'
  local:
    path: '/etc/authelia/db.sqlite3'
identity_validation:
  reset_password:
    jwt_secret: '{{{{ env "JWT" }}}}'
notifier:
  smtp:
    address: 'submission://smtp-relay.brevo.com:587'
    password: 'SMTP-SECRET'
"""


@pytest.fixture
def config_files(tmp_path: Path) -> Path:
    users = tmp_path / "users.yml"
    users.write_text(USERS_YML)
    config = tmp_path / "configuration.yml"
    config.write_text(CONFIG_YML.format(users=users))
    return config


SECOND_FACTOR = {
    "totp": [{"username": "micha"}],
    "webauthn": [{"username": "micha", "description": "YubiKey", "passkey": True}],
    "duo": [],
}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("$argon2id$v=19$...", "argon2id"),
        ("$6$rounds=5000$x$y", "sha512crypt"),
        ("$2b$12$abc", "bcrypt"),
        ("$pbkdf2-sha512$310000$x$y", "pbkdf2-sha512"),
        ("plaintext", "unknown"),
        (None, "none"),
    ],
)
def test_hash_algorithm(value, expected) -> None:
    assert hash_algorithm(value) == expected


def test_users(config_files: Path) -> None:
    data = AutheliaConfigReader(str(config_files)).read(SECOND_FACTOR)
    users = data["users"]
    assert users["supported"] is True and users["backend"] == "file"
    by_name = {u["username"]: u for u in users["users"]}
    assert list(by_name) == ["anna", "gast", "micha"]

    assert by_name["micha"]["has_second_factor"] is True
    assert by_name["micha"]["passkeys"] == 1
    assert by_name["anna"]["has_second_factor"] is False
    assert by_name["anna"]["password_algorithm"] == "sha512crypt"
    assert by_name["anna"]["legacy_password_hash"] is True
    assert by_name["gast"]["disabled"] is True
    assert by_name["gast"]["has_email"] is False
    assert users["groups"] == {"admins": ["micha"], "dev": ["micha"], "family": ["anna"]}

    text = json.dumps(data)
    for secret in ("$argon2id", "micha@example.com", "SUPER-SECRET", "SMTP-SECRET", "ANOTHER-SECRET"):
        assert secret not in text


def test_config(config_files: Path) -> None:
    cfg = AutheliaConfigReader(str(config_files)).read(SECOND_FACTOR)["config"]
    assert cfg["access_control"] == {
        "default_policy": "deny",
        "rules": 3,
        "rules_by_policy": {"two_factor": 2, "bypass": 1},
    }
    assert cfg["regulation"] == {"max_retries": 3, "find_time": "2m", "ban_time": "5m", "modes": ["user", "ip"]}
    assert cfg["session"] == {"expiration": "1h", "inactivity": "5m", "remember_me": "1M", "cookie_domains": 1}
    assert cfg["password_policy"] == {"standard": False, "zxcvbn": True}
    assert cfg["authentication_backend"]["type"] == "file"
    assert cfg["second_factor"]["passkey_login"] is True
    assert cfg["notifier"] == "smtp"
    assert cfg["storage"] == "local"
    assert cfg["telemetry_metrics"] is True
    assert cfg["log_level"] == "info"


def test_config_ldap_and_missing(tmp_path: Path) -> None:
    ldap = tmp_path / "ldap.yml"
    ldap.write_text("authentication_backend:\n  ldap:\n    address: 'ldap://x'\n    password: 'secret'\n")
    data = AutheliaConfigReader(str(ldap)).read(SECOND_FACTOR)
    assert data["users"] == {"supported": False, "backend": "ldap", "error": "ldap_not_supported"}
    assert data["config"]["authentication_backend"]["type"] == "ldap"
    assert "secret" not in json.dumps(data)

    missing = AutheliaConfigReader(str(tmp_path / "nope.yml")).read(SECOND_FACTOR)
    assert missing["users"]["error"] == "config_not_found"


def test_yaml_cache_reloads_on_change(config_files: Path) -> None:
    reader = AutheliaConfigReader(str(config_files))
    assert reader.read(SECOND_FACTOR)["config"]["log_level"] == "info"
    import os
    import time as _time

    config_files.write_text(config_files.read_text().replace("level: 'info'", "level: 'debug'"))
    stat = config_files.stat()
    os.utime(config_files, (stat.st_atime, stat.st_mtime + 5))
    _time.sleep(0)
    assert reader.read(SECOND_FACTOR)["config"]["log_level"] == "debug"
