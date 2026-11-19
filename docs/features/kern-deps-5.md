<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Abhängigkeiten und Images nachziehen (kern-deps-5)

Roadmap: R-1552, R-1553, R-1555, R-1584, R-1585, R-1586, R-1587. Kevin 2026-11-18 Triage: angenommen; R-1584 „pip
im Runtime-Image entfernen“, R-1585 „in eigenen Images gosu durch setpriv ersetzen, im offiziellen postgres-Image
hinnehmen“.

## Problem je Zeile

- **R-1552 — Pins nachziehen.** Desktop `libz-sys` 1.1.31 → 1.1.33 (`apps/desktop/src-tauri/Cargo.lock`); die
  Go-Stufe des frps-Images (`apps/frps/Dockerfile`, `golang:1.27.3-alpine`) und `toolchain` in `apps/agent/go.mod`
  (`go1.27.3`) → 1.27.4. Das Release v0.47.0 baut den Agent schon mit 1.27.4.
- **R-1553 — Semver-kompatible Updates.** Desktop `Cargo.lock` (rund 60 Crates, darunter tauri 2.12.6); Agent
  `golang.org/x/sys`, `golang.org/x/term`, `go-sql-driver/mysql`, `go-ole`.
- **R-1555 — Basis-Images.** Die Digests von `python:3.14-slim`, `nginx:1.30.6-alpine`, `postgres:18-alpine`,
  `node:26-alpine` (Stand 2026-11-02) haben neuere Upstream-Stände; der neue Digest allein bringt nicht jedes
  Paket auf Stand (die frps-Basis wird upstream nicht neu gebaut). VictoriaMetrics `v1.155.0` hat Nachfolger.
- **R-1584 — pip im Runtime-Image.** Server, Monitoring und CA-Issuer installieren mit pip und behalten es; pip
  bringt eigene vendorte Pakete mit, läuft zur Laufzeit aber nie.
- **R-1585 — gosu.** Die eigenen Python-Images wechseln im Entrypoint per `gosu` auf `app`; das Debian-Paket ist
  mit einer alten Go-Version gebaut. Ersatz: `setpriv` (util-linux, im Basis-Image vorhanden). Das offizielle
  postgres-Image bleibt.
- **R-1586 — cargo audit.** Neun erlaubte Warnungen (unmaintained, unsound, yanked) ohne Begründung.
- **R-1587 — jsdom 31.** Major-Update der Test-Umgebung in `apps/web` und `apps/desktop/ui`.

## Ziel & Nicht-Ziele

- Alle Pins auf dem geprüften Stand, jede Änderung mit ihrem Test; pip und gosu fehlen in den eigenen Runtime-Images,
  der Prozess `app` bleibt nicht dumpable (`tests/test_images_exec_only.py`).
- R-1586: was ein kompatibles Update behebt, wird behoben; der Rest bekommt eine Begründung in
  `apps/desktop/src-tauri/.cargo/audit.toml` (Kommentar, keine neue `ignore`-Zeile: `license_gate.rs` hält die
  Liste auf genau einem Eintrag).
- Nicht-Ziele: Major-Updates außer jsdom; das postgres-Image umbauen; Go-Minor-Wechsel.

## Betroffene Komponenten & Dateien

- desktop: `apps/desktop/src-tauri/Cargo.lock`, ggf. `Cargo.toml`, `.cargo/audit.toml` — R-1552, R-1553, R-1586
- agent: `apps/agent/go.mod`, `go.sum` — R-1552, R-1553
- Images: `Dockerfile`, `apps/monitoring/Dockerfile`, `apps/ca-issuer/Dockerfile`, `apps/gateway/Dockerfile`,
  `apps/frps/Dockerfile`, `docker-compose.yml`, die drei `docker-entrypoint.sh`; Tests unter `apps/server/tests/`
  (`test_images_exec_only.py`, `test_frps_policy_image.py`, `test_compose_*.py`) — R-1552, R-1555, R-1584, R-1585
- web, desktop-ui: `package.json`, `package-lock.json` — R-1587

## Datenmodell / API / Migrationen

Keine. Kein Wire-Format ändert sich. Workflows bleiben unberührt (`go-version: "1.27"` deckt 1.27.4).

## Trade-offs & Alternativen

- R-1555: neue Digests plus `apt-get upgrade` bzw. `apk upgrade` im Build statt nur Digests: sonst bleiben bekannte,
  fixbare Pakete stehen. Kosten: der Build ist nicht mehr allein durch den Digest bestimmt; die Release-Images werden
  ohnehin je Release gebaut und signiert.
- R-1584: `pip uninstall` am Ende der Stufe statt Multi-Stage-Umbau: kleinste Änderung, gleiches Ergebnis.
- R-1585: `setpriv --reuid app --regid app --init-groups` wechselt wie gosu vor dem `exec`; Alternative `su-exec`
  wäre ein weiteres Paket.

## Risiken & Rollback

- Entrypoints (R-1585) sind der Start jedes Containers: Test im echten Image plus Sammellauf (`linux-full`).
- Ein Crate-Update kann den Desktop-Build ändern; die PR-CI baut ihn auf Linux und Windows.
- Rollback: Commits zurücknehmen; keine Daten.

## Doku-Impact

Stellen mit `gosu` und pip im Image (`docs/developer/server.html` DE+EN), `changelog.d/kern-deps-5.md`.

## Offene Fragen

Keine (Kevin hat R-1584 und R-1585 in der Triage entschieden).
