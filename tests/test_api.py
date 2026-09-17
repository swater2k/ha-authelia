"""Tests für AutheliaClient gegen einen lokalen aiohttp-Testserver."""

from pathlib import Path

import aiohttp
from aiohttp import web
import pytest

from custom_components.authelia.api import (
    AutheliaClient,
    AutheliaConnectionError,
    AutheliaMetricsError,
    HealthState,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "metrics_sample.txt").read_text()

# echter lokaler aiohttp-Server -> Sockets für diese Tests erlauben
pytestmark = pytest.mark.usefixtures("socket_enabled")


async def _start(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def _app(*, metrics_body: str = FIXTURE, verbose_status: int | None = 200) -> web.Application:
    app = web.Application()

    async def metrics(_: web.Request) -> web.Response:
        return web.Response(text=metrics_body)

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="OK")

    async def verbose(_: web.Request) -> web.Response:
        return web.Response(status=verbose_status or 200)

    app.router.add_get("/metrics", metrics)
    app.router.add_get("/api/health", health)
    if verbose_status is not None:
        app.router.add_get("/api/health/verbose", verbose)
    return app


async def test_metrics_and_health_ok() -> None:
    runner, base = await _start(_app())
    try:
        async with aiohttp.ClientSession() as session:
            client = AutheliaClient(session, f"{base}/metrics", f"{base}/api/health")
            metrics = await client.fetch_metrics()
            assert metrics.value("authn", success="false") == 9
            health = await client.check_health()
            assert health.state is HealthState.OK
            assert health.verbose_available is True
    finally:
        await runner.cleanup()


async def test_verbose_unhealthy_and_missing() -> None:
    runner, base = await _start(_app(verbose_status=503))
    try:
        async with aiohttp.ClientSession() as session:
            health = await AutheliaClient(session, f"{base}/metrics", f"{base}/api/health").check_health()
            assert health.state is HealthState.UNHEALTHY
            assert health.verbose_ok is False
    finally:
        await runner.cleanup()

    runner, base = await _start(_app(verbose_status=None))
    try:
        async with aiohttp.ClientSession() as session:
            health = await AutheliaClient(session, f"{base}/metrics", f"{base}/api/health").check_health()
            assert health.state is HealthState.OK
            assert health.verbose_available is False
    finally:
        await runner.cleanup()


async def test_non_authelia_metrics() -> None:
    runner, base = await _start(_app(metrics_body="go_goroutines 3\n"))
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AutheliaMetricsError):
                await AutheliaClient(session, f"{base}/metrics", f"{base}/api/health").fetch_metrics()
            with pytest.raises(AutheliaMetricsError):
                await AutheliaClient(session, f"{base}/nope", f"{base}/api/health").fetch_metrics()
    finally:
        await runner.cleanup()


async def test_unreachable() -> None:
    async with aiohttp.ClientSession() as session:
        client = AutheliaClient(session, "http://127.0.0.1:1/metrics", "http://127.0.0.1:1/api/health", timeout=2)
        with pytest.raises(AutheliaConnectionError):
            await client.fetch_metrics()
        assert (await client.check_health()).state is HealthState.UNREACHABLE
