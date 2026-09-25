"""Async-Client für Authelia (Metrics, Health) und GitHub-Releases.

Keine Home-Assistant-Imports: Die Session wird von außen hereingereicht
(in HA über ``async_get_clientsession``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

import aiohttp

from .metrics import AutheliaMetrics, MetricsParseError

GITHUB_LATEST_RELEASE = "https://api.github.com/repos/authelia/authelia/releases/latest"
DEFAULT_TIMEOUT = 10


def _describe(err: BaseException, timeout: aiohttp.ClientTimeout) -> str:
    """Lesbare Ursache; TimeoutError hat von sich aus keinen Text."""
    if isinstance(err, (TimeoutError, asyncio.TimeoutError)):
        return f"Zeitüberschreitung nach {timeout.total:g} s"
    return str(err) or type(err).__name__


class AutheliaError(Exception):
    """Basisfehler."""


class AutheliaConnectionError(AutheliaError):
    """Host nicht erreichbar / Timeout / TLS-Fehler."""


class AutheliaMetricsError(AutheliaError):
    """Metrics-Endpoint antwortet, liefert aber keine Authelia-Metriken."""


class AutheliaAgentAuthError(AutheliaError):
    """Agent lehnt das Token ab."""


class AutheliaAgentError(AutheliaError):
    """Agent antwortet unerwartet (falsche API-Version, DB-Fehler, ...)."""


class HealthState(StrEnum):
    OK = "ok"
    UNHEALTHY = "unhealthy"  # z. B. 503 bei /api/health/verbose
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class HealthResult:
    state: HealthState
    status_code: int | None
    latency_ms: float | None
    verbose_available: bool | None = None
    verbose_ok: bool | None = None


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str  # ohne führendes "v"
    name: str
    url: str
    published_at: str
    body: str


class AutheliaClient:
    """Dünner Wrapper um die HTTP-Aufrufe."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        metrics_url: str,
        health_url: str,
        *,
        verify_ssl: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self.metrics_url = metrics_url
        self.health_url = health_url.rstrip("/")
        self._ssl: bool | None = None if verify_ssl else False
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    # ------------------------------------------------------------------ #

    async def fetch_metrics_text(self) -> str:
        try:
            async with self._session.get(
                self.metrics_url, ssl=self._ssl, timeout=self._timeout
            ) as resp:
                if resp.status == 404:
                    raise AutheliaMetricsError(
                        f"{self.metrics_url} liefert 404 – falscher Pfad?"
                    )
                resp.raise_for_status()
                return await resp.text()
        except AutheliaError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise AutheliaConnectionError(
                f"Metrics nicht erreichbar ({self.metrics_url}): {_describe(err, self._timeout)}"
            ) from err

    async def fetch_metrics(self, *, require_authelia: bool = True) -> AutheliaMetrics:
        """Metriken abrufen.

        ``require_authelia`` trennt zwei Situationen: Bei der Einrichtung soll
        ein falscher Port sofort auffallen. Im laufenden Betrieb ist ein
        Endpoint ohne ``authelia_*``-Familien dagegen normal, solange Authelia
        nach einem Neustart noch keine Anfrage verarbeitet hat – die Zähler
        entstehen erst beim ersten Ereignis.
        """
        text = await self.fetch_metrics_text()
        try:
            metrics = AutheliaMetrics.from_text(text)
        except MetricsParseError as err:
            raise AutheliaMetricsError(f"Antwort ist kein Prometheus-Format: {err}") from err
        if require_authelia and not metrics.has_authelia_metrics:
            raise AutheliaMetricsError(
                "Endpoint liefert keine authelia_*-Metriken – ist es der Authelia-Telemetry-Port?"
            )
        return metrics

    # ------------------------------------------------------------------ #

    async def _probe(self, url: str) -> tuple[int | None, float | None]:
        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            async with self._session.get(url, ssl=self._ssl, timeout=self._timeout) as resp:
                await resp.read()
                return resp.status, (loop.time() - start) * 1000
        except (TimeoutError, aiohttp.ClientError):
            return None, None

    async def check_health(self, *, verbose: bool = True) -> HealthResult:
        """/api/health (Liveness) und optional /api/health/verbose (Readiness)."""
        status, latency = await self._probe(self.health_url)
        if status is None:
            return HealthResult(HealthState.UNREACHABLE, None, None)

        verbose_available: bool | None = None
        verbose_ok: bool | None = None
        if verbose:
            v_status, _ = await self._probe(f"{self.health_url}/verbose")
            if v_status in (200, 503):
                verbose_available = True
                verbose_ok = v_status == 200
            else:
                verbose_available = False

        healthy = status == 200 and verbose_ok is not False
        return HealthResult(
            HealthState.OK if healthy else HealthState.UNHEALTHY,
            status,
            latency,
            verbose_available,
            verbose_ok,
        )

    # ------------------------------------------------------------------ #

    async def fetch_latest_release(self) -> ReleaseInfo:
        headers = {"Accept": "application/vnd.github+json"}
        try:
            async with self._session.get(
                GITHUB_LATEST_RELEASE, headers=headers, timeout=self._timeout
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise AutheliaConnectionError(
                f"GitHub nicht erreichbar: {_describe(err, self._timeout)}"
            ) from err
        tag = str(data.get("tag_name", ""))
        return ReleaseInfo(
            version=tag.removeprefix("v"),
            name=str(data.get("name") or tag),
            url=str(data.get("html_url", "")),
            published_at=str(data.get("published_at", "")),
            body=str(data.get("body") or ""),
        )


class AutheliaAgentClient:
    """Client für den Authelia HA Agent (read-only Datenbank-Bridge)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str,
        *,
        verify_ssl: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        api_version: int = 1,
    ) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._token = token
        self._ssl: bool | None = None if verify_ssl else False
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._api_version = api_version

    async def fetch_summary(self, since_id: int | None = None) -> dict:
        params = {} if since_id is None else {"since_id": str(since_id)}
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.get(
                f"{self.url}/api/v1/summary",
                params=params,
                headers=headers,
                ssl=self._ssl,
                timeout=self._timeout,
            ) as resp:
                if resp.status == 401:
                    raise AutheliaAgentAuthError("Agent-Token abgelehnt")
                if resp.status == 503:
                    detail = (await resp.json(content_type=None)).get("detail", "")
                    raise AutheliaAgentError(f"Agent meldet Datenbankfehler: {detail}")
                if resp.status != 200:
                    raise AutheliaAgentError(f"Agent antwortet mit HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except AutheliaError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise AutheliaConnectionError(
                f"Agent nicht erreichbar ({self.url}): {_describe(err, self._timeout)}"
            ) from err
        except ValueError as err:
            raise AutheliaAgentError("Agent liefert kein JSON") from err
        if not isinstance(data, dict) or data.get("api_version") != self._api_version:
            found = data.get("api_version") if isinstance(data, dict) else "?"
            raise AutheliaAgentError(f"Inkompatible Agent-API-Version: {found}")
        return data
