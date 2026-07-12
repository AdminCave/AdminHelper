# AdminCave-Design-System-Adoption (Web + Desktop) — Task-Ledger
Status: aktiv · Branch: feature/admincave-design-adoption · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/admincave-design-adoption.md
Fast-Suite: crabbox · Warm-Profil: desktop
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Leitplanken (für JEDE Task): Nur *Look* ändern — DOM-Struktur und alle Layout-Regeln
(Grid/Flex/`width`/strukturelles `padding`) bleiben unangetastet. Token-Werte web
(`global.css`) und desktop (`app.css`) wertgleich halten (Spec „Token-Rezept").

---

## Phase A — Web (apps/web)

### T1 — Web: Geist-Font bündeln  [x] (Geist gebündelt via @fontsource-variable + Ambient-d.ts)
Komponente: apps/web · Dateien: package.json · src/main.ts · src/styles/global.css
Änderung: `@fontsource-variable/geist` + `@fontsource-variable/geist-mono` als Dep
hinzufügen (exakten npm-Namen verifizieren, Fallback `@fontsource/geist`), in
`main.ts` importieren; `--font`/`--font-mono` in `global.css` auf Geist umstellen
(System-Fallback-Kette behalten).
Verify: `cd apps/web && npm run build` grün; DevTools `getComputedStyle(document.body).fontFamily` enthält „Geist".
Doku: keine (intern).

### T2 — Web: Token-Blöcke Dark + Light  [x] (DS-Dark-Werte + Light-Block + neue Tokens)
Komponente: apps/web · Dateien: src/styles/global.css
Änderung: `:root` auf DS-Dark-Werte setzen (Spec-Mapping); neuen
`:root[data-theme="light"]`-Block anlegen; fehlende Tokens ergänzen (`--fill-solid`,
`--fill-solid-hover`, `--fill-solid-text`, `--radius-pill`, `--radius-2xl`,
`--shadow-pop`, `--ring`); Radien angleichen (lg 16 / md 12 / sm 8). Nur der
Token-Block — Komponenten-Regeln kommen in T3.
Verify: `cd apps/web && npm run check && npm run test:unit` grün; `npm run build` grün.
Doku: keine (intern).
Abhängt von: T1

### T3 — Web: Komponenten-Look (Buttons/Inputs/Cards/Status)  [x] (Pill-Radien, monochrome Primary, Fokus-Ring, Scrollbar-Token)
Komponente: apps/web · Dateien: src/styles/global.css
Änderung: `.btn*` → `--radius-pill`, `.btn.primary` monochrom
(`--fill-solid`/`--fill-solid-text`); Inputs/Select/Search → Pill, Textarea → 12px;
`.panel`/Cards → 16px, `.login-card`/`.modal` → 28px; Badges/Tags/Toasts als getönte
Pills mit Hairline; Fokus-Ring `--ring`; Aktiv-Nav bleibt gefüllt, nur Token-Farben.
KEINE Layout-Regeln (Grid/Flex/`width`/strukturelles `padding`) anfassen.
Verify: `npm run check && npm run build` grün; crabbox-Screenshot Dashboard/Login — kein Layout-Shift ggü. vorher.
Doku: keine (intern).
Abhängt von: T2

### T4 — Web: hartkodierte Hex → Tokens  [x] (4 Inline-Hex → --success/--danger)
Komponente: apps/web · Dateien: src/pages/Frp.svelte · src/pages/Audit.svelte · src/modals/FrpStatusModal.svelte
Änderung: die 4 Inline-Hex (`#22c55e`, `#ef4444`, `#d23`) auf `--success`/`--danger`
umstellen, damit sie im Light-Mode korrekt kippen.
Verify: `grep -rniE '#[0-9a-f]{3,8}' apps/web/src --include='*.svelte'` liefert keine Chrome-Hex mehr; `npm run test:unit` grün.
Doku: keine (intern).
Abhängt von: T2

### T5 — Web: Theme-Store + Umschalter + Persistenz  [x] (FOUC-Init + theme.ts + Sidebar-Toggle + Tests + Doku)
Komponente: apps/web · Dateien: src/lib/stores/theme.ts (neu) · index.html · src/lib/components/layout/Sidebar.svelte
Änderung: **FOUC-frei** — winziges Inline-Script im `index.html`-`<head>` liest
`localStorage['ah-theme']` und setzt `document.documentElement.dataset.theme` **vor**
dem ersten Paint (sonst flackern Light-User dark→light). Neuer Store `theme.ts`
(SPDX-Header; Default `dark`, initialisiert aus dem bereits gesetzten `data-theme`,
schreibt Änderungen nach `localStorage` + Attribut); Toggle-Icon-Button im
Sidebar-Footer neben dem `EN/DE`-Button; i18n-Label ergänzen. Neuer Flow ⇒ Test.
(index.html wird auch von T6 angefasst — Reihenfolge in der Lane beachten.)
Verify: `apps/web` vitest `theme.test.ts` grün (Toggle flippt Attribut + persistiert); Playwright-E2E `theme-toggle`: umschalten → Reload → Theme bleibt.
Doku: docs/developer/webui.html + docs/en/developer/webui.html (Theme-Umschalter erwähnen) — im selben Commit.
Abhängt von: T2

### T6 — Web: AdminCave-Brand-Mark + App-Name/Meta  [x] (inline currentColor-Mark, Favicon prefers-color-scheme, Titel/theme-color)
Komponente: apps/web · Dateien: public/logo.svg · public/assets/logo.svg · index.html · src/lib/components/layout/Sidebar.svelte · src/pages/Login.svelte
Änderung: Verlaufs-`logo.svg` durch AdminCave-Mark (`currentColor`, aus DS
`assets/admincave-mark.svg`) ersetzen — **beide** Dateien (`public/logo.svg` =
Favicon, `public/assets/logo.svg` = In-App); Mark-Farbe an `--text-strong`/`--text`;
Wortmarke „Admin" (600) / „Helper" (300) über bestehende `brand-title`/`-subtitle`.
In `index.html`: Alt-Titel `Simple Remote Manager` → `AdminHelper`, `theme-color`
`#0b0e14` → `#000`.
Verify: `npm run build` grün; Mark rendert sichtbar in Dark **und** Light (crabbox-Screenshot); `grep -ri 'simple remote manager' apps/web` leer.
Doku: keine (intern).
Abhängt von: T2

---

## Phase B — Desktop (apps/desktop/ui)

### T7 — Desktop: Geist-Font bündeln  [x] (Geist in dependencies + Ambient-d.ts, wertgleich Web)
Komponente: apps/desktop/ui · Dateien: package.json · src/main.ts · src/styles/app.css
Änderung: analog T1 (gleiche Deps, Import in `main.ts`, `--font`/`--font-mono` in `app.css`).
Verify: `cd apps/desktop/ui && npm run build` grün; computed font-family enthält „Geist".
Doku: keine (intern).

### T8 — Desktop: Token-Blöcke Dark + Light  [x] (wertgleich Web + desktop-Tokens erhalten)
Komponente: apps/desktop/ui · Dateien: src/styles/app.css
Änderung: `:root` auf DS-Dark-Werte (wertgleich zu Web-T2) + `:root[data-theme="light"]`
+ neue Tokens; **desktop-spezifische Tokens behalten** (`--bg-panel`, `--bg-input`,
`--sidebar-width`, `--header-height`). Nur Token-Block.
Verify: `cd apps/desktop/ui && npm run check && npm run test` grün; `npm run build` grün.
Doku: keine (intern).
Abhängt von: T7

### T9 — Desktop: Komponenten-Look in app.css  [x] (Pill/monochrome/Fokus-Ring/Card+Modal-Radien, wie Web-T3)
Komponente: apps/desktop/ui · Dateien: src/styles/app.css
Änderung: analog Web-T3 — Buttons/Inputs Pill, monochrome Primary, Cards/Panels
(16px) und Modals (28px), Status-Pills, Fokus-Ring; Aktiv-Nav gefüllt nur Farben.
Keine Layout-Regeln.
Verify: `npm run check && npm run build` grün; crabbox-GUI-Screenshot — kein Layout-Shift.
Doku: keine (intern).
Abhängt von: T8

### T10 — Desktop: theme-aware Scoped-Styles (Hex → Tokens)  [x] (tote Fallback-Hex entfernt, --error→--danger, --info→--accent)
Komponente: apps/desktop/ui · Dateien: src/components/StatusBar.svelte · NotificationBell.svelte · TunnelIndicator.svelte · components/infra/tabs/MonitoringTab.svelte (+ weitere mit Chrome-Hex)
Änderung: die ~32 hartkodierten Hex in Scoped-`<style>`-Blöcken auf Tokens
umstellen (Status → `--success`/`--warning`/`--danger`, Chrome → `--text*`/`--border`/
`--bg*`), damit Light-Mode kippt. Chart-Serienfarben bleiben T11.
Verify: `grep -rniE '#[0-9a-f]{3,8}' apps/desktop/ui/src --include='*.svelte'` nur noch bewusste Chart-/Fallback-Hex; `npm run test` grün.
Doku: keine (intern).
Abhängt von: T8

### T11 — Desktop: Monitoring-/Chart-Theming (uPlot)  [x] (Achsen/Grid aus Tokens + Re-Render on Toggle; Timeline→Tokens) — Abschluss: Serien #38bdf8/#ec4899 auf Weiß prüfen
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonChart.svelte · MonStatusTimeline.svelte · src/styles/app.css (uPlot-Overrides)
Änderung: uPlot Achsen/Grid/Serien + Timeline theme-adaptiv über Tokens statt fixer
Dark-Werte; Serien-Palette in beiden Themes lesbar halten (kein Neon/Pastel, DS-Regel).
Verify: crabbox-GUI: Monitoring-Charts in Dark **und** Light lesbar (Screenshot beider Themes); `npm run test` grün.
Doku: keine (intern).
Abhängt von: T8, T10

### T12 — Desktop: Theme-Store + Umschalter + Persistenz  [ ]
Komponente: apps/desktop/ui · Dateien: src/lib/stores/theme.ts (neu) · index.html · src/components/AppShell.svelte
Änderung: **FOUC-frei** — Inline-Script im `index.html`-`<head>` setzt `data-theme`
aus `localStorage['ah-theme']` vor dem ersten Paint. Store `theme.ts` (SPDX; Default
`dark`, aus `data-theme` initialisiert, schreibt Attribut + `localStorage`) —
**nicht** ins persistierte `Settings`-Contract (kein Rust-/Migration-Eingriff);
Toggle-Icon-Button im `AppShell`-Footer; i18n-Label. Neuer Flow ⇒ Test.
Verify: `apps/desktop/ui` vitest `theme.test.ts` grün; crabbox-GUI: Umschalten wirkt + überlebt Reload (Screenshot beider Themes).
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Theme-Umschalter) — selber Commit.
Abhängt von: T8

