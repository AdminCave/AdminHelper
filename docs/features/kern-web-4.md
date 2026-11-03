<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-web-4 — Web-Admin-Panel auf das neue Design

Roadmap: R-1082 (FEAT, Kevin 2026-11-02: erst Desktop, Web danach; eigene Kopie, kein gemeinsames Paket). Baut auf
R-1061 (kern-design-1, #373: Tokens, Lucide, Bibliothek `apps/desktop/ui/src/components/ui/`) auf. Vorlage:
`AdminCave/DesignSystem@244e890` (`tokens/*.css`) und die Desktop-Bibliothek. Stand `origin/main@4d1ad071`, Pfade
unter `apps/web/src/`, soweit nicht anders genannt.

## Problem / Motivation

- **Tokens:** `styles/global.css:1-75` steht auf dem alten DS-Stand: True-Black `#000`, eigene Namen wie `--bg-surface`
  und `--text-faint`. Es fehlen soft black, `surface`/`raised`/`inset`, die Status-Paare `--*-bg`/`--*-border`,
  Motion und `--ring-shadow`. Die Desktop-Oberfläche hat diesen Stand seit kern-design-1.
- **Icons:** Inline-SVGs in `lib/components/layout/Sidebar.svelte` (4) und `pages/Login.svelte` (1), keine
  Icon-Bibliothek.
- **Komponenten:** `lib/components/ui/` hat `Button`, `Modal`, `ConfirmDialog`, `Toast` und `EmptyState`. Seiten und
  Modals bauen Felder, Pills, Tabellen-Knöpfe und Formulare aus 117 globalen Klassen in `styles/global.css`.
- **Dialoge:** `lib/components/ui/Modal.svelte` setzt keinen Anfangsfokus, hat keine Fokusfalle und kein
  `aria-labelledby`. Die Desktop-Kopie hat das seit R-0714.

## Ziel & Nicht-Ziele

**Ziel:** dieselben Funktionen in der Gestalt der Desktop-Oberfläche.
- **Tokens:** auf DS-Stand wie `apps/desktop/ui/src/styles/app.css`, dunkel und hell. Alte Namen bleiben als Aliase,
  bis keine Regel sie mehr nutzt.
- **Icons:** `@lucide/svelte` in derselben Version wie der Desktop (1.66.0), Inline-SVGs raus.
- **Bibliothek:** `lib/components/ui/` als eigene Kopie der Desktop-Bausteine, die das Web braucht: `Button`,
  `IconButton`, `Pill`, `Tag`, `Dot`, `Panel`, `EmptyState`, `Spinner`, `Input`, `Select`, `FormField`, `Checkbox`,
  `Switch`, `SearchField`, `Modal` (Anfangsfokus, Fokusfalle, `aria-labelledby`), `ConfirmDialog` und `Toast`.
  Die Tests kommen mit.
- **Shell:** Sidebar wie im Desktop: aktiver Eintrag fett mit Balken, Lucide-Icons, Theme-Umschalter, Benutzer und
  Abmelden. Login-Seite auf der Bibliothek.
- **Seiten:**
  - Benutzer, API-Keys, Zertifikate, Audit, Hooks und FRP als `Panel` mit Tabelle, Bibliotheksknöpfen und `Pill`s.
  - Die zehn Modals auf `Modal`, `FormField` und `Button`.
- **CSS:** verwaiste globale Klassen raus.
- **E2E:** Die Anker der Playwright-Specs (`tests/e2e/*.spec.ts`, `tests/live/*.spec.ts`) bleiben oder ziehen in
  derselben Task nach. Dazu gehören Rollen und Namen der Knöpfe („+ Benutzer“, „Löschen“), die Feld-IDs,
  `.toast-stack .toast.success`, `.key-reveal` und `tbody tr`.

**Nicht-Ziele:**
- Neue Funktionen, neue Seiten, neue Routen oder eine neue API.
- Ein gemeinsames Paket mit dem Desktop (Kevin 2026-11-02: eigene Kopie).
- Befehlspalette, Statusleiste und Benachrichtigungen des Desktops: Das Web-Panel hat dafür keine Datenquelle und
  keine Zeile.
- Ein eigenes Web-Mockup: Das DesignSystem führt nur `ui_kits/adminhelper` (Desktop) und `admincave`. Das Web folgt
  den Bausteinen des Desktops.

## Betroffene Komponenten & Dateien

Nur `web`:
- `styles/global.css`, `styles/tokens.test.ts`
- `package.json`, `package-lock.json` (`@lucide/svelte`), `THIRD_PARTY_LICENSES.md` (Eintrag gibt es schon für den
  Desktop; die Spalte nennt dann beide)
- `lib/components/ui/*` (neu oder ersetzt, mit Tests), `lib/components/layout/Sidebar.svelte`, `App.svelte`
- `pages/*.svelte`, `modals/*.svelte` und ihre Tests
- `tests/e2e/*.spec.ts`, `tests/live/smoke.live.spec.ts`, falls ein Anker wandert; die sieben visuellen Baselines
  unter `tests/e2e/*-snapshots/`

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

Keine. Lucide: `@lucide/svelte` 1.66.0 (ISC), wie im Desktop.

## Trade-offs & Alternativen

- **Kopie statt Paket:** Ein Workspace-Paket spart Duplikat, koppelt aber Build, Versionen und Releases zweier Apps.
  Kevin hat entschieden: Kopie. Die Tests kommen mit, damit beide Seiten einzeln prüfbar bleiben.
- **Nur die nötigen Bausteine:** Was das Web nicht nutzt (`Tabs`, `Menu`, `Segmented`, `Slider`, `Avatar`,
  `Tooltip`, `Kbd`, `Callout`, `CodeBlock`, `MetaList`, `RadioGroup`, `Skeleton`), kommt nicht mit (YAGNI). Braucht
  eine Seite beim Bau einen davon, nimmt die Task ihn mit und vermerkt es unter `## Entscheidungen`.
- **Aliase für alte Token-Namen:** Ohne Aliase müsste jede Regel im selben Commit wandern. So stellt T1 die Werte um,
  und die Seiten-Tasks ziehen die Namen nach.
- **Knopftexte als E2E-Anker:** Die Specs wählen über Rolle und Namen. Die Texte bleiben, Icons kommen dazu.

## Risiken & Rollback

- **E2E:** Playwright läuft in der PR-CI (`ci.yml`, Chromium); `web-live` läuft im Sammellauf (`Heavy:
  linux-full`).
- **Visuelle Baselines:** `login.spec.ts:61` und `smoke.spec.ts:58` vergleichen sieben Bildschirmfotos. Jede
  sichtbare Änderung macht sie rot. T8 erzeugt sie neu im Playwright-Container. Weicht dessen Rendering von
  `ubuntu-latest` ab, kommen sie aus dem Artefakt des CI-Laufs.
- **Kontrast:** Neue Werte für dunkel und hell; `tokens.test.ts` prüft die Paare wie im Desktop.
- **Rollback:** je Task `git revert`, keine Datenänderung.

## Doku-Impact

- `docs/developer/webui.html` und `docs/en/developer/webui.html`:
  Tokens, Bibliothek, Icons.
- `docs/admin/*` nur, wenn sich sichtbare Wege ändern; das ist nicht geplant.
- Changelog: `changelog.d/kern-web-4.md`.

## Offene Fragen

Keine. Umfang und Kopie hat Kevin am 2026-11-02 entschieden.
