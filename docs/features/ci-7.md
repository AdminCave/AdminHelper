<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ci-7: Downloads der CI wiederholen, xrdp-Suite je PR

Zug `tasks/ci-7.md`, Roadmap R-1130, R-1160, R-1194, R-1142 (Kevin 2026-11-09 Triage, vor 0.47.0). Alle vier Zeilen
ändern `.github/workflows/ci.yml`; den Merge macht Kevin (CLAUDE.md §2).

## Problem / Motivation

- **R-1130:** Der Schritt „Tauri system dependencies“ (`ci.yml:716` im Job `rust`, `ci.yml:791` in
  `tauri-build-smoke`) läuft in sein 10-min-Limit, wenn der Azure-Spiegel kriecht (Lauf 41888786175, apt-Downloads
  18:42–18:46Z). Der Job ist rot und braucht einen manuellen Rerun.
- **R-1160:** „Install Playwright browsers“ (`ci.yml:691`) läuft in sein 10-min-Limit. Im Lauf 42171086845 (Job
  127738815106) war apt nach Sekunden fertig, der Download der Browser von `cdn.playwright.dev` hing („Downloading
  Chrome Headless Shell …“, danach nichts). Der Kommentar über dem Schritt nennt nur den apt-Fall; der ist mit dem
  Browser-Argument behoben, der CDN-Fall nicht.
- **R-1194:** Die Release-Downloads per `curl` (frpc-Sidecar `ci.yml:725,766,812`, oasdiff `ci.yml:952`) haben kein
  `--retry`; ein 504 von github.com machte in PR #418 fünf Jobs rot (Lauf 42465851987).
- **R-1142:** Die xrdp-Suite `scripts/tests/desktop_e2e_rdp_embedded.sh` läuft nur im Sammellauf (Teil `gui`); ein
  Fehler im eingebetteten RDP fällt damit erst nach dem Merge auf. Sie braucht Docker, openssl, die Tauri-Pakete, den
  frpc-Sidecar und `cargo tauri` — alles auf einem GitHub-Runner vorhanden oder installierbar, kein Display.

## Ziel & Nicht-Ziele

**Ziel:** Ein hängender oder kriechender Download kostet einen Versuch, nicht den Job; ein 5xx von github.com einen
Retry; die xrdp-Suite ist ein PR-Gate.

**Nicht-Ziele:**
- `release.yml` (eigene Downloads, läuft nur auf Tags; nicht Teil der Zeilen).
- Ein apt-Paket-Cache: der Hänger von R-1130 lag im Download, den der Versuch mit Frist abdeckt; ein Cache
  der `.deb` bräuchte Rechte auf `/var/cache/apt` und eine Schlüsselpflege je Runner-Image (YAGNI).
- Die übrigen `desktop_e2e_*`-Suiten (WebKit-Kette, bewusst nicht in CI, `ci.yml` Kommentar am Ende).

## Betroffene Komponenten & Dateien

- `.github/workflows/ci.yml` (Jobs `frontend-e2e`, `rust`, `rust-windows`, `tauri-build-smoke`, `openapi-compat`, neu
  `rdp-embedded`).
- Neu `.github/scripts/retry.sh` (SPDX): `retry.sh <versuche> <sekunden> <befehl…>` — jeder Versuch unter
  `timeout`, Exit des letzten Versuchs. Liegt neben, nicht unter `workflows/`.
- Doku `docs/developer/cicd.html`, `docs/en/developer/cicd.html`, `changelog.d/ci-7.md`.

## Entwurf

- **apt (R-1130):** erst `apt-get update` und `apt-get install --download-only` unter `retry.sh 3 180` (ein Abbruch
  im Download lässt dpkg unberührt), mit `-o Acquire::Retries=3 -o Acquire::http::Timeout=30`; dann `apt-get install`
  aus dem Cache ohne Frist-Abbruch. Das Schritt-Limit steigt auf 12 min (drei Versuche plus Install).
- **Playwright (R-1160):** `actions/cache` auf `~/.cache/ms-playwright`, Schlüssel aus der Version von
  `playwright-core` in `apps/web/node_modules`; `npx playwright install-deps chromium` (apt) und
  `npx playwright install chromium` (CDN, bei Cache-Treffer ein No-op) je unter `retry.sh 3 180`.
- **curl (R-1194):** `--retry 5 --retry-delay 5 --connect-timeout 30` an allen vier Stellen; curl wiederholt damit
  408, 429, 5xx und Zeitüberschreitungen (curl-Doku `--retry`).
- **xrdp (R-1142):** Job `rdp-embedded` auf `ubuntu-26.04` wie `rust`: Tauri-Pakete (wie oben), frpc-Sidecar,
  Toolchain, `Swatinem/rust-cache`, `cargo install tauri-cli --locked --version "2.12.4"` (Lockstep mit
  `tauri-build-smoke`/`release.yml`; rust-cache hält `~/.cargo/bin`), dann `bash
  scripts/tests/desktop_e2e_rdp_embedded.sh`. Die Suite endet mit 75 ohne `cargo tauri`; ein Exit ≠ 0 macht den Job
  rot, auch 75.

## Externe Integrationen

- curl `--retry`: https://curl.se/docs/manpage.html#--retry
- apt `Acquire::Retries`, `Acquire::http::Timeout`: apt.conf(5).
- `actions/cache`, Playwright-Browser-Pfad `~/.cache/ms-playwright`: https://playwright.dev/docs/browsers#managing-browser-binaries
- `Swatinem/rust-cache` `cache-bin` (Standard `true`): README des Actions-Repos.

## Trade-offs & Alternativen

- Generischer Helfer statt drei Inline-Schleifen: einmal geschrieben, lesbar im Job. Er liegt unter `.github/scripts/`,
  nicht im Hermetik-Block von `run.sh` (Harness-Pfad); Beweis ist der PR-Lauf, dazu `shellcheck` lokal.
- Eigener Job statt Schritt in `rust`: ein roter xrdp-Lauf ist als solcher erkennbar, und `rust` wird nicht länger.
  Kosten: ein zweiter Kompilat-Cache; der Job ist kein Required Check, bis Kevin ihn ins Ruleset nimmt.

## Risiken & Rollback

- Kriecht der Spiegel über alle drei Versuche, bleibt der Job rot (wie heute, nach 12 statt 10 min).
- Der xrdp-Job kann flaken (R-1195, R-1258 sind mit kern-rdp-9 behoben). Rollback: den Job entfernen.

## Doku-Impact

`docs/developer/cicd.html` (DE+EN): Frist und Versuche der Downloads, der neue Job `rdp-embedded`. CHANGELOG
`### Changed`.

## Offene Fragen

Keine aus Kevins Bereich. Ob `rdp-embedded` ein Required Check wird, entscheidet Kevin nach einigen grünen Läufen
(Ruleset).
