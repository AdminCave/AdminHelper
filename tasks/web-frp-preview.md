<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: FRP-Konfigurationsvorschau beim Schließen leeren — Task-Ledger
Status: erledigt · Branch: feature/web-frp-preview · Review: am Ende
Spec: docs/features/web-frp-preview.md (Härtung, Kevin 2026-10-22)
Heavy: none — nur der Zustand einer Web-Seite, ein Komponenten-Test und ein CHANGELOG-Eintrag; keine Route, kein Schema, keine Migration, kein Server-, Gateway-, PKI-, FRP-Datenpfad-, Compose- oder Install-Pfad (die erzeugten `frps.toml`/`visitor.toml` ändern sich nicht, nur wie lange die Seite den Vorschau-Text hält); keine Web-E2E öffnet die Vorschau (`apps/web/tests/e2e` kennt `frps.toml`/`visitor.toml` nicht)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: Schließt die FRP-Konfigurationsvorschau, ist ihr Text (`frps.toml` bzw. `visitor.toml` mit `auth.token`,
Dashboard-Passwort bzw. STCP-`secretKey`) nicht mehr im Zustand der Seite; offen zeigt sie ihn wie bisher.
Zeilenangaben: origin/main@237b450a; der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Kein Pfad aus `scripts/dev/review-risk.txt`; `Review: am Ende` (ein Review über den Branch-Diff).
- Keine Änderung an `apps/web/src/modals/FrpConfigPreviewModal.svelte` und `apps/web/src/lib/components/ui/Modal.svelte`.
- Parallel: `web-fixes` (PR #261) ändert `apps/web` (Stores, `client.ts`, i18n) und `CHANGELOG.md` (`### Fixed`),
  nicht `Frp.svelte`; vor dem Push `origin/main` hineinmergen.
- Neue Code-Kommentare englisch; Testwerte erkennbar unecht (`frp-s3cr3t-token`, `dash-s3cr3t`, `stcp-s3cr3t`).

### T1 — FRP-Seite: Vorschau-Text beim Schließen leeren  [x]
Komponente: web · Dateien: apps/web/src/pages/Frp.svelte, apps/web/src/pages/Frp.preview.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @2db77211 2026-10-22T13:02:25+02:00
Review: am Ende (Branch-Review)
Änderung: In `apps/web/src/pages/Frp.svelte` wird das `onClose` der Vorschau (`:266`, heute `() => (previewOpen = false)`) eine Funktion `closePreview()`, die `previewOpen = false` und `previewContent = ''` setzt, wie `handleCloseReveal` (`apps/web/src/pages/ApiKeys.svelte:46-49`) und das `onClose` des Webhook-Token-Dialogs (`apps/web/src/pages/Hooks.svelte:224-228`). Jeder Schließweg läuft über diese Prop (`FrpConfigPreviewModal.svelte:32`, `:37`; `Modal.svelte:28-30`). Ein kurzer Kommentar nennt das Warum: der Text trägt die FRP-Zugangsdaten (auth token, dashboard password, STCP secret keys) und soll nicht bis zum Verlassen der Seite bleiben. `previewTitle` (`:66`) und `showPreview` (`:122-131`) bleiben. Neue Testdatei `apps/web/src/pages/Frp.preview.test.ts`, SPDX-Header per `reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later` (Form wie `Frp.test.ts:1-3`), Kopfkommentar mit dem Warum der Naht: die echte `Modal` rendert geschlossen nichts (`apps/web/src/lib/components/ui/Modal.svelte:71`), ein DOM-Test wäre auch ohne den Fix grün. Mocks: `vi.mock('$lib/api/frp', …)` wie `Frp.test.ts:25-29`, dazu `getFrpsToml` und `getVisitorToml`; `listConfigs` liefert eine Konfiguration (sonst fehlen die Knöpfe, `Frp.svelte:161`), `supervisorStatus` eine Antwort oder eine Ablehnung; `FrpConfigPreviewModal` per `vi.mock('$modals/FrpConfigPreviewModal.svelte', () => ({ default: h.Preview }))` mit `h = vi.hoisted(() => ({ Preview: vi.fn<…>() }))` wie `apps/desktop/ui/src/components/AppShell.workspace.test.ts:18-25`, `:60-70`. Svelte ruft sie als `Preview(anchor, props)` mit Gettern für `open`, `title`, `content` auf (Spec, „Externe Integrationen“); der Test liest `props` aus dem Aufruf, `FrpConfigModal` und `FrpStatusModal` bleiben echt (geschlossen ohne Effekt, `FrpConfigModal.svelte:43-63`, `FrpStatusModal.svelte:29-35`). Tests, parametrisiert über `frps.toml` (`getFrpsToml`, Text mit `auth.token = "frp-s3cr3t-token"` und `webServer.password = "dash-s3cr3t"`) und `visitor.toml` (`getVisitorToml`, Text mit `auth.token = "frp-s3cr3t-token"` und `secretKey = "stcp-s3cr3t"`): (a) Klick auf den Knopf → `h.Preview` genau einmal aufgerufen, `props.open` ist `true`, `props.title` der Dateiname, `props.content` genau der Text; (b) danach `props.onClose()` und `await tick()` → `props.open` ist `false`, `props.content` ist `''`; (c) erneuter Klick → der Abruf lief zweimal, `props.open` ist `true` und `props.content` wieder der Text. Zuerst rot: (b) auf HEAD (`props.content` ist nach dem Schließen noch der Text); (a) und (c) sind die positiven Gegenstücke.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Frp.preview.test.ts
Doku: CHANGELOG.md (`[Unreleased]`, `### Changed`, direkt nach dem Eintrag „Web: Stores halten nach dem Anlegen nur die Felder der Liste“ (`CHANGELOG.md:15-18`), umlautfrei: „**Web: FRP-Konfigurationsvorschau wird beim Schliessen geleert:** Der Text von `frps.toml` bzw. `visitor.toml` (mit Auth-Token, Dashboard-Passwort bzw. STCP-Schluesseln) bleibt nach dem Schliessen der Vorschau nicht mehr bis zum Verlassen der FRP-Seite im Speicher der Seite.“); `docs/` keine (keine Seite beschreibt die Vorschau, `docs/developer/webui.html:64` gilt den Stores)
Beweis: Code-Lesung apps/web/src/pages/Frp.svelte:126, :266
Orakel: contract — nach `onClose` ist die `content`-Prop der Vorschau leer; offen trägt sie den abgerufenen Text
HEAD: 237b450a
Semantik: keine Stelle in docs/ beschreibt die Vorschau (gesucht: `frps.toml`, `visitor.toml`, Vorschau/preview in `docs/admin`, `docs/developer`, DE+EN). Maßstab sind die Dialoge, die schon beim Schließen leeren (`apps/web/src/pages/Hooks.svelte:224-228`, `apps/web/src/pages/ApiKeys.svelte:46-49`), und `docs/developer/webui.html:64` — „Ein einmalig angezeigter Wert aus einer Create-Antwort (API-Key, Webhook-Token) geht nur an den Aufrufer“.
