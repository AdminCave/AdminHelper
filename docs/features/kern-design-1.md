<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-design-1 — Desktop-Design-Fundament nach dem AdminCave-DesignSystem

Roadmap: R-1061 (FEAT, Kevin 2026-11-02: Start des Design-Programms; löst R-0714 ab).
Vorlage: `AdminCave/DesignSystem@244e890` (`tokens/*.css`, `components/*/*.d.ts`, `ui_kits/adminhelper/kit.jsx`).

## Problem / Motivation

Das Design-Programm (R-1062 bis R-1082: Shell, Einstellungen, Verbindungen, Terminal, Monitoring-Verlauf,
Benachrichtigungen) baut die Desktop-Oberfläche nach dem gemeinsam geplanten Mockup um. Jede dieser Zeilen braucht
dieselbe Grundlage, die es heute nicht gibt:

- **Tokens:** `apps/desktop/ui/src/styles/app.css:1-125` steht auf dem alten DS-Stand (True-Black `#000`, eigene Namen
  wie `--bg-surface`, `--bg-panel`, `--text-faint`). Es fehlen soft black `#17181b`, `surface`/`raised`/`inset`,
  die Status-Paare `--*-bg`/`--*-border`, die Motion-Tokens und `--ring-shadow`.
- **Icons:** 28 Inline-SVGs in acht Dateien, ohne eine Icon-Bibliothek.
- **Komponenten:** `components/ui/` hat nur `Modal`, `ConfirmDialog` und `EmptyState`. Jede Seite baut Buttons, Pills,
  Felder und Tabs selbst.
- **Dialoge (R-0714):** `Modal.svelte` setzt keinen Anfangsfokus, hat keine Fokusfalle und kein `aria-labelledby`.

## Ziel & Nicht-Ziele

**Ziel**
- Die DS-Tokens (Farben dark und light, Radius, Schatten, Motion, Fokus-Ring, Spacing) stehen in `app.css`. Die alten
  AH-Namen bleiben als Aliase auf die DS-Namen, damit bestehende Seiten unverändert weiterlaufen und dabei den neuen
  Stand zeigen.
- `@lucide/svelte` (ISC) ersetzt die Inline-SVGs.
- `components/ui/` enthält eine Svelte-5-Bibliothek nach den DS-Verträgen:
  - Button, IconButton, Tag, Badge, Pill, Dot, Kbd, Spinner, Panel
  - Input, SearchField, Select, Switch, Checkbox, RadioGroup, Slider, FormField
  - Tabs, Segmented, Menu, Tooltip, Toast, Dialog
  - Callout, EmptyState, Skeleton, CodeBlock, MetaList

  Jede Komponente hat ihren Test.
- Der Dialog ist das bisherige `Modal.svelte`, erweitert um Anfangsfokus, Fokusfalle, `aria-labelledby` und
  `aria-describedby`. Seine bisherige Schnittstelle bleibt, damit alle acht Nutzer unverändert laufen.

**Nicht-Ziele**
- Seiten auf die neuen Komponenten umbauen. Das tun die Folgezüge je Seite (R-1062 Shell, R-1063 Einstellungen,
  R-1065 Verbindungen usw.).
- Die sieben Dialoge mit eigenem Overlay aus R-0714 auf den Dialog umziehen. Sie wandern mit ihren Seiten in den
  Folgezügen (R-1063 übernimmt SettingsModal).
- Das Web-Panel (`apps/web`). Es bleibt auf seinem Token-Stand. Der Kommentar „wertgleich zu apps/web“ in
  `app.css` entfällt.
- Neue Schriften: Geist ist schon gebündelt (`@fontsource-variable`).

## Betroffene Komponenten & Dateien

Nur `apps/desktop/ui`:
- `src/styles/app.css` (Tokens, Basisregeln für Fokus-Ring und reduzierte Bewegung)
- `src/components/ui/*.svelte` (neu) und Tests
- `src/components/ui/Modal.svelte`
- `package.json`, `package-lock.json` (`@lucide/svelte`)
- die acht Dateien mit Inline-SVG:
  - `components/AppShell.svelte`
  - `components/Login.svelte`
  - `components/NotificationBell.svelte`
  - `components/Picker.svelte`
  - `pages/Connections.svelte`
  - `components/monitoring/MonSparkline.svelte`
  - `components/monitoring/section/MonSectionIcon.svelte`
  - `components/monitoring/section/SecLive.svelte`

  Sparkline- und Ring-Grafiken bleiben SVG, ersetzt werden nur die Symbole.
- `THIRD_PARTY_LICENSES.md`, die Desktop-Doku (DE und EN), `changelog.d/kern-design-1.md`

## Datenmodell / API / Migrationen

Keine. Kein Rust, keine Tauri-Commands, kein Server.

## Externe Integrationen

- Lucide für Svelte 5: `@lucide/svelte` 1.66.0, Lizenz ISC, Peer `svelte ^5`. Je Symbol ein Import (tree-shakeable).
  Die Dokumentation liegt unter lucide.dev/guide/packages/lucide-svelte und wird vor dem Bau gelesen.

## Trade-offs & Alternativen

- **Alte Token-Namen als Aliase oder überall umbenennen:** Aliase. Das Umbenennen in 65 Dateien wäre reiner Churn;
  die Folgezüge schreiben die Seiten ohnehin neu und nehmen dabei die DS-Namen. Empfehlung: Aliase.
- **Dialog neu oder Modal erweitern:** Modal erweitern, mit Komponentenname `Modal` und DS-Vertrag als Obermenge.
  Ein zweiter Dialog neben Modal hieße zwei Fokus- und Stack-Logiken.
- **Lucide oder eigenes Icon-Set:** Lucide, so steht es im DS und im Mockup.
- **Komponenten als Snippet-Props:** Wo React `ReactNode` nimmt, nimmt Svelte `Snippet` oder einen String. Icons
  werden als Lucide-Komponente übergeben (`icon={Search}`).

## Risiken & Rollback

- Optische Regressionen auf allen Seiten durch den Token-Wechsel: soft black statt `#000` und andere Flächen. Das
  ist gewollt (Mockup). Die Unit-Tests prüfen keine Farben. Die GUI-E2E im Sammellauf prüfen Funktionen, keine Optik.
- Die Fokusfalle kann bestehende Dialog-Abläufe ändern, etwa Tab im Formular oder einen gestapelten ConfirmDialog.
  Das decken die bestehenden Dialog-Tests ab, dazu kommen neue Tests für Falle und Stapel.
- Rollback: einzelne Task-Commits revertieren. Es gibt keinen Daten- oder Vertragsbezug.

## Doku-Impact

`docs/developer/desktop.html` und `docs/en/developer/desktop.html`, Abschnitt Design-System (heute „True-Black,
wertgleich zum Web-Panel“): neuer Token-Stand, Lucide, `components/ui` als Bibliothek.
Dazu `THIRD_PARTY_LICENSES.md` (Lucide) und das Changelog.

## Offene Fragen

- R-0714 (sieben eigene Overlays) wird hier nicht vollständig gelöst, siehe Nicht-Ziele. Empfehlung: R-0714 als
  `zurückgestellt` führen, mit Verweis auf die Folgezüge. Das entscheidet Kevin.
