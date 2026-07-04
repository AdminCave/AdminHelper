---
name: test
description: Run AdminHelper's real test suites on crabbox (docker/GUI/multi-host tests the dev box can't run). Use for integration/e2e/heavy tests, verifying on real Linux, or before a release.
---

# Testing AdminHelper on crabbox

The fast unit/lint suites run anywhere (and in GitHub CI). The **heavy tier** — real
docker-compose stack, mTLS enrollment, Redis SSE fan-out, agent monitoring, apt/rpm repo
build, and multi-host scenarios (cross-distro rpm, 3-host FRP tunnel, monitoring
closed-loop, the real Tauri desktop GUI) — needs real Linux with Docker + a display, which
the sandboxed dev box lacks. crabbox leases ephemeral Proxmox VMs, rsyncs the tree, runs,
and tears down. Provider env: `.claude/settings.json` (+ secret in the gitignored
`.claude/settings.local.json`); confirm with `crabbox doctor`.

## Fast loop — warm once → iterate → reap (the default; do NOT stop after each run)

A hydrated box is expensive to build (~18 min bootstrap + ~20 min Tauri build) but cheap to
keep. Reuse it: `.crabbox.yaml` excludes `target/`/`node_modules/`/`.venv/` from the
`delete`-sync, so on a REUSED box those build trees survive → cargo/npm rebuild
incrementally (minutes, not ~40). Validated: iter #1 ~12 min (cold) → #2 ~3.5 min (3.4×).

1. **Warm once** (idempotent — reuses `.crabbox/warm.env` if the slug is still ready):
   `bash scripts/tests/crabbox_warm.sh <desktop|server|pond>`
   - `desktop` = full box (docker+go+node+rust+tauri) — the general workhorse for `run.sh`.
   - `server`  = server box with the stack UP + admin/monitor creds stashed.
   - `pond`    = server (stack up) + desktop, for the distributed desktop loop.
2. **Iterate** after each change:
   - `bash scripts/tests/crabbox_iter.sh <lint|unit|quick|integration|e2e|all>` — run.sh on the warm box.
   - `bash scripts/tests/crabbox_iter.sh --desktop [spec…]` — GUI on the warm desktop box vs the warm server.
   Under the hood: `crabbox run --id <slug> -no-hydrate -keep-on-failure -capture-stdout/-stderr
   -artifact-glob '.crabbox-out/**' -- 'AH_ALLOW_REAL=1 AH_CAPTURE=1 bash scripts/tests/run.sh <layer>'`.
   `AH_NO_SYNC=1` re-runs the already-synced tree (flaky retry, no rsync).
3. **Reap** at branch-switch / EOD: `bash scripts/tests/crabbox_reap.sh` (stops the `ah-warm`
   pond + clears warm.env). Warm boxes also self-reap via `-ttl 8h -idle-timeout 4h`.

## Auto-debug on failure (no re-run needed)

`crabbox_iter.sh` (and `run.sh` with `AH_CAPTURE=1`) leave, on ANY failure:
- `.crabbox/out/last.err.log` — full untruncated stderr (read first).
- `.crabbox-out/screenshots/*.png` + `.html` — the GUI at failure (wdio `afterTest` hook).
- `.crabbox-out/logs/*` — docker container logs, agent journal, tool versions (crabbox_debug.sh).
- newest `.crabbox/captures/*.tar.gz` — crabbox's own failure bundle.
- the box stays up (`-keep-on-failure`): `crabbox ssh --id <slug>` to reproduce interactively.

## Manual primitives (what the loop wraps)

`crabbox warmup -slug <s> -pond <p> -proxmox-bridge <bridge> -ttl 8h -idle-timeout 4h` →
`crabbox run --id <s> -- 'AH_BOOTSTRAP_PROFILE=<full|server|agent> bash scripts/tests/crabbox_bootstrap.sh'` →
`crabbox run --id <s> -- 'AH_ALLOW_REAL=1 bash scripts/tests/run.sh <layer>'` → `crabbox stop --id <s>`.
`run.sh [lint|unit|quick|integration|e2e|all]` prints `N passed, M failed, K skipped`, exits
non-zero on fail; integration/e2e/all need `AH_ALLOW_REAL=1`. Bootstrap profiles:
`server`/`agent` skip Rust/Tauri (~18 min faster); `full` (desktop + single-box) keeps it.

## Multi-host scenarios — `crabbox_multibox.sh` (composable flags)

`bash scripts/tests/crabbox_multibox.sh [flags]` leases a server-box + role boxes on the same
provider bridge,
prints one `N ok, M failed` summary, tears leases down on exit (`--keep` to inspect):
- `--agents N`  N agent-boxes: real `.deb` install + provision over the hop (cross-host mTLS).
- `--rpm`       + a cross-distro rpm agent in a `rockylinux:8` container (crabbox_agentbox_rpm.sh).
- `--tunnel`    + frps + an agent frpc STCP server + a visitor: full 3-host FRP tunnel data path.
- `--desktop`   + the real Tauri GUI headless vs the remote server (login/CRUD/monitoring).
                `AH_DESKTOP_ID=<slug>` reuses a warm desktop box (skips ~30 min re-bootstrap+build).
