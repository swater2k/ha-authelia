# Authelia für Home Assistant

Custom Integration (HACS), die [Authelia](https://www.authelia.com) in Home Assistant sichtbar macht:
Login-Statistiken (1FA/2FA/Passkey), Autorisierungs-Requests, Antwortzeiten, Health-Status und Updates.

> Status: **in Entwicklung** – Meilenstein 2 (Config-Flow, Sensoren, Events, Diagnostics).

## Voraussetzung in Authelia

Telemetry aktivieren (`/etc/authelia/configuration.yml`):

```yaml
telemetry:
  metrics:
    enabled: true
    address: 'tcp://0.0.0.0:9959/metrics'
```

Port 9959 **nur im LAN** erreichbar machen – niemals über Reverse Proxy oder Tunnel veröffentlichen.

## Datenquellen

| Quelle | Endpoint | Auth |
|---|---|---|
| Prometheus-Metriken | `http://<authelia>:9959/metrics` | keine |
| Liveness | `http://<authelia>:9091/api/health` | keine |
| Readiness (optional) | `http://<authelia>:9091/api/health/verbose` | keine |
| Update-Info | GitHub Releases API | keine |

## Entwicklung

```bash
pip install -r requirements_test.txt ruff
ruff check custom_components tests
pytest -q
```
