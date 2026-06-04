# Security Policy

## Supported versions

AdminHelper is under active development. Security fixes are applied to the
latest released `0.x` version. Please always run the most recent release.

## Reporting a vulnerability

Please report security vulnerabilities **privately** — do **not** open a public
issue for security problems.

- Preferred: GitHub's [private vulnerability reporting](https://github.com/ks98/AdminHelper/security/advisories/new)
  (repository → **Security** → **Report a vulnerability**), or
- email **kevin@ks98.de** with a description and, if possible, a proof of concept.

You can expect an initial response within a few days. Please allow a reasonable
amount of time for a fix before any public disclosure.

## Scope

AdminHelper is remote-management software (SSH/RDP/Web access, FRP tunnels with
their own PKI, server inventory, monitoring). Areas of particular interest:

- authentication / authorization (JWT with refresh-token rotation, API keys,
  one-time provision tokens),
- the FRP PKI and tunnel configuration (key handling, `frpc.toml` exposure),
- the server-bound API-key scoping on the `/api/frp/provision/*` endpoints,
- hook execution — hooks are **trusted admin code with database access**; this
  is by design and documented, not a sandbox boundary.

Out of scope: issues that require an already-compromised admin account, or that
only affect deliberately self-hosted/private deployment misconfigurations.