### T13 — Desktop: AdminCave-Brand-Mark  [ ]
Komponente: apps/desktop/ui · Dateien: public/logo.svg · src/components/AppShell.svelte · src/components/Login.svelte
Änderung: `logo.svg` durch AdminCave-Mark ersetzen; Wortmarken-Gewicht „Admin"(600)/
„Helper"(300); Mark via `currentColor`.
Verify: `npm run build` grün; Mark rendert in Dark + Light (crabbox-Screenshot).
Doku: keine (intern).
Abhängt von: T8

---

## Phase C — Doku & Abschluss

### T15 — Web+Desktop: generische Hover-Overlays theme-adaptiv  [ ]
Komponente: apps/web · apps/desktop/ui · Dateien: src/styles/global.css · src/styles/app.css (+ ggf. Scoped-Styles)
Änderung: die verbliebenen `rgba(255,255,255,.02–.06)`-Overlays (Nav-/Tabellen-Zeilen-/
Icon-Button-Hover, getönte `badge-read/-inactive`/`tag`-bg), die im Light-Mode nicht
kippen (weiß auf weiß = unsichtbar/invertiert). Ein neutrales `--hover`-Token (Dark:
`rgba(255,255,255,.05)`, Light: `rgba(0,0,0,.05)`) in beiden `:root`-Blöcken (web+desktop,
wertgleich) + betroffene Hover-Regeln darauf umstellen. Aufgetaucht im T3-Review als
Light-Mode-Kante (T3 adressierte laut Wortlaut nur die enumerierten Komponenten).
Verify: `npm run check && npm run build` (web+desktop) grün; Light-Screenshot: Row-/Nav-Hover sichtbar.
Doku: keine (intern).
Abhängt von: T3, T9

