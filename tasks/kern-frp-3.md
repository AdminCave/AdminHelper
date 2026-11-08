# frp 0.69.1 -> 0.72.0 — Task-Ledger
Status: erledigt · Branch: feature/kern-frp-3 · Review: am Ende
Spec: docs/features/kern-frp-3.md (Roadmap R-1034)
Heavy: scenario --tunnel — frps-Image und frpc wechseln die Version; der echte 3-Host-FRP-Datenpfad beweist es (die Desktop-Tunnel-Suiten mit dem frpc-Image im Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — frp-Pins auf 0.72.0 (R-1034)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, scripts/vm/bootstrap_linux.sh, apps/frps/Dockerfile, apps/server/tests/test_release_images.py, scripts/tests/desktop_e2e_workspaces.sh, scripts/tests/desktop_e2e_connect_tunnel.sh, changelog.d/kern-frp-3.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2003c9cc8 2026-11-08T08:15:42+01:00
Review: am Ende (Branch-Review)
Änderung: `FRP_VERSION` 0.72.0 und beide SHA256 (Spec) in `ci.yml`/`release.yml`, Version und Linux-SHA in `bootstrap_linux.sh`; `apps/frps/Dockerfile` auf `snowdreamtech/frps:0.72.0-alpine@sha256:bd1b1475…`, `FRPC_IMAGE` beider Desktop-Suiten auf `snowdreamtech/frpc:0.72.0-alpine`. `test_release_images.py`: `_FRPS_BASE` nimmt ein optionales `-alpine`, der Gegentest ersetzt die Version im Tag statt `:<v>@`. `changelog.d/kern-frp-3.md` (`### Changed`, umlautfrei). Acht Dateien, weil die Pins nur zusammen konsistent sind (`frp-consistency`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py tests/test_compose_frps.py
Doku: changelog.d/kern-frp-3.md

### T2 — frp-Quellen-Zitate gegen v0.72.0 nachgeprueft (R-1034)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/proxy_status.py, apps/frps/frps-supervisor.sh, apps/server/tests/test_frp_input_hardening.py, apps/server/tests/test_frp_status.py, scripts/tests/box_tunnelbox.sh, scripts/tests/multibox.sh, SECURITY.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @262a7b954 2026-11-08T08:23:52+01:00
Review: am Ende (Branch-Review)
Änderung: Jede Stelle, die frp v0.69.1 als Beleg nennt, nennt v0.72.0, nachdem das zitierte Verhalten dort gleich ist (Spec, „Zitierte Stellen gleich“); `clientVersion` der Fixtures in `test_frp_status.py` auf 0.72.0. Nur Kommentare und Testdaten, kein Verhalten; neun Dateien, weil es dieselbe Pruefung ist.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_status.py tests/test_frp_input_hardening.py tests/test_frps_supervisor.py
Doku: SECURITY.md
Abhängt von: T1

## Entscheidungen
- 2026-11-08 T1: `FRPC_IMAGE` der Desktop-Suiten ohne Digest wie bisher — das neue Image startet frpc im Hintergrund und bleibt laufen, wenn frpc endet (Probe: 0.69.1 exit=1, 0.72.0-alpine running); beide Suiten erkennen einen Fehler an der frps-Registrierung und zeigen dann die frpc-Logs, nicht am Container-Exit
