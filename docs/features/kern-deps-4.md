<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-4 — Desktop-Backend: webpki-root-certs auf aktuellen Stand

Roadmap: R-1093. Stand `origin/main@4e0d5f7e`.

## Problem / Motivation

Der wöchentliche Dependency-Audit (`audit.yml`, 2026-11-02) ist rot: `cargo audit` meldet für
`apps/desktop/src-tauri/Cargo.lock` den Stand `webpki-root-certs` 1.0.9. Die Lösung des Advisories ist „Upgrade to
>=1.0.10“. Das Paket kommt transitiv über `rustls-platform-verifier` 0.7.1 ← `reqwest` 0.13.5 (direkt und über
`tauri`).

## Ziel & Nicht-Ziele

**Ziel:** `webpki-root-certs` im Lockfile auf 1.0.11 (crates.io, 2026-11-03) heben, nur dieses Paket
(`cargo update -p webpki-root-certs --precise 1.0.11`). `cargo audit` meldet danach nur noch die erlaubten
Warnungen.

**Nicht-Ziele:** keine weiteren Paket-Updates (die laufen in kern-deps-2/-3), kein Eingriff in `Cargo.toml`.

## Betroffene Komponenten & Dateien

`apps/desktop/src-tauri/Cargo.lock`, `changelog.d/kern-deps-4.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

RustSec-Advisory-Datenbank (`cargo audit`), crates.io `webpki-root-certs`.

## Trade-offs & Alternativen

Gleiches Vorgehen wie bei R-0657 (`webpki-roots`): reiner Lockfile-Bump. Ein breiteres `cargo update` würde den
Umfang von kern-deps-2/-3 vorwegnehmen.

## Risiken & Rollback

Die Wurzelmenge der Plattform-Prüfung ändert sich, wie es das Advisory verlangt. Rollback: Revert.

## Doku-Impact

`changelog.d/kern-deps-4.md` (`### Security`). Sonst keine.

## Offene Fragen

Keine.