### T14 — Doku + CHANGELOG konsolidieren  [ ]
Komponente: docs · Dateien: docs/developer/webui.html · docs/developer/desktop.html · docs/en/developer/{webui,desktop}.html · CHANGELOG.md · (ggf. README.md)
Änderung: DS-Adoption + Light-Mode/Theme-Umschalter in beiden Entwickler-Doku-Seiten
(DE+EN) knapp beschreiben; `CHANGELOG.md` `## [Unreleased]` → `### Added`
(AdminCave-Design-System-Retheme, Light-Mode-Umschalter); optional 1 README-Zeile.
Prüfen, ob T5/T12 die Doku schon partiell gesetzt haben (Dopplung vermeiden).
Verify: DE+EN vorhanden & konsistent; `grep -ril 'theme\|design' docs/**/webui.html docs/**/desktop.html` trifft neue Abschnitte; interne Links valide.
Doku: (ist selbst die Doku).
Abhängt von: T5, T12

---

## Abschluss-Lauf (nach allen Tasks)
Fast-Suite lief pro Task auf crabbox. Vor dem Draft-PR die schwere Suite fahren:
`bash scripts/tests/run.sh e2e` (bzw. warm-Box `desktop`) mit `AH_ALLOW_REAL=1` —
GUI-E2E beider Frontends, Screenshots Dark **und** Light. Kein Multibox nötig (keine
Cross-Host-/PKI-/Install-Pfade berührt).
