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

## Security model — the boundaries that carry the weight

These are documented honestly so they are not silently relied upon or "fixed"
the wrong way.

### FRP tunnel authorization rests on per-tunnel `secretKey`, NOT on `allowUsers`

In the FRP STCP model, `user` / `serverUser` / `allowUsers` are **self-asserted
strings**, accepted after a token-only check — FRP does **not** bind them to the
TLS client-certificate CN (verified against frp 0.69.1), and a single global
`auth.token` ships in **every** `frpc.toml` and visitor bundle. The system is
safe **only because the server scopes the per-tunnel `secretKey` per user**
(`frp/generate_router.py` filters visitor tunnels by `current_user.servers`).
That one control is load-bearing. Therefore, treated as **accepted risk**:

- `allowUsers` is **defense-in-depth, not an authorization boundary**.
- The **global `auth.token` is a single point of failure** — one leaked bundle
  exposes it for the whole mesh. Mitigation: **rotate `auth.token` + per-tunnel
  `secretKey` on offboarding**; for higher assurance move to per-agent tokens or
  cert-CN binding.

### Single-worker availability profile

The server runs one uvicorn worker / one event loop, so any event-loop stall is
a full outage. **Blocking work in an `async def` MUST go through
`run_in_threadpool` / `asyncio.to_thread`** (the webhook bug that violated this
is fixed). Horizontal scale needs `--workers N` + Redis (the rate-limit backend
already supports it).

## Audit residuals

The deep audit's exploitable findings (2 high, several medium) are fixed and
tested (`CHANGELOG.md`). The following are **deliberately not changed in code** —
either deferred because a safe fix needs dedicated, manually-tested work, or
accepted because the current behaviour is the correct trade-off.

### Deferred (needs dedicated, manually-tested work)

- **Desktop TLS — replace the `allow_self_signed_certs` blanket bypass with TOFU
  pinning.** `danger_accept_invalid_certs(true)` disables chain + hostname
  checks. Proper pinning in `reqwest` needs a **custom rustls `ServerCertVerifier`**
  and a live server + MITM to verify; shipping it under-verified would risk a
  MITM-open or can't-connect bug. Plan: mirror the Go agent's TOFU (capture +
  pin the leaf on first connect, `add_root_certificate`, full validation, reject
  changes). Bundle the related `api_proxy` token-destination pin, `connect-src`
  CSP, `ansible_*` path confinement and `check_server_cert` scheme check with it.
- **Web — move the refresh token from `localStorage` to an `HttpOnly` cookie.**
  Half-doing it (cookie without CSRF protection) introduces a CSRF hole; needs
  `HttpOnly; Secure; SameSite` + CSRF tokens + a CORS review, tested end to end.
- **Python deps — hashed lockfile.** No `uv`/`pip-tools` in this environment; a
  half-pinned file is worse than none. Plan: `pip-compile --generate-hashes`
  (or `uv pip compile`) → install with `pip install --require-hashes`.

### Accepted (deliberate, with rationale)

- **frps container capability hardening** — attempted and reverted: `cap_drop`
  breaks the image's `su-exec` privilege drop and its read of the intentionally
  `0600` root-owned `frps.toml` on the `:ro` volume (verified locally — the
  container crash-loops). Needs a coordinated volume-permission change without
  weakening the `0600` protection of the token + dashboard password.
- **List endpoints without pagination** — admin-only, small tables; pagination
  would be a breaking API change for existing clients.
- **Token-validity watermark sub-second precision** — intentional (see the
  comment in `core/auth.py`); required for same-second refresh-reuse containment.
- **Agent pinned-cert expiry breaks the loop** — fail-closed is the safe posture;
  auto-re-pinning would weaken the TOFU guarantee.
- **Bootstrap double-admin race** — guarded by `count()>0` + the username unique
  constraint and needs a sub-second race with the operator-only one-time token.
- **`style-src 'unsafe-inline'`** — required by Svelte inline styles; `script-src`
  stays strict `'self'`.
- **Base-image / GitHub-Action tag pinning, SMART device-id sanitization,
  `MONITOR_API_KEY` divergence** — defense-in-depth / marginal; Dependabot keeps
  Actions current.
