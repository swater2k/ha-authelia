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
- **Optional database agent**: active bans, login history with user and IP, 2FA devices, users without 2FA, security configuration, WebAuthn clone warnings and automatic version detection
- **Repair issues** for users without second factor, legacy password hashes, a non-`deny` default policy, cloned WebAuthn credentials and a rejected agent token
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
| Polling interval | `30 s` | Interval for metrics, health check and agent (10–300 s) |
| Agent URL / Agent token | empty | Connects the optional [database agent](#database-agent-optional) |
| Warn about users without 2FA | on | Creates a repair issue for active users without second factor (agent only) |
| Installed Authelia version | empty | Only needed without agent, e.g. `4.39.27`. Enables the update entity |

## Database agent (optional)

Authelia's metrics only contain counters. Details such as *who* failed to log in *from where*, active bans, registered 2FA devices or users without a second factor live in Authelia's storage database, user database and configuration. The **Authelia HA Agent** is a small companion service that runs next to Authelia and exposes this data read-only to Home Assistant.

- Single Python file, runs as a systemd service (Python ≥ 3.11; `python3-yaml` for users and configuration, installed automatically on Debian/Ubuntu)
- Opens the SQLite database strictly read-only (`mode=ro`, `query_only`)
- Reads the file user database (`authentication_backend.file`) and an allow-list of non-secret configuration values
- Protected by a bearer token; optional HTTPS
- Never exposes TOTP secrets, WebAuthn keys, password hashes (only the algorithm), e-mail addresses, request URIs, OAuth2/OIDC sessions or any secret from the configuration
- Detects the installed Authelia version via `authelia --version`, so the update entity works without manual input
- Supports the **SQLite** storage backend (`storage.local`) and the **file** authentication backend; with LDAP, users are not available

### Install the agent

Run inside the Authelia host or LXC as root:

```bash
curl -fsSL https://raw.githubusercontent.com/swater2k/ha-authelia/main/agent/install.sh | bash
```

The installer places the agent in `/opt/authelia-ha-agent`, generates a random token in `/etc/authelia-ha-agent/agent.env`, enables the `authelia-ha-agent` service on port `9960` and prints URL and token.

Options: `--port <port>`, `--db <path>`, `--config <path>`, `--rotate-token`. Running the installer again updates the agent and keeps the token.

```bash
systemctl status authelia-ha-agent
journalctl -u authelia-ha-agent -n 50
curl -s http://127.0.0.1:9960/health
```

### Connect it to Home Assistant

**Settings → Devices & services → Authelia → Configure** and enter **Agent URL** (e.g. `http://192.168.1.10:9960`) and **Agent token**. The connection is validated before saving.

> [!IMPORTANT]
> The agent exposes usernames and IP addresses. Only make port `9960` reachable from Home Assistant (for example with a firewall rule) and never publish it through a reverse proxy or tunnel. Use `AGENT_TLS_CERT` / `AGENT_TLS_KEY` in `agent.env` if you want HTTPS inside your LAN.

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

### Database agent

Only created when the agent is configured.

| Entity | Type | Default |
|---|---|---|
| Active user bans / Active IP bans (list as attributes) | sensor | ✓ |
| Ban active | binary sensor | ✓ |
| Last successful login / Last failed login (user, IP, type as attributes) | sensor (timestamp) | ✓ |
| IPs with failed logins (24 h) | sensor | ✓ |
| Users with failed logins (24 h) | sensor | ✗ |
| Users with TOTP / WebAuthn credentials (details as attributes) | sensor | ✓ |
| Passkeys | sensor | ✗ |
| WebAuthn clone warning | binary sensor (problem) | ✓ |
| Database agent | binary sensor (diagnostic) | ✓ |
| Authelia version | sensor (diagnostic) | ✓ |
| Database schema version | sensor (diagnostic) | ✗ |

#### Users (file backend)

| Entity | Type | Default |
|---|---|---|
| Users (list with groups, 2FA status and hash algorithm as attributes) | sensor | ✓ |
| Users without 2FA (active users only) | sensor | ✓ |
| Disabled users | sensor | ✓ |
| Users with legacy password hash | sensor | ✓ |
| Users without e-mail | sensor | ✗ |
| Groups (members as attributes) | sensor (diagnostic) | ✓ |

#### Security configuration

| Entity | Type | Default |
|---|---|---|
| Default policy (`deny`, `one_factor`, `two_factor`, `bypass`) | sensor (diagnostic) | ✓ |
| Access control rules (count per policy as attributes) | sensor (diagnostic) | ✓ |
| Bypass rules | sensor (diagnostic) | ✓ |
| Regulation max retries (find time, ban time, modes as attributes) | sensor (diagnostic) | ✓ |
| Session expiration (inactivity, remember me as attributes) | sensor (diagnostic) | ✓ |
| Password policy (`zxcvbn`, `standard`, `disabled`) | sensor (diagnostic) | ✓ |
| Notifier (storage, log level, telemetry as attributes) | sensor (diagnostic) | ✗ |

With the agent, *Failed logins (24 h)*, *Successful logins (24 h)* and *Banned attempts (24 h)* are calculated from the database and survive Home Assistant restarts. The attribute `source` shows whether a value comes from `database` or `metrics`.

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
| Authelia | update | ✓ (with agent, or if the installed version is set) |

## Security event

The event entity fires for new authentication activity since the last poll. Its data source depends on whether the database agent is configured.

| Event type | Meaning | Without agent | With agent |
|---|---|---|---|
| `first_factor_failed` | Failed username/password attempt | ✓ | ✓ |
| `second_factor_failed` | Failed TOTP, WebAuthn or Duo attempt | ✓ | ✓ |
| `passkey_failed` | Failed passkey attempt | ✓ | ✓ |
| `banned` | Attempt rejected because of an active ban | ✓ | ✓ |
| `login_successful` | Successful authentication step (1FA, TOTP, WebAuthn, …) | – | ✓ |
| `ban_created` | New user or IP ban | – | ✓ |

**Without agent**, each event carries `count` (new occurrences since the last poll).
**With agent**, one event is fired per log entry with `username`, `remote_ip`, `auth_type`, `time` and `method`; `ban_created` carries `kind` (`user`/`ip`), `subject`, `expires`, `permanent`, `source` and `reason`.

The entity ID depends on your Home Assistant language, e.g. `event.authelia_security_event` (English) or `event.authelia_sicherheitsereignis` (German).

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
             ['first_factor_failed', 'second_factor_failed', 'passkey_failed', 'banned', 'ban_created'] }}
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Authelia"
          message: >
            {% set a = trigger.to_state.attributes %}
            {{ a.event_type | replace('_', ' ') | capitalize }}
            {%- if a.username is defined %}: {{ a.username }} from {{ a.remote_ip }}
            {%- elif a.subject is defined %}: {{ a.kind }} {{ a.subject }}
            {%- else %} ({{ a.count }}×){% endif %}
