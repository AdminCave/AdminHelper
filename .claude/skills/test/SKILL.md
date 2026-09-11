---
name: test
description: Run AdminHelper's real test suites — the quick local one, and the heavy tier on crabbox VMs (docker/GUI/multi-host) including the weekly run heavy.sh. Use for integration/e2e/heavy tests, verifying on real Linux, reading the last weekly report, or before a release.
---

# Testing AdminHelper

The fast unit/lint suites run anywhere (and in GitHub CI). The **heavy tier** — real
docker-compose stack, mTLS enrollment, Redis SSE fan-out, agent monitoring, apt/rpm repo
build, the upgrade path from the last release, and multi-host scenarios (cross-distro rpm,
3-host FRP tunnel, monitoring closed-loop, the real Tauri desktop GUI) — needs real Linux
with Docker + a display, which the sandboxed dev box lacks. crabbox leases ephemeral
Proxmox VMs, rsyncs the tree, runs, and tears down. Provider env AND token live only in the
gitignored `.claude/settings.local.json` (nothing infra-bearing in the public
`settings.json`); confirm with `crabbox doctor`.

## The five verbs

| `/test …`  | What happens |
|---|---|
| `quick`    | run it here and now: `bash scripts/dev/verify.sh all --strict` |
| `all`      | PRINT the start command for `heavy.sh all`, then stop |
| `capstone` | PRINT the start command for `heavy.sh capstone`, then stop |
| `weekly`   | PRINT the start command for `heavy.sh weekly`, then stop |
| `status`   | read the newest weekly report and quote its first line |

**`all`, `capstone` and `weekly` are never started from inside a session.** They run for
hours and burn up to eight VMs; nothing here starts without Kevin (CLAUDE.md §2). Print
exactly this and end the turn:

```
tmux new -d -s ah-weekly 'bash scripts/tests/heavy.sh weekly'
```

(`all` and `capstone` are the same line with the mode swapped, and the session name may be
anything.) Kevin starts it, closes the terminal, and reads the report afterwards.

**Name these two before ending the turn** — both cost a whole run otherwise:
`crabbox list` must be empty (a foreign box aborts the run with 74 in its first
minute, long after the terminal is closed), and `capstone`/`weekly` have never
run against the enforced gateway `--capstone` now sets — the desktop stage
enrolls a device identity first (T7a), but only a real run proves it.

## `status` — what the last weekly run said

Newest report first; its FIRST line is the verdict and is quoted verbatim, never
paraphrased. Glob on `report.md`, not on the directory: heavy.sh creates the run
directory before it starts and writes the report at the end, so while a run is
going — and after a hard abort — the newest DIRECTORY holds no verdict, and
taking it would hide the last real one:

```
ls -1d .crabbox-out/weekly/*/report.md | sort -r        # newest first
head -1 <the first one whose first line is not empty>   # PASS | FAIL | UNVERIFIED (<reason>)
```

The first report with a VERDICT wins, not the newest file: an aborted run leaves an
empty `report.md`, and taking it would hide the last real one. `session-status.sh`
does exactly this for line 4 of `AH-STATUS`.

The same line is on the `AH-STATUS` block's fourth line at session start.

## The weekly run — `scripts/tests/heavy.sh`

```
bash scripts/tests/heavy.sh all|capstone|weekly [--base <sha>] [--no-second-vm] [--notify]
```

- `all` = warm box → `run.sh all --strict`; `capstone` = `crabbox_multibox.sh --capstone --strict`;
  `weekly` = both, serially. The capstone is skipped only when the `all` layer ended
  UNVERIFIED (seven VMs must not burn into a broken environment) — a plain FAIL does not
  stop it.
- It is a **wrapper**: every VM operation goes through the crabbox_*.sh scripts, so stage 2
  can swap the implementation underneath as long as the summary lines stay the same.
- Pre-flight: `crabbox doctor`, and `crabbox list` must show no box outside this lane's pond
  and `warm.env` — a foreign box means the capacity is not there, and the run stops before
  burning any.
- Results: `.crabbox-out/weekly/<jjjj-mm-tt-hhmm>/report.md` plus the pulled artifacts. The
  report's first line is the verdict, then the wrappers' summary lines **verbatim**, then the
  step table, `Kevin sichtet`, `Notizen`, the audit.yml verdict and the VM list. Facts, never
  a judgement.
- History: `tasks/private/history.csv` (one row per step per run plus a layer row), committed
  in the private repo — never pushed.
- `--notify` posts the verdict line + report path to `AH_NOTIFY_URL` (from `.devenv.sh`).
  Default off.
- Exit: **0 = PASS · 1 = FAIL · 74 = UNVERIFIED** (infrastructure — the run could not happen,
  so nothing about the code was learned) · `2` = usage.

### How a red step is classified

| Verdict | How it is reached | What it means |
|---|---|---|
| `infra` | the box could not be had, or the step could not RUN: no warm box, warm pond not ready, a failed server lease, `strict-failed: no step ran`, `strict-failed: … (SKIP)`, wrapper exit 74 | never a regression, report reads UNVERIFIED |
| `flaky` | green within 3 retries on the same box (`AH_NO_SYNC=1`) | quarantined in `tasks/private/seen.md`, does not fail the run |
| `unbestaetigt` | 3× red, but green on a fresh second VM — or no PASS commit to compare against, or `--no-second-vm` | Kevin looks; never a REG |
| `extern` | red on the second VM AND on the last PASS commit | environment/dependency, not the change |
| `reg` | red on the second VM, green on the last PASS commit | roadmap row (class REG, `neu`) + `tasks/reg-<datum>-<schritt>.md` |
| `fail` | red all three times, but failing DIFFERENTLY each time | reproducibly broken without the stable signature a regression claim needs — no second VM |

