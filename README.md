<p align="center">
  <img src="custom_components/authelia/brand/icon@2x.png" alt="Authelia integration icon" width="128">
</p>

<h1 align="center">Authelia for Home Assistant</h1>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <a href="https://github.com/swater2k/ha-authelia/releases"><img src="https://img.shields.io/github/v/release/swater2k/ha-authelia" alt="Release"></a>
  <a href="https://github.com/swater2k/ha-authelia/actions/workflows/tests.yml"><img src="https://github.com/swater2k/ha-authelia/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/swater2k/ha-authelia/actions/workflows/validate.yml"><img src="https://github.com/swater2k/ha-authelia/actions/workflows/validate.yml/badge.svg" alt="Validate"></a>
</p>

A custom integration that brings your self-hosted [Authelia](https://www.authelia.com) SSO/2FA server into Home Assistant: login statistics, failed and banned attempts, authorization results, response times, health status and release updates. It also provides a security event entity, so you can trigger automations on failed logins.

> [!NOTE]
> This is a community project and is not affiliated with or endorsed by the Authelia project.

## Features

- **Security monitoring**: failed logins in rolling windows (5 min / 1 h / 24 h), successful logins, banned attempts, denied authorizations
- **Security event entity**: fires on failed first factor, failed second factor, failed passkey and banned attempts – ready to use as an automation trigger
- **Counters** for first factor, second factor (TOTP, WebAuthn, Duo), passkeys, forward-auth results and HTTP requests
- **Performance**: average login duration, average and p95 request duration over the last hour
- **Health**: reachability via `/api/health`, readiness via `/api/health/verbose` (if available), telemetry status
- **Process diagnostics**: start time, memory, CPU time, file descriptors, network traffic, goroutines, Go version
- **Update entity** based on the latest GitHub release
- Config flow, reconfiguration, options flow, diagnostics download
- No credentials required, fully local polling (except the optional GitHub release check)

## Requirements

- Home Assistant **2026.2** or newer
- Authelia **4.36** or newer with telemetry enabled (tested with **4.39.27**)
- Network access from Home Assistant to the Authelia server port (default `9091`) and the telemetry port (default `9959`)

## Authelia configuration

Enable the Prometheus metrics endpoint in your Authelia `configuration.yml`:

```yaml
telemetry:
  metrics:
    enabled: true
    address: 'tcp://0.0.0.0:9959/metrics'
```

Restart Authelia and verify the endpoint:

```bash
curl -s http://<authelia-host>:9959/metrics | grep '^authelia_'
```

> [!IMPORTANT]
> The metrics endpoint has no authentication. Only expose it to your local network and **never** publish it through a reverse proxy or tunnel.

Some metric families (for example `authelia_authz` or `authelia_authn_passkey`) only appear after the first matching event. The integration reports `0` until then.

## Installation

### HACS (recommended)

1. Open HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/swater2k/ha-authelia` with type **Integration**
3. Search for **Authelia** and download it
4. Restart Home Assistant

### Manual

Copy `custom_components/authelia` into the `custom_components` folder of your Home Assistant configuration and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → Authelia**

| Field | Default | Description |
|---|---|---|
| Host | – | IP address or hostname of the Authelia server in your LAN |
| Server port | `9091` | Authelia web server port, used for the health check |
| Telemetry port | `9959` | Port of `telemetry.metrics` |
| Server uses HTTPS | off | Only if Authelia terminates TLS itself |
| Verify SSL certificate | on | Disable for self-signed certificates |

The setup validates both endpoints and tells you whether the telemetry port is unreachable, returns no Authelia metrics, or the health endpoint is unreachable.

### Options

| Option | Default | Description |
|---|---|---|
| Polling interval | `30 s` | Interval for metrics and health check (10–300 s) |
| Installed Authelia version | empty | e.g. `4.39.27`. Enables the update entity (see [Limitations](#limitations)) |

## Entities

All entities belong to a single **Authelia** service device. Entities marked with ✗ are disabled by default and can be enabled in the entity settings.

### Security

| Entity | Type | Default |
|---|---|---|
| Failed logins (5 min / 1 h / 24 h) | sensor | ✓ |
| Successful logins (24 h) | sensor | ✓ |
| Banned attempts (24 h) | sensor | ✓ |
| Denied authorizations (1 h) | sensor | ✓ |
| Security event | event | ✓ |

### Authentication counters

| Entity | Type | Default |
|---|---|---|
| First factor successful / failed / banned | sensor (total increasing) | ✓ |
| Second factor successful / failed | sensor (total increasing) | ✓ |
| Second factor banned | sensor (total increasing) | ✗ |
| Second factor TOTP / WebAuthn / Duo | sensor (total increasing) | ✗ |
| Passkey successful / failed | sensor (total increasing) | ✗ |

### Authorization & HTTP

| Entity | Type | Default |
|---|---|---|
| Authorizations granted / redirected to login / unauthorized / forbidden | sensor (total increasing) | ✗ |
| HTTP requests / client errors / server errors | sensor (total increasing) | ✗ |
| Server errors (1 h) | sensor | ✓ |

### Performance

| Entity | Type | Default |
|---|---|---|
| Average login duration (1 h) | sensor (ms) | ✗ |
| Average request duration (1 h) | sensor (ms) | ✗ |
| Request duration p95 (1 h) | sensor (ms) | ✗ |

### Health & diagnostics

| Entity | Type | Default |
|---|---|---|
| Reachable | binary sensor | ✓ |
| Telemetry | binary sensor (diagnostic) | ✓ |
| Readiness problem | binary sensor | ✓ (only if `/api/health/verbose` exists) |
| Started | sensor (timestamp, diagnostic) | ✓ |
| Memory usage | sensor (diagnostic) | ✓ |
| Latest version | sensor (diagnostic) | ✓ |
| Heap allocated, CPU time, open file descriptors, network received/sent, goroutines, Go version, health check latency | sensor (diagnostic) | ✗ |
| Authelia | update | ✓ (only if the installed version is set) |

## Security event

The event entity fires whenever new failures were counted since the last poll. Event types:

| Event type | Meaning |
|---|---|
| `first_factor_failed` | Failed username/password attempt |
| `second_factor_failed` | Failed TOTP, WebAuthn or Duo attempt |
| `passkey_failed` | Failed passkey attempt |
| `banned` | Attempt rejected by Authelia's regulation (ban) |

Each event carries a `count` attribute with the number of new occurrences. Authelia's metrics contain no usernames or IP addresses, so the event does not either.

### Example automation

```yaml
automation:
  - alias: "Authelia: notify on failed logins"
    triggers:
      - trigger: state
        entity_id: event.authelia_security_event
    conditions:
      - condition: template
        value_template: >
          {{ trigger.to_state.attributes.event_type in
             ['first_factor_failed', 'second_factor_failed', 'passkey_failed', 'banned'] }}
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Authelia"
          message: >
            {{ trigger.to_state.attributes.count }}×
            {{ trigger.to_state.attributes.event_type | replace('_', ' ') }}
```

## Limitations

- **Installed version**: Authelia does not expose its version through an unauthenticated endpoint. The update entity therefore requires the installed version to be entered in the options and kept up to date manually.
- **Rolling windows** are kept in memory. After a Home Assistant restart they need time to fill up again (the 24 h window needs 24 hours). Total counters are not affected.
- **Counter resets**: Authelia's counters restart at zero when Authelia restarts. Total sensors use `total_increasing`, which Home Assistant handles automatically; rolling windows and events compensate for resets.
- **No user or IP details**: bans, registered 2FA devices and per-user login history are stored in Authelia's database and are not part of the metrics.

## Removal

1. **Settings → Devices & services → Authelia → ⋮ → Delete**
2. Remove the repository in HACS (or delete `custom_components/authelia`) and restart Home Assistant
3. Optionally disable `telemetry.metrics` in Authelia again

## Troubleshooting

- **"Telemetry endpoint not reachable"**: check that `telemetry.metrics.enabled` is `true`, Authelia was restarted, and no firewall blocks the telemetry port.
- **"Provides no Authelia metrics"**: the configured port answers but is not Authelia's telemetry endpoint.
- **Diagnostics**: Settings → Devices & services → Authelia → ⋮ → Download diagnostics (the host is redacted).
- **Debug logging**:

  ```yaml
  logger:
    logs:
      custom_components.authelia: debug
  ```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt ruff
ruff check custom_components tests
pytest -q
```

Tests run against `pytest-homeassistant-custom-component` and use a real metrics output of Authelia 4.39.27 as fixture (`tests/fixtures/`).

### Releasing

1. Bump `version` in `custom_components/authelia/manifest.json`
2. Commit and push
3. Tag and create a release:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "vX.Y.Z" --generate-notes
   ```

## License

[MIT](LICENSE)