```

## Repair issues

With the database agent, the integration reports security findings under **Settings → Repairs**. Issues disappear automatically once the cause is fixed.

| Issue | Severity |
|---|---|
| Active users without second factor (can be disabled in the options) | warning |
| Users with a password hash algorithm that is no longer recommended | warning |
| `access_control.default_policy` is not `deny` | warning |
| WebAuthn credential flagged as possibly cloned | error |
| Agent rejects the configured token | error |

## Limitations

- **Installed version**: Authelia does not expose its version through an unauthenticated endpoint. Without the agent, the installed version has to be entered in the options and kept up to date manually.
- **Rolling windows** from metrics are kept in memory and need time to fill up after a Home Assistant restart. With the agent, the 24 h values come from the database instead.
- **Agent backends**: the agent supports the SQLite storage backend and the file authentication backend. With LDAP, user entities stay unavailable.
- **Users without 2FA** does not evaluate access control rules: a user who only needs `one_factor` resources is reported as well. Disable the warning in the options if that is intended.
- **Counter resets**: Authelia's counters restart at zero when Authelia restarts. Total sensors use `total_increasing`, which Home Assistant handles automatically; rolling windows and events compensate for resets.
- **No user or IP details without agent**: bans, 2FA devices and login history are only available through the database agent.

## Removal

1. **Settings → Devices & services → Authelia → ⋮ → Delete**
2. Remove the repository in HACS (or delete `custom_components/authelia`) and restart Home Assistant
3. Optionally disable `telemetry.metrics` in Authelia again
4. If installed, remove the agent:

   ```bash
   systemctl disable --now authelia-ha-agent
   rm -rf /opt/authelia-ha-agent /etc/authelia-ha-agent /etc/systemd/system/authelia-ha-agent.service
   systemctl daemon-reload
   ```

## Troubleshooting

- **"Telemetry endpoint not reachable"**: check that `telemetry.metrics.enabled` is `true`, Authelia was restarted, and no firewall blocks the telemetry port.
- **"Provides no Authelia metrics"**: the configured port answers but is not Authelia's telemetry endpoint.
- **"Token rejected by the agent"**: compare with `grep AGENT_TOKEN /etc/authelia-ha-agent/agent.env`.
- **Agent reports a database error**: check `journalctl -u authelia-ha-agent` and the `AUTHELIA_DB` path.
- **User and configuration entities are unknown**: `python3-yaml` is missing on the Authelia host (`apt install python3-yaml`) or `AUTHELIA_CONFIG` points to the wrong file. The diagnostics download shows the reason under `agent.users.error`.
- **Diagnostics**: Settings → Devices & services → Authelia → ⋮ → Download diagnostics (the host is redacted).
- **Debug logging**:

  ```yaml
  logger:
    logs:
      custom_components.authelia: debug
  ```

## License

[MIT](LICENSE)
