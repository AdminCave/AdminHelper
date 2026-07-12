# AdminCave-Design-System-Adoption (Web + Desktop) — Spec

## Problem / Motivation

AdminHelper ist Teil von **[Admin Cave](https://admincave.com)**, hat aber noch das
alte, eigenständige Design aus der Vor-AdminCave-Zeit: dunkles Navy (`#0f1117`),
Blau-Akzent `#4d9fff`, Inter/JetBrains als reine `font-family`-Deklaration (nicht
gebündelt → System-Fallback), 6–12px-Radien, gefüllte Akzent-Buttons und ein
**Verlaufs**-Logo (Cyan→Blau). Das AdminCave-Design-System
(`AdminCave/DesignSystem`) definiert dagegen eine klare, monochrome, high-contrast
Marke: True-Black `#000` (dark-first) mit gleichwertigem Light-Mode auf Pure-White
`#fff`, Blau **nur** als Akzent, **Geist**-Font, **Pill-Radien** (999px) für
Buttons/Inputs/Chips, **monochrome** Primary-Buttons, Hairline-Borders statt
Schatten und einen monochromen `currentColor`-Brand-Mark (Verläufe explizit
verboten).

Das DS liefert sogar ein Referenz-Kit **speziell für AdminHelper**
(`ui_kits/adminhelper/`) — es behält exakt die heutige Struktur (240px-Sidebar,
Topbar, Server-Tabelle, Monitoring) und ändert **nur** die visuelle Sprache. Genau
das ist der Auftrag.

Quelle / Design-Referenz: `AdminCave/DesignSystem` (main) — `README.md`,
`SKILL.md`, `tokens/*.css`, `ui_kits/adminhelper/`.

## Ziel & Nicht-Ziele

**Ziel:** Die **grundsätzliche visuelle Sprache** beider Svelte-Frontends
(`apps/web`, `apps/desktop/ui`) auf das AdminCave-DS umstellen — Farben, Typografie
(Font-Familie), Radien, Button-/Input-/Card-/Status-Look, Brand-Mark — plus einen
**Light-Mode mit Umschalter** (das DS ist dark-first, definiert aber einen
gleichwertigen Light-Mode). Ergebnis: beide Apps sehen „AdminCave" aus, in Dark
**und** Light.

**Nicht-Ziele (bewusst raus):**
- **Kein Layout-/Aufteilungs-Umbau.** Keine Panels, Spalten, Sidebars, Drawer,
  Tabellen-Struktur oder Ansichten verschieben/umsortieren. DOM-Struktur und alle
  Layout-Regeln (Grid/Flex/`width`/strukturelles `padding`) bleiben. Nur der
  *Look* der Elemente ändert sich.
- **Kein Type-Scale-Umbau.** Font-**Familie** wird Geist, aber die bestehende
  Schriftgrößen-Skala (`--text-*`) bleibt, um Reflow/Dichte-Änderungen und damit
  Layout-Verschiebungen zu vermeiden.
- **Aktiv-Nav-Signature nicht übernehmen.** Das DS zeigt aktive Nav per Gewicht +
  Indikator (ohne Füllung); AdminHelper behält bewusst den **gefüllten** Aktiv-Pill,
  nur farblich angeglichen (Nutzer-Entscheidung).
- **Keine anderen Oberflächen.** `docs/`-HTML-Chrome, Gateway-Fehlerseiten,
  E-Mail-/Print-Templates, Server-Enrollment-Seiten: nicht Teil dieser Lane.
- **Keine geteilte Token-Bibliothek** (kein `packages/tokens`-Refactor) — YAGNI;
  siehe Trade-offs.

## Betroffene Komponenten & Dateien

**Web (`apps/web`)** — sehr sauber, fast alles zentral:
- `src/styles/global.css` (21 KB) — die eine Token- + Komponenten-CSS.
- `src/main.ts` — Font-Import.
- `index.html` — trägt noch den **Alt-Produktnamen** `<title>Simple Remote Manager</title>`
  (einziges Leftover im Frontend) + `theme-color #0b0e14`; bekommt zusätzlich das
  FOUC-freie Inline-Theme-Init im `<head>`.
- `src/lib/components/layout/Sidebar.svelte` — Brand + Footer (hat bereits
  `EN/DE`-Toggle als Muster/Platz für den Theme-Switch).
- `src/pages/Login.svelte` — Brand.
- Hartkodierte Hex (nur 4): `src/pages/Frp.svelte`, `src/pages/Audit.svelte`,
  `src/modals/FrpStatusModal.svelte`.
- `public/logo.svg`, `public/assets/logo.svg` — Brand-Mark.
- neu: `src/lib/stores/theme.ts` (+ `.test.ts`), `e2e/…` Theme-Toggle.

**Desktop (`apps/desktop/ui`)** — mehr Scoped-Styles:
- `src/styles/app.css` (55 KB) + `src/styles/global.css` (Imports/Reset).
- `src/main.ts` — Font-Import; `index.html` — FOUC-freies Inline-Theme-Init
  (Titel ist bereits `AdminHelper`).
- `src/components/AppShell.svelte` — Brand + Footer (Toggle-Platz).
- `src/components/Login.svelte` — Brand.
- 24 `.svelte` mit `<style>`, ~32 hartkodierte Hex — v.a. `StatusBar.svelte`,
  `NotificationBell.svelte`, `TunnelIndicator.svelte`,
  `components/infra/tabs/MonitoringTab.svelte`,
  `components/monitoring/MonChart.svelte`, `.../MonStatusTimeline.svelte`.
- `public/logo.svg` — Brand-Mark.
- neu: `src/lib/stores/theme.ts` (+ `.test.ts`).

**Doku:** `docs/developer/webui.html`, `docs/developer/desktop.html` (+ `docs/en/…`),
`CHANGELOG.md`, ggf. `README.md`.

## Datenmodell / API / Migrationen

**Keine.** Rein Frontend/visuell. Kein Server-/API-/Pydantic-/Alembic-Kontakt,
keine Contract-Drift zu Agent/Server. Theme-Präferenz ist **nicht-sensitive
UI-State** → `localStorage` (`ah-theme`), **nicht** ins persistierte Desktop-
`Settings`-Contract (kein Rust-/Settings-Modell-Eingriff, keine Migration).
`data-theme`-Attribut auf `<html>` steuert das Theme (wie im DS:
`:root[data-theme="light"]`), Default = dark (Attribut fehlt/`"dark"`).

## Externe Integrationen

- **Geist / Geist Mono** (OFL) — statt Google-Fonts-CDN (DS nutzt CDN) wird die
  Schrift **gebündelt** eingebettet: `@fontsource-variable/geist` +
  `@fontsource-variable/geist-mono`, importiert im jeweiligen `main.ts`. Grund:
  Desktop läuft offline / unter CSP, Web ist self-hosted — ein CDN-`@import` ist
  dort ein Fehler. **Exakter Paketname beim Build verifizieren** (npm), Fallback
  `@fontsource/geist`.
- **AdminCave-Mark** — `assets/admincave-mark.svg` aus dem DS (rounded-square mit
  Homebase-Peak, `currentColor`, `fill-rule:evenodd`, theme-adaptiv).
- Kein FRP/Tauri-IPC/VictoriaMetrics-Wire-Format berührt.

## Token-Rezept (Kern der Änderung)

**Strategie:** Die bestehenden AH-Token-**Namen** behalten (`--bg`, `--accent`,
`--sp-*`, `--radius-*`, `--font`, …) und ihre **Werte** auf die DS-Semantik setzen;
zusätzlich einen `:root[data-theme="light"]`-Block und die wenigen fehlenden
DS-Tokens ergänzen. Kein globales Umbenennen (76 KB CSS + Scoped-Styles würden
sonst unnötig anfassen — verstößt gegen Surgical-Changes). Beide `:root`-Blöcke
(web `global.css` + desktop `app.css`) werden **wertgleich** gehalten.

Dark (`:root`) — AH-Name → neuer Wert (DS `colors.css`):
`--bg` `#000` · `--bg-surface` `#050506` · `--bg-elevated` `#101013` ·
`--bg-sidebar` `#000` (Trennung via Border) · `--border` `rgba(255,255,255,.10)` ·
`--border-hover` `rgba(255,255,255,.18)` · `--text` `#ededee` · `--text-muted`
`#9aa1a8` · `--text-faint` `#6e757c` · `--accent` `#4f9dff` · `--accent-hover`
`#7db3ff` · `--accent-bg` `rgba(79,157,255,.14)` · `--success` `#34d186` ·
`--warning` `#f5b454` · `--danger` `#ff6b6b` · `--green` `#34d186`.
Neu: `--fill-solid #fff` / `--fill-solid-hover #dfe2e5` / `--fill-solid-text #000` ·
`--radius-pill 999px` · `--radius-2xl 28px` · `--shadow-pop 0 8px 28px rgba(0,0,0,.6)` ·
`--ring rgba(79,157,255,.55)`. Radien angleichen: `--radius-lg 12→16`, `--radius-md
8→12`, `--radius-sm 6→8`.

Light (`:root[data-theme="light"]`) — DS-Light-Aliase auf dieselben AH-Namen:
`--bg #fff` · `--bg-surface #fff` · `--bg-elevated #fff` · `--bg-sidebar #f4f5f6` ·
`--border rgba(0,0,0,.10)` · `--border-hover rgba(0,0,0,.16)` · `--text #16181c` ·
`--text-muted #565c64` · `--text-faint #868d94` · `--accent #2563eb` ·
`--accent-hover #1d4ed8` · `--accent-bg rgba(37,99,235,.10)` · `--success #1f9d57` ·
`--warning #e0961f` · `--danger #e5484d` · `--fill-solid #000` /
`--fill-solid-text #fff` · hellere Schatten · `color-scheme: light`.

Fonts: `--font: 'Geist Variable','Geist',system-ui,-apple-system,'Segoe UI',sans-serif` ·
`--font-mono: 'Geist Mono Variable','Geist Mono',ui-monospace,'SF Mono',monospace`.

**Komponenten-Regeln** (nur Look, keine Layout-Regeln):
Buttons/Inputs/Select/Search → `--radius-pill`; Textarea → 12px; `.btn.primary`
monochrom (`--fill-solid`/`--fill-solid-text`) statt Akzent-Füllung; `.panel`/
Cards → `--radius-lg` (16px), Login-Card/Modal → `--radius-2xl` (28px); Badges/
Tags/Toasts → getönte Pills mit Hairline; **Aktiv-Nav bleibt gefüllt**, nur Farben
über Tokens; Fokus-Ring `--ring`.

## Trade-offs & Alternativen

- **Werte-Swap statt Token-Rename (empfohlen).** Minimaler Diff, kein Anfassen der
  Layout-Klassen. Nachteil: AH-Namen ≠ DS-Namen (kognitiver Bruch beim Quervergleich)
  — akzeptabel, in `global.css`/`app.css` kommentiert.
- **Keine geteilte Token-Datei.** Web und Desktop halten je eigene, aber wertgleiche
  `:root`-Blöcke (heute schon dupliziert). Ein `packages/tokens`-Paket wäre sauberer,
  erzwingt aber Build-Config-Änderungen in zwei Vite-Setups → YAGNI, out of scope.
  **Risiko: Drift** → Ledger hält Web/Desktop-Token-Tasks bewusst parallel & wertgleich.
- **Geist gebündelt statt CDN (empfohlen).** +2 Deps je App, dafür offline/CSP-fest.
- **Type-Scale unverändert (empfohlen).** DS-Body ist 15px vs. AH 14px; ein Bump
  würde reflowen → widerspricht „kein Layout". Nur Font-Familie wechselt.
- **Monochrome Primary-Buttons + Pill-Radien** sind sichtbare Änderungen (Blau→Weiß/
  Schwarz, eckig→Pille). Kernbestandteil des DS-Looks → übernommen, aber am Gate
  explizit ausgewiesen (veto-fähig).

## Risiken & Rollback

- **Light-Mode deckt Ecken auf,** die dark-only-Annahmen hartkodieren (fixe Hex,
  `#0f1117`-Textfarben auf Buttons, uPlot-Charts). Deshalb eigene Tasks für Hex→Token
  (T4/T10) und Chart-Theming (T11).
- **Charts (uPlot)** haben eigenes CSS + teils fixe Serien-/Achsen-Farben →
  aufwändigster Light-Teil; in beiden Themes auf Lesbarkeit prüfen (crabbox-GUI).
- **Layout-Regression** durch Radius-/Font-Wechsel möglich (z. B. Umbruch) →
  Verify per crabbox-Screenshot-Diff „kein Shift".
- **Rollback:** rein additiv/visuell, ohne DB/Contract — Branch/Commits revertierbar;
  Theme-Store entfernen + Token-Blöcke zurücksetzen genügt.

## Doku-Impact

Nach außen sichtbar (visueller Overhaul + neuer Light-Mode-Umschalter → User-Feature),
also **dokumentieren, proportional**: `docs/developer/webui.html` +
`docs/developer/desktop.html` (**+ `docs/en/…`**) um DS-Adoption + Theme-Umschalter
ergänzen; `CHANGELOG.md` (`Added`: AdminCave-DS-Retheme, Light-Mode); ggf. eine
`README.md`-Zeile. Keine neuen Endpunkte/Env/Ports/Wire-Formate → sonst nichts.

## Offene Fragen (fürs Gate)

1. **Theme-Umschalter-Platzierung:** Vorschlag = kleiner Icon-Button im
   Sidebar-Footer beider Apps (Web: neben dem bestehenden `EN/DE`-Button; Desktop:
   im `AppShell`-Footer). Bewusst nicht in einem Modal/Menü, aber ohne Layout-Umbau.
   OK so?
2. **Sichtbare Look-Änderungen bestätigen:** monochrome Primary-Buttons
   (Blau → Weiß/Schwarz) und **Pill-Radien** auf Buttons/Inputs — beides
   DS-Kern, aber deutlich sichtbar. Übernehmen (empfohlen) oder abschwächen?
3. **Light-Mode-Default:** Start in Dark (empfohlen), Light nur auf Wunsch — korrekt?