The second VM is a **worktree** `.crabbox-worktrees/w2` with its own lane (`AH_LANE=w2`,
pond `ah-warm-w2`); heavy.sh reaps that pond and removes the worktree itself. Kevin's own
warm box (`ah-warm`) is never touched. `--no-second-vm` skips the check and leaves the
candidate unconfirmed; `--base <sha>` overrides the comparison commit.

### Rhythm

Friday evening, one `weekly`. The first runs are noisy (the desktop chain flakes) — that is
what the quarantine is for; `R reruns` in the run.sh summary stays 0 on purpose so the
quarantine calibrates against un-retried suites.

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
3. **Reap** at branch-switch / EOD: `bash scripts/tests/crabbox_reap.sh` (stops THIS lane's
   pond — `ah-warm`, or `ah-warm-<lane>` in a worktree-lane (see cbx_lane in crabbox_lib.sh) —
   + clears warm.env; other lanes' boxes stay). Warm boxes also self-reap via
   `-ttl 8h -idle-timeout 4h`.

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
`run.sh [lint|unit|quick|integration|e2e|all] [--strict] [--only <keys…>] [--step <name>]`
(the `all` layer includes `upgrade_path_test.sh` — last published release → this checkout —
and the eight `desktop_e2e_*.sh` GUI suites, `desktop_e2e_misc.sh` among them). **Caveat
(T15a):** `crabbox_iter.sh` does not forward `AH_REQUIRED`, so on the box the built-in
default applies and NO heavy step is required — a self-SKIP of any of them stays green.
prints `N passed, M failed, K skipped, J test-skips, R reruns` and exits non-zero on fail;
under `--strict` a skipped required step is a failure, and so is a run in which nothing ran.
integration/e2e/all need `AH_ALLOW_REAL=1`. Bootstrap profiles:
`server`/`agent` skip Rust/Tauri (~18 min faster); `full` (desktop + single-box) keeps it.

## Multi-host scenarios — `crabbox_multibox.sh` (composable flags)

`bash scripts/tests/crabbox_multibox.sh [flags]` leases a server-box + role boxes on the same
provider bridge,
prints one `N ok, M failed, K skipped` summary, tears leases down on exit (`--keep` to inspect):
- `--strict`    a guard that could not run fails the run instead of passing as a note.
                Since stage 3 the six conditional guards report through `skipped()` (debian:9,
                agent-repo/CA-flip without `REPO_FP`, desktop lease, moncheck lease,
                `--enforce`, monitoring hop), so `0 failed, 0 skipped` means "every
                REQUESTED check ran". A failed lease (agent, tunnel, visitor, rpm, moncheck)
                still drops its follow-up checks without a SKIP — there the accompanying
                FAIL is the evidence.
- `--agents N`  N agent-boxes: real `.deb` install + provision over the hop (cross-host mTLS).
- `--rpm`       + a cross-distro rpm agent in a `rockylinux:8` container (crabbox_agentbox_rpm.sh).
- `--tunnel`    + frps + an agent frpc STCP server + a visitor: full 3-host FRP tunnel data path.
- `--desktop`   + the real Tauri GUI headless vs the remote server (login/CRUD/monitoring).
                `AH_DESKTOP_ID=<slug>` reuses a warm desktop box (skips ~30 min re-bootstrap+build).
- `--moncheck`  + a mailhog sink box: pull ping-checks + a closed-loop email alert over the hop.
- `--enforce`   `MTLS_ENFORCE=true`: cert-based admin seed (enroll on :8444) + assert certless :443 → 400.
- `--capstone`  = `--agents 1 --rpm --tunnel --desktop --moncheck --enforce` (everything,
                one run — 7 boxes). `--enforce` is included since stage 3: without it the
                MTLS_ENFORCE guard never ran in a release capstone. `heavy.sh capstone`
                runs exactly this, with `--strict`. **Partial runs — anything short of the
                capstone flag set — run WITHOUT `--strict`:** a missing `--enforce` reports
                SKIP, and a SKIP fails a strict run, so `--agents 1 --desktop --strict` is
                red before it tests anything. **T7a:** because the enforced gateway demands
                a client cert on :443, the desktop stage enrolls a device identity over the
                certless :8444 plane before EACH spec (one one-time token per spec, minted
                just before the stage). Implemented, but only a real capstone proves it.
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
- **Monitoring SSRF guard blocks private IPs** for HTTP-checks + alert webhooks only; `ping`/`tcp`
  deliberately allow private targets (v0.44.0 — monitoring internal hosts is the point). The closed
  loop therefore uses ping (ICMP) + SMTP (`smtp_host` in the alert `channel_config`). The sink is
  **mailpit with STARTTLS** and an IP-SAN cert whose PEM is injected into the monitoring container's
  trust store: the alerter mandates STARTTLS on every non-465 port and verifies cert+hostname (3.24),
  so a plaintext catcher (mailhog) can never receive an alert. The monitoring
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
  have repeatedly leaked provisioned (`keep=true`) boxes. Never leave a VM running. `heavy.sh`
  checks the same list BEFORE it starts (a foreign box aborts with 74) and prints it into the
  report afterwards — a leaked VM is a finding, not a detail.
- **Never claim green unless it actually passed** — report the `run.sh` / multibox summary line
  verbatim; SKIP = "not verified", not "ok". For a weekly run, quote the report's first line;
  `UNVERIFIED` is never reported as a pass and never as a regression.
- Pre-approved (auto): `warmup / run / status / list / connect / ssh / doctor / stop / cleanup /
  artifacts pull`. Provision/cost → ask first: `prewarm / job / checkpoint create / image / bake`.
