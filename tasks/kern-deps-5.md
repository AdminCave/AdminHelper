<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-5 — Task-Ledger
Status: aktiv · Branch: feature/kern-deps-5 · Review: pro Task
Spec: docs/features/kern-deps-5.md (Roadmap R-1552, R-1553, R-1555, R-1584, R-1585, R-1586, R-1587)
Heavy: linux-full — eigene Images, Entrypoints (`docker-compose.yml`) und `apps/agent`; kein PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich zu `reviewer` bei T5–T7 (Images, Entrypoints) und wenn `review.sh risk` es verlangt.
Reihenfolge: T4 nach T3 (`test_frps_policy_image.py` verlangt, dass die frps-Go-Stufe nicht älter ist als die
Toolchain des Agents); T6 und T7 nach T5; T10 zuletzt. Sonst unabhängig.

## Tasks

### T1 — R-1552, R-1553: Desktop-Crates semver-kompatibel nachziehen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @fda40824b 2026-11-18T13:37:06+01:00
Review: approve (.ah-out/review/kern-deps-5/T1.verdict.json)
Änderung: `cargo update` im semver-Rahmen von `Cargo.toml` (libz-sys 1.1.31 → ≥ 1.1.33, tauri 2.12.6 u. a.);
keine Änderung an `Cargo.toml`. Build, Clippy und Tests grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T10

### T2 — R-1586: cargo-audit-Warnungen beheben oder begründen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/.cargo/audit.toml, apps/desktop/src-tauri/Cargo.lock
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @87a622753 2026-11-18T13:51:00+01:00
Review: approve (.ah-out/review/kern-deps-5/T2.verdict.json)
Änderung: nach T1 `cargo audit` lesen; was ein kompatibles Update behebt, beheben; jede verbleibende Warnung mit
Kommentar (Crate, Grund, über welche Abhängigkeit) in `audit.toml`. Die `ignore`-Liste bleibt unverändert
(`license_gate.rs`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (nur Begründungen in audit.toml)
Abhängt von: T1

### T3 — R-1552: Go-Stufe des frps-Images auf 1.27.4  [x]
Komponente: server · Dateien: apps/frps/Dockerfile
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @ee858ad48 2026-11-18T13:30:02+01:00
Review: approve (.ah-out/review/kern-deps-5/T3.verdict.json)
Änderung: `golang:1.27.3-alpine@sha256:…` → `golang:1.27.4-alpine` mit dem Digest aus R-1552 (vor dem Schreiben
mit `docker buildx imagetools inspect` gegenprüfen).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_policy_image.py tests/test_release_images.py
Doku: keine (Pin)

### T4 — R-1552, R-1553: Agent-Toolchain und Go-Module  [x]
Komponente: agent · Dateien: apps/agent/go.mod, apps/agent/go.sum
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b462af9a2 2026-11-18T13:47:54+01:00
Review: approve (.ah-out/review/kern-deps-5/T4.verdict.json)
Änderung: `toolchain go1.27.4`; `golang.org/x/sys`, `golang.org/x/term`, `github.com/go-sql-driver/mysql`,
`github.com/go-ole/go-ole` auf die Stände aus R-1553 (`go get`, `go mod tidy`); `go` bleibt 1.27.0.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T10
Abhängt von: T3

### T5 — R-1555: Basis-Images, Paket-Upgrade, VictoriaMetrics  [x]
Komponente: server · Dateien: Dockerfile, apps/monitoring/Dockerfile, apps/ca-issuer/Dockerfile, apps/gateway/Dockerfile, apps/frps/Dockerfile, docker-compose.yml
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @7ce051634 2026-11-18T14:07:33+01:00
Review: approve (.ah-out/review/kern-deps-5/T5.verdict.json)
Änderung: neue Digests für `python:3.14-slim`, `nginx:1.30.6-alpine`, `postgres:18-alpine`, `node:26-alpine`
(vor dem Schreiben per `imagetools inspect` gegenprüfen); `apt-get upgrade -y` bzw. `apk upgrade --no-cache` im
Paket-Schritt der Runtime-Stufen; VictoriaMetrics auf den neuesten v1.x-Patch mit Digest (Release-Notes vorher
lesen). Die `postgres:18-alpine`-Nennung in Skripten ohne Digest bleibt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py tests/test_release_images.py tests/test_compose_hardening.py tests/test_compose_healthchecks.py tests/test_compose_startup_order.py
Doku: → T10

### T6 — R-1584: pip aus den Runtime-Images entfernen  [ ]
Komponente: server · Dateien: Dockerfile, apps/monitoring/Dockerfile, apps/ca-issuer/Dockerfile, apps/server/tests/test_images_exec_only.py
Änderung: nach der Installation der Anforderungen `pip` (und setuptools/wheel, falls vorhanden) deinstallieren; der
Test prüft statt „pip läuft als app“, dass `pip`/`pip3` im Image fehlt und die App-Pakete importierbar bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: → T10
Abhängt von: T5
Test-Löschung: apps/server/tests/test_images_exec_only.py::test_after_the_step_pip_runs_as_app — pip fehlt
gewollt; ersetzt durch einen Test, dass pip fehlt

### T7 — R-1585: gosu durch setpriv ersetzen  [ ]
Komponente: server · Dateien: Dockerfile, apps/monitoring/Dockerfile, apps/ca-issuer/Dockerfile, apps/server/docker-entrypoint.sh, apps/monitoring/docker-entrypoint.sh, apps/ca-issuer/docker-entrypoint.sh, apps/server/tests/test_images_exec_only.py
Änderung: `exec gosu app:app …` → `exec setpriv --reuid=app --regid=app --init-groups …`; `gosu` aus den
`apt-get install`-Zeilen. Der Test startet Prozesse wie der Entrypoint (setpriv) und prüft weiter, dass sie nicht
dumpable sind; ein neuer Test, dass kein Entrypoint und kein Dockerfile `gosu` nennt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: → T10
Abhängt von: T5

### T8 — R-1587: jsdom 31 im Web  [ ]
Komponente: web · Dateien: apps/web/package.json, apps/web/package-lock.json
Änderung: `jsdom` ^30.1.3 → ^31; Unit-Tests grün, Anpassungen nur in Tests, falls nötig (`set-files`).
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (Test-Abhängigkeit)

### T9 — R-1587: jsdom 31 in der Desktop-UI  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json
Änderung: wie T8 für `apps/desktop/ui`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (Test-Abhängigkeit)

### T10 — Doku und CHANGELOG  [ ]
Komponente: server · Dateien: docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-deps-5.md, DEVELOPMENT.md
Änderung: `gosu`-Stellen auf `setpriv`, pip fehlt im Runtime-Image; Changelog-Fragment (neutral: aktualisierte
Abhängigkeiten und Basis-Images, Images ohne pip und gosu).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: docs/developer/server.html DE+EN · changelog.d/kern-deps-5.md
Task-Review: am Ende

## Entscheidungen
