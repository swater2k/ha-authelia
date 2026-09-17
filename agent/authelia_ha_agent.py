#!/usr/bin/env python3
"""Authelia HA Agent.

Small read-only companion service for the Home Assistant Authelia integration.
Runs next to Authelia, opens the SQLite storage database strictly read-only and
exposes selected, non-secret data as JSON:

    GET /health            -> liveness, no authentication
    GET /api/v1/summary    -> bans, login history, 2FA devices, version
                              (Bearer token, optional ?since_id=<int>)

Never returned: TOTP secrets, WebAuthn public keys/attestations, request URIs,
OAuth2/OIDC sessions, identity verification tokens.

Standard library only (Python >= 3.11). Configuration via environment:

    AGENT_TOKEN        required, shared secret for /api/*
    AGENT_BIND         default 0.0.0.0
    AGENT_PORT         default 9960
    AUTHELIA_DB        default /etc/authelia/db.sqlite3
    AUTHELIA_BIN       default: "authelia" from PATH
    AGENT_TLS_CERT     optional, PEM certificate -> serve HTTPS
    AGENT_TLS_KEY      optional, PEM private key
    AGENT_HISTORY_MAX  default 5000, rows scanned for 24 h aggregates
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

AGENT_VERSION = "1.0.0"
API_VERSION = 1
MAX_EVENTS = 200
VERSION_CACHE_SECONDS = 300

_LOGGER = logging.getLogger("authelia_ha_agent")

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_TS_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T ](?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?\s*(?P<tz>Z|[+-]\d{2}:?\d{2})?"
)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse timestamps as written by Authelia's SQLite driver into aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=UTC)
    else:
        match = _TS_RE.match(str(value).strip())
        if not match:
            return None
        frac = (match["frac"] or "0")[:6].ljust(6, "0")
        tz = match["tz"] or "+00:00"
        if tz == "Z":
            tz = "+00:00"
        elif ":" not in tz:
            tz = f"{tz[:3]}:{tz[3:]}"
        try:
            dt = datetime.fromisoformat(f"{match['date']}T{match['time']}.{frac}{tz}")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso(value: Any) -> str | None:
    dt = parse_timestamp(value)
    return dt.isoformat() if dt else None


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "t", "yes")
    return bool(value)


_VERSION_RE = re.compile(r"v?(\d+\.\d+\.\d+(?:[-+][\w.]+)?)")


def parse_authelia_version(output: str) -> str | None:
    match = _VERSION_RE.search(output)
    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Settings:
    token: str
    bind: str = "0.0.0.0"
    port: int = 9960
    db_path: str = "/etc/authelia/db.sqlite3"
    authelia_bin: str | None = None
    tls_cert: str | None = None
    tls_key: str | None = None
    history_max: int = 5000

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("AGENT_TOKEN", "").strip()
        if len(token) < 24:
            raise SystemExit("AGENT_TOKEN must be set and at least 24 characters long")
        return cls(
            token=token,
            bind=os.environ.get("AGENT_BIND", "0.0.0.0"),
            port=int(os.environ.get("AGENT_PORT", "9960")),
            db_path=os.environ.get("AUTHELIA_DB", "/etc/authelia/db.sqlite3"),
            authelia_bin=os.environ.get("AUTHELIA_BIN") or shutil.which("authelia"),
            tls_cert=os.environ.get("AGENT_TLS_CERT") or None,
            tls_key=os.environ.get("AGENT_TLS_KEY") or None,
            history_max=int(os.environ.get("AGENT_HISTORY_MAX", "5000")),
        )


class AutheliaStore:
    """Read-only queries against the Authelia SQLite database."""

    def __init__(self, db_path: str, history_max: int = 5000) -> None:
        self.db_path = db_path
        self.history_max = history_max

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @staticmethod
    def _tables(conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {r["name"] for r in rows}

    def summary(self, since_id: int | None, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        with self._connect() as conn:
            tables = self._tables(conn)
            return {
                "schema": self._schema(conn, tables),
                "bans": self._bans(conn, tables, now),
                "logins": self._logins(conn, tables, since_id, now),
                "second_factor": self._second_factor(conn, tables),
            }

    # -- schema ------------------------------------------------------------ #

    @staticmethod
    def _schema(conn: sqlite3.Connection, tables: set[str]) -> dict[str, Any]:
        if "migrations" not in tables:
            return {"version": None, "application_version": None}
        row = conn.execute(
            "SELECT version_after, application_version FROM migrations "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "version": row["version_after"] if row else None,
            "application_version": row["application_version"] if row else None,
        }

    # -- bans -------------------------------------------------------------- #

    def _bans(self, conn: sqlite3.Connection, tables: set[str], now: datetime) -> dict[str, Any]:
        result: dict[str, Any] = {"supported": False, "users": [], "ips": [], "latest_id": None}
        if not {"banned_user", "banned_ip"} <= tables:
            return result
        result["supported"] = True
        latest: list[str] = []
        sources = (("banned_user", "username", "users"), ("banned_ip", "ip", "ips"))
        for table, key, target in sources:
            for row in conn.execute(
                f"SELECT id, time, expires, source, reason, {key} AS subject "
                f"FROM {table} WHERE revoked = 0 AND expired IS NULL ORDER BY id"
            ):
                expires = parse_timestamp(row["expires"])
                if expires is not None and expires <= now:
                    continue
                result[target].append(
                    {
                        "id": row["id"],
                        key: row["subject"],
                        "since": iso(row["time"]),
                        "expires": expires.isoformat() if expires else None,
                        "permanent": expires is None,
                        "source": row["source"],
                        "reason": row["reason"],
                    }
                )
            max_row = conn.execute(f"SELECT MAX(id) AS m FROM {table}").fetchone()
            latest.append(f"{table}:{max_row['m'] or 0}")
        result["latest_id"] = ",".join(latest)
        return result

    # -- login history ----------------------------------------------------- #

    def _logins(
        self,
        conn: sqlite3.Connection,
        tables: set[str],
        since_id: int | None,
        now: datetime,
    ) -> dict[str, Any]:
        empty: dict[str, Any] = {
            "supported": False,
            "latest_id": None,
            "events": [],
            "events_truncated": False,
            "last_24h": {},
            "last_successful": None,
            "last_failed": None,
            "per_user": {},
        }
        if "authentication_logs" not in tables:
            return empty
        cols = (
            "id, time, successful, banned, username, auth_type, remote_ip, request_method"
        )
        max_row = conn.execute("SELECT MAX(id) AS m FROM authentication_logs").fetchone()
        latest_id = max_row["m"] or 0

        events: list[dict[str, Any]] = []
        truncated = False
        if since_id is not None and since_id < latest_id:
            rows = conn.execute(
                f"SELECT {cols} FROM authentication_logs WHERE id > ? ORDER BY id LIMIT ?",
                (since_id, MAX_EVENTS + 1),
            ).fetchall()
            truncated = len(rows) > MAX_EVENTS
            events = [self._log_row(r) for r in rows[:MAX_EVENTS]]

        cutoff = now - timedelta(hours=24)
        stats = {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "banned": 0,
            "unique_failed_ips": 0,
            "unique_failed_users": 0,
            "by_type": {},
        }
        failed_ips: set[str] = set()
        failed_users: set[str] = set()
        per_user: dict[str, dict[str, Any]] = {}
        last_successful = last_failed = None

        rows = conn.execute(
            f"SELECT {cols} FROM authentication_logs ORDER BY id DESC LIMIT ?",
            (self.history_max,),
        )
        for row in rows:
            entry = self._log_row(row)
            ok = entry["successful"]
            user = entry["username"]
            if ok and last_successful is None:
                last_successful = entry
            if not ok and last_failed is None:
                last_failed = entry

            info = per_user.setdefault(
                user, {"last_successful": None, "last_failed": None, "failed_24h": 0}
            )
            key = "last_successful" if ok else "last_failed"
            if info[key] is None:
                info[key] = {"time": entry["time"], "remote_ip": entry["remote_ip"]}

            ts = parse_timestamp(entry["time"])
            if ts is None or ts < cutoff:
                continue
            stats["total"] += 1
            bucket = stats["by_type"].setdefault(entry["auth_type"], {"successful": 0, "failed": 0})
            if entry["banned"]:
                stats["banned"] += 1
            if ok:
                stats["successful"] += 1
                bucket["successful"] += 1
            else:
                stats["failed"] += 1
                bucket["failed"] += 1
                info["failed_24h"] += 1
                failed_users.add(user)
                if entry["remote_ip"]:
                    failed_ips.add(entry["remote_ip"])

        stats["unique_failed_ips"] = len(failed_ips)
        stats["unique_failed_users"] = len(failed_users)
        return {
            "supported": True,
            "latest_id": latest_id,
            "events": events,
            "events_truncated": truncated,
            "last_24h": stats,
            "last_successful": last_successful,
            "last_failed": last_failed,
            "per_user": per_user,
            "history_scanned_max": self.history_max,
        }

    @staticmethod
    def _log_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "time": iso(row["time"]),
            "successful": as_bool(row["successful"]),
            "banned": as_bool(row["banned"]),
            "username": row["username"],
            "auth_type": row["auth_type"],
            "remote_ip": row["remote_ip"],
            "request_method": row["request_method"],
        }

    # -- 2FA devices ------------------------------------------------------- #

    @staticmethod
    def _second_factor(conn: sqlite3.Connection, tables: set[str]) -> dict[str, Any]:
        result: dict[str, Any] = {"totp": [], "webauthn": [], "duo": []}
        if "totp_configurations" in tables:
            result["totp"] = [
                {
                    "username": r["username"],
                    "created_at": iso(r["created_at"]),
                    "last_used_at": iso(r["last_used_at"]),
                    "algorithm": r["algorithm"],
                    "digits": r["digits"],
                    "period": r["period"],
                }
                for r in conn.execute(
                    "SELECT username, created_at, last_used_at, algorithm, digits, period "
                    "FROM totp_configurations ORDER BY username"
                )
            ]
        if "webauthn_credentials" in tables:
            result["webauthn"] = [
                {
                    "username": r["username"],
                    "description": r["description"],
                    "created_at": iso(r["created_at"]),
                    "last_used_at": iso(r["last_used_at"]),
                    "passkey": as_bool(r["discoverable"]),
                    "attachment": r["attachment"],
                    "backup_eligible": as_bool(r["backup_eligible"]),
                    "backup_state": as_bool(r["backup_state"]),
                    "clone_warning": as_bool(r["clone_warning"]),
                    "legacy": as_bool(r["legacy"]),
                }
                for r in conn.execute(
                    "SELECT username, description, created_at, last_used_at, discoverable, "
                    "attachment, backup_eligible, backup_state, clone_warning, legacy "
                    "FROM webauthn_credentials ORDER BY username, description"
                )
            ]
        if "duo_devices" in tables:
            result["duo"] = [
                {"username": r["username"], "method": r["method"]}
                for r in conn.execute("SELECT username, method FROM duo_devices ORDER BY username")
            ]
        return result


class VersionProbe:
    """Runs ``authelia --version`` with caching."""

    def __init__(self, binary: str | None) -> None:
        self.binary = binary
        self._lock = threading.Lock()
        self._value: str | None = None
        self._checked = 0.0

    def get(self) -> str | None:
        if not self.binary:
            return None
        with self._lock:
            if time.monotonic() - self._checked < VERSION_CACHE_SECONDS and self._checked:
                return self._value
            try:
                out = subprocess.run(
                    [self.binary, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self._value = parse_authelia_version(out.stdout + out.stderr)
            except (OSError, subprocess.TimeoutExpired) as err:
                _LOGGER.warning("Could not determine Authelia version: %s", err)
                self._value = None
            self._checked = time.monotonic()
            return self._value


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class AgentHandler(BaseHTTPRequestHandler):
    server_version = f"AutheliaHAAgent/{AGENT_VERSION}"
    sys_version = ""

    # injected by make_server
    settings: Settings
    store: AutheliaStore
    version_probe: VersionProbe

    def log_message(self, fmt: str, *args: Any) -> None:
        _LOGGER.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(
            token.strip().encode(), self.settings.token.encode()
        )

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/health":
            self._send(HTTPStatus.OK, {"status": "ok", "agent_version": AGENT_VERSION})
            return
        if url.path != "/api/v1/summary":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        since_raw = parse_qs(url.query).get("since_id", [None])[0]
        try:
            since_id = int(since_raw) if since_raw not in (None, "") else None
        except ValueError:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_since_id"})
            return

        try:
            data = self.store.summary(since_id)
        except sqlite3.Error as err:
            _LOGGER.error("Database error: %s", err)
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "database", "detail": str(err)})
            return

        self._send(
            HTTPStatus.OK,
            {
                "api_version": API_VERSION,
                "agent_version": AGENT_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
                "authelia_version": self.version_probe.get(),
                **data,
            },
        )


def make_server(settings: Settings) -> ThreadingHTTPServer:
    handler = type(
        "BoundAgentHandler",
        (AgentHandler,),
        {
            "settings": settings,
            "store": AutheliaStore(settings.db_path, settings.history_max),
            "version_probe": VersionProbe(settings.authelia_bin),
        },
    )
    server = ThreadingHTTPServer((settings.bind, settings.port), handler)
    if settings.tls_cert and settings.tls_key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(settings.tls_cert, settings.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("AGENT_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(message)s",
    )
    settings = Settings.from_env()
    if not os.path.exists(settings.db_path):
        raise SystemExit(f"Database not found: {settings.db_path}")
    server = make_server(settings)
    scheme = "https" if settings.tls_cert else "http"
    _LOGGER.info(
        "Authelia HA Agent %s listening on %s://%s:%s (db=%s)",
        AGENT_VERSION,
        scheme,
        settings.bind,
        settings.port,
        settings.db_path,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