- `--moncheck`  + a mailhog sink box: pull ping-checks + a closed-loop email alert over the hop.
- `--enforce`   `MTLS_ENFORCE=true`: cert-based admin seed (enroll on :8444) + assert certless :443 → 400.
- `--capstone`  = `--agents 1 --rpm --tunnel --desktop --moncheck` (everything, one run — 7 boxes).
Roles: `crabbox_serverbox` / `agentbox` / `agentbox_rpm` / `tunnelbox` / `visitorbox` /
`desktopbox` / `moncheckbox`. serverbox modes (tunnel/moncheck/enforce) are independent + compose.

## Bake a fat template (ask-first — provisions)

`bash scripts/tests/crabbox_bake.sh <desktop|server>` hydrates a box + guides converting it to
a Proxmox template so cold starts skip the ~18 min bootstrap. Provisions → run deliberately.

## Pitfalls (learned the hard way — keep them true)

- **Proxmox template = DHCP + cloud-init + a cloud-init user** (template ID(s) + bridge come
  from the provider env in `.claude/settings.local.json`; keep an ubuntu one, add others as
  needed). Static IP → clones collide; no cloud-init → warmup hangs. `crabbox doctor` doesn't
  prove this. RHEL-family containers need a v8 base (v9 wants x86-64-v2 the default vCPU lacks).
- **Lease SEQUENTIALLY into a `-pond`** — concurrent `warmup &` on this proxmox provider
  (ssh-lease, coordinator:never) hangs (once ran ~7 h). Every crabbox call is `timeout`-bounded.
  Boxes reach each other over the shared bridge; resolve peer IPs via `crabbox ssh --id`, not the warmup line.
- **Bring up ONLY `gateway server ca-issuer monitoring`** — `scheduler` pulls the not-yet-
  published `ghcr.io/admincave/*` tag → `unauthorized`; first-party images build from checkout
  as `adminhelper-test/*`. frps is public (snowdreamtech) and is brought up by `--tunnel`.
- **`DOMAIN=<server-IP>` before the first `up`** (ca-issuer mints the gateway/frps leaf IP-SAN
  once; changing later needs `down -v`).
- **Desktop GUI blank screen = `LANG=C`** → the webview feeds "C" to `Intl.NumberFormat` →
  `RangeError` → the Svelte app never mounts (empty `#app`). bootstrap `locale-gen en_US.UTF-8`;
  desktopbox exports `LANG=en_US.UTF-8`. (Diagnose the mount error via a `window.__errs` catcher —
  WebKitWebDriver exposes no console/`getLogs`.)
- **rpm cross-distro:** RHEL 9 needs x86-64-v2 (Proxmox kvm64 lacks it → use `rockylinux:8`);
  RPM `Version` forbids `-` (use `0.0.0`, not `0.0.0-test`); the agent must be **static**
  (`CGO_ENABLED=0`, in the Makefile) to run on RHEL 8's older glibc.
- **Monitoring SSRF guard blocks private IPs** for HTTP-checks + webhooks → the closed loop uses
  ping (ICMP) + SMTP (`smtp_host` in the alert `channel_config`), both un-guarded. The monitoring
  internal API (`/checks`, `/alerts`) is reachable only inside the compose net (`docker compose
  exec monitoring`, auth `X-Internal-Key: $MONITOR_API_KEY`); trigger a check with `POST /checks/{id}/run`.
- **enforce: agents bootstrap via the certless :8444 plane** (`/provision/activate` + `/enroll`,
  token-gated); the cert-gated data plane (:443) stays hard. Agent `.deb`/`.rpm` land at the repo
  ROOT (not `dist/`); `build-*.sh` need `frpc` staged at root + `apps/agent/bin/adminhelper-agent`.
- **Release: bump `Cargo.lock` with the version** (else `cargo check/build --locked` in CI goes red).

## Rules

- **Warm boxes persist across iterations — do NOT `crabbox stop` after each run.** They self-reap
  (ttl/idle); sweep with `crabbox_reap.sh`. `crabbox stop` after one run is only for a genuine
  one-off. A box that fails sync sanity is not a debug target — stop it + re-warm.
- **After ANY workflow / batch of agents, run `crabbox list` and stop strays** — read-only agents
  have repeatedly leaked provisioned (`keep=true`) boxes. Never leave a VM running.
- **Never claim green unless it actually passed** — report the `run.sh` / multibox summary line
  verbatim; SKIP = "not verified", not "ok".
- Pre-approved (auto): `warmup / run / status / list / connect / ssh / doctor / stop / cleanup /
  artifacts pull`. Provision/cost → ask first: `prewarm / job / checkpoint create / image / bake`.
