<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-design-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-design-1 · Review: pro Task
Spec: docs/features/kern-design-1.md (Roadmap R-1061)
Heavy: linux-full — Token-Wechsel und Icons in AppShell, Login und Connections ändern das DOM der Desktop-Journeys; der Sammellauf fährt die GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890`: `tokens/*.css`, `components/*/*.d.ts` (Verträge), `ui_kits/adminhelper/kit.jsx` (Pill, Dot, Segmented, Panel, MetaList). Zeilenangaben `origin/main@1c313156`. Alle Pfade unter `apps/desktop/ui/`, soweit nicht anders genannt. Svelte 5 (Runes), TypeScript strict ohne `any`; Snippet statt ReactNode, Icons als Lucide-Komponente.

### T1 — DS-Tokens in app.css, alte Namen als Aliase (R-1061)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/styles/app.css, apps/desktop/ui/src/styles/tokens.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0062ae35 2026-11-02T16:36:10+01:00
Review: approve (.ah-out/review/kern-design-1/T1.verdict.json)
Änderung: `:root` und `:root[data-theme='light']` (`src/styles/app.css:1-125`) auf DS-Stand: Farben aus `tokens/colors.css` (`--bg` #17181b, `--bg-subtle`, `--surface`, `--surface-raised`, `--surface-inset`, `--surface-hover`/`-active`, `--border`/`-strong`/`-faint`, `--text`/`-strong`/`-muted`/`-subtle`/`-inverse`, Akzent, `--fill-solid*`, Status mit `-bg`/`-border`, `--ring`), Radius, Schatten (dark und light), Motion (`--dur-*`, `--ease-*`), `--ring-shadow`, Spacing `--space-*`. Die bisherigen AH-Namen (`--bg-surface`, `--bg-elevated`, `--bg-sidebar`, `--bg-panel`, `--bg-input`, `--border-hover`, `--hover`, `--text-faint`, `--accent-bg`, `--green`, `--sp-*`, `--shadow`) werden `var()`-Aliase auf DS-Namen. Basisregeln: `:focus-visible` mit `--ring-shadow`, `prefers-reduced-motion` setzt die Dauern auf 0. Neuer Test liest `app.css` und prüft, dass jeder DS-Token in beiden Blöcken steht und jeder Alt-Name auf einen definierten Namen zeigt (gegen Tippfehler, die sonst still auf den Browser-Default fallen).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/styles/tokens.test.ts
Doku: → T8

### T2 — Lucide statt Inline-SVG (R-1061)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/NotificationBell.svelte, apps/desktop/ui/src/components/Picker.svelte, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/components/monitoring/section/MonSectionIcon.svelte, THIRD_PARTY_LICENSES.md
Änderung: `@lucide/svelte` als Abhängigkeit (Version und Import-Form vorher auf lucide.dev nachlesen); die Symbol-SVGs der genannten Dateien durch Lucide-Komponenten ersetzen, Klassen und `aria-*` bleiben, damit Tests und E2E-Selektoren tragen. Grafiken (Sparkline in `MonSparkline.svelte`, Ring in `SecLive.svelte`) bleiben SVG. Lizenz in `THIRD_PARTY_LICENSES.md`. Mehr als acht Dateien: die Abhängigkeit und ihre Nutzer sind nur gemeinsam baubar. `package.json`/Lockfile ändert auch `feature/kern-laufzeit-1` (`@types/node`): diese Task baut nach dessen Merge, sonst nach T1 und T3–T7 mit `origin/main` hineingemergt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.notifications.test.ts src/components/AppShell.workspace.test.ts src/components/Picker.test.ts src/components/Login.dialog.test.ts src/mount.smoke.test.ts
Doku: → T8

### T3 — Kernkomponenten: Button, IconButton, Tag, Badge, Pill, Dot, Kbd, Spinner, Panel (R-1061)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ui/Button.svelte, apps/desktop/ui/src/components/ui/IconButton.svelte, apps/desktop/ui/src/components/ui/Tag.svelte, apps/desktop/ui/src/components/ui/Badge.svelte, apps/desktop/ui/src/components/ui/Pill.svelte, apps/desktop/ui/src/components/ui/Dot.svelte, apps/desktop/ui/src/components/ui/Kbd.svelte, apps/desktop/ui/src/components/ui/Spinner.svelte, apps/desktop/ui/src/components/ui/Panel.svelte, apps/desktop/ui/src/components/ui/core.test.ts
Änderung: Neun Komponenten nach den Verträgen in `components/core/*.d.ts` (Pill, Dot, Panel nach `kit.jsx`): Varianten, Größen, Töne als Props, Pill-Radius, Press-Scale, `loading` sperrt den Button, IconButton verlangt `label` (aria-label). Ein Test je Komponente (Rendern, Varianten-Klasse, Ereignisse, Sperren, aria). SPDX-Header in jeder neuen Datei. Zehn Dateien: neun kleine Komponenten mit einem gemeinsamen Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ui/core.test.ts
Doku: → T8
Abhängt von: T1

### T4 — Formulare: Input, SearchField, Select, Switch, Checkbox, RadioGroup, Slider, FormField (R-1061)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ui/Input.svelte, apps/desktop/ui/src/components/ui/SearchField.svelte, apps/desktop/ui/src/components/ui/Select.svelte, apps/desktop/ui/src/components/ui/Switch.svelte, apps/desktop/ui/src/components/ui/Checkbox.svelte, apps/desktop/ui/src/components/ui/RadioGroup.svelte, apps/desktop/ui/src/components/ui/Slider.svelte, apps/desktop/ui/src/components/ui/FormField.svelte, apps/desktop/ui/src/components/ui/forms.test.ts
Änderung: Acht Formular-Komponenten nach `components/forms/*.d.ts`, als Svelte-`bind:value`/`bind:checked` statt `onChange`-Paar; native Elemente darunter (Tastatur und Formular-Submit wie gewohnt), FormField verknüpft Label, Hinweis und Fehler per `for`/`aria-describedby`/`aria-invalid`; SearchField mit Löschen-Knopf und Kürzel-Anzeige. Tests: Bindung, Tastatur (Space/Pfeile), aria-Verknüpfung, `disabled`. SPDX-Header.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ui/forms.test.ts
Doku: → T8
Abhängt von: T1

### T5 — Navigation und Überlagerungen: Tabs, Segmented, Menu, Tooltip, Toast (R-1061)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ui/Tabs.svelte, apps/desktop/ui/src/components/ui/Segmented.svelte, apps/desktop/ui/src/components/ui/Menu.svelte, apps/desktop/ui/src/components/ui/Tooltip.svelte, apps/desktop/ui/src/components/ui/Toast.svelte, apps/desktop/ui/src/components/ui/nav.test.ts
Änderung: Tabs (aktiv = Gewicht + Balken, `role=tablist`, Pfeiltasten), Segmented (`role=radiogroup`), Menu (Auslöser-Snippet, Pfeiltasten, Escape, Klick außerhalb schließt, Fokus zurück an den Auslöser), Tooltip (bei Hover und Fokus, `aria-describedby`), Toast (Ton, Aktion, Schließen; der Stapel kommt mit R-1062). Tests für Tastatur, Rollen und Schließen. SPDX-Header.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ui/nav.test.ts
Doku: → T8
Abhängt von: T1

### T6 — Dialog: Modal mit Anfangsfokus, Fokusfalle und aria (R-1061, R-0714 Teil)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ui/Modal.svelte, apps/desktop/ui/src/components/ui/primitives.test.ts
Änderung: `Modal.svelte` erfüllt den DS-Dialog-Vertrag (`components/feedback/Dialog.d.ts`) als Obermenge seiner heutigen Props (`open`, `title`, `width`, `onClose`, `children`, `footer`; neu `description`): beim Öffnen Fokus auf das erste fokussierbare Element (sonst das Panel), Tab/Shift+Tab bleiben im obersten Dialog des `modalStack`, beim Schließen Fokus zurück an das vorher fokussierte Element, `role=dialog`, `aria-modal`, `aria-labelledby`/`aria-describedby`, DS-Optik (Scrim mit Blur, `--radius-2xl`, Fade + 8px). Tests neu: Anfangsfokus, Falle vorwärts und rückwärts, Fokus-Rückgabe, gestapelter ConfirmDialog fängt nur oben; die bestehenden Modal-Tests bleiben unverändert grün.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ui/primitives.test.ts src/components/WorkspaceEditor.test.ts src/components/SettingsModal.dialog.test.ts
Doku: → T8
Abhängt von: T1

### T7 — Daten und Rückmeldung: Callout, EmptyState, Skeleton, CodeBlock, MetaList (R-1061)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ui/Callout.svelte, apps/desktop/ui/src/components/ui/EmptyState.svelte, apps/desktop/ui/src/components/ui/Skeleton.svelte, apps/desktop/ui/src/components/ui/CodeBlock.svelte, apps/desktop/ui/src/components/ui/MetaList.svelte, apps/desktop/ui/src/components/ui/data.test.ts
Änderung: Callout (Ton, Titel, Icon, Aktion), EmptyState auf DS-Vertrag erweitert (Icon, Titel, Beschreibung, `framed`; die heutigen Props bleiben, `primitives.test.ts` bleibt grün), Skeleton (`count`, `circle`, `aria-hidden`), CodeBlock (Dateiname, Kopieren über `navigator.clipboard` mit Rückmeldung), MetaList (Schlüssel/Wert-Zeilen, Werte in Mono). Tests je Komponente. SPDX-Header.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ui/data.test.ts src/components/ui/primitives.test.ts
Doku: → T8
Abhängt von: T1

### T8 — Doku: Design-System im Desktop, Changelog (R-1061)  [ ]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-design-1.md
Änderung: Abschnitt Design-System (`docs/developer/desktop.html:278` und EN-Gegenstück) auf den neuen Stand: soft black statt True-Black, DS-Token-Namen samt Alt-Aliasen, Lucide, `components/ui` als Bibliothek mit Liste und Regel „neue Seiten nehmen sie“; der Satz „wertgleich zum Web-Panel“ entfällt. Changelog-Fragment (Changed: Desktop-Design-Fundament; umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-design-1.md
Task-Review: am Ende

## Entscheidungen
- T1: Alias-Zuordnung: `--bg-surface`→`--surface`, `--bg-elevated`/`--bg-panel`→`--surface-raised`, `--bg-sidebar`→`--bg-subtle`, `--bg-input`→`--surface-inset`, `--shadow`→`--shadow-md`, `--sp-5/6/7`→`--space-6/8/12` (wertgleich zu den alten 24/32/48 px). Fokus-Ring als `:where(:focus-visible)` (Spezifität 0), damit die bestehenden `:focus-visible`-Regeln der Seiten weiter gelten; gezeichnet als `outline` mit `--ring-width`/`--ring` statt `--ring-shadow`, weil Klassen mit eigenem `box-shadow` (`.ws-swatch.selected`) den Ring sonst verdecken (Reviewer T1). Die undefinierten Altnamen `--bg-elev`, `--radius`, `--bg-hover`, `--bg-accent` (Ansible, NotificationBell) bleiben unberührt, Roadmap-Zeile.
