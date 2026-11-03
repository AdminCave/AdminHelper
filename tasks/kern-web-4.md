<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-web-4 — Task-Ledger
Status: bereit · Branch: feature/kern-web-4 · Review: pro Task
Spec: docs/features/kern-web-4.md (Roadmap R-1082)
Heavy: linux-full — das Web-Panel läuft im Sammellauf gegen den echten Stack (web-live, Playwright)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage: Desktop-Bibliothek `apps/desktop/ui/src/components/ui/` und Tokens `apps/desktop/ui/src/styles/app.css` (nach `AdminCave/DesignSystem@244e890`). Stand `origin/main@4d1ad071`. Jede Task entfernt die globalen Klassen, die sie verwaist, und hält die Anker der Playwright-Specs (`apps/web/tests/e2e/*.spec.ts`, `apps/web/tests/live/smoke.live.spec.ts`) oder zieht sie in derselben Task nach.

### T1 — Tokens auf DS-Stand (R-1082)  [x]
Komponente: web · Dateien: apps/web/src/styles/global.css, apps/web/src/styles/tokens.test.ts, apps/web/src/theme-init.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @ca69efa0 2026-11-03T01:36:16+01:00
Review: approve (.ah-out/review/kern-web-4/T1.verdict.json)
Änderung: Die Token-Blöcke in `global.css` (dunkel und `[data-theme='light']`) bekommen Werte und Namen wie die Desktop-Tokens: soft black, `surface`/`raised`/`inset`, Status-Paare `--*-bg`/`--*-border`, Radien, Motion, `--ring-shadow`. Die alten Namen bleiben als Aliase. Neuer `tokens.test.ts` prüft Namen in beiden Themes, Aliase und reduzierte Bewegung wie `apps/desktop/ui/src/styles/tokens.test.ts`. SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh web --strict -- src/styles/tokens.test.ts src/theme-init.test.ts
Doku: → T9

### T2 — Bibliothek: Kopie der Desktop-Bausteine (R-1082)  [x]
Komponente: web · Dateien: apps/web/package.json, apps/web/package-lock.json, THIRD_PARTY_LICENSES.md, apps/web/src/lib/components/ui/Button.svelte, apps/web/src/lib/components/ui/IconButton.svelte, apps/web/src/lib/components/ui/Pill.svelte, apps/web/src/lib/components/ui/Tag.svelte, apps/web/src/lib/components/ui/Dot.svelte, apps/web/src/lib/components/ui/Panel.svelte, apps/web/src/lib/components/ui/EmptyState.svelte, apps/web/src/lib/components/ui/Spinner.svelte, apps/web/src/lib/components/ui/Input.svelte, apps/web/src/lib/components/ui/Select.svelte, apps/web/src/lib/components/ui/FormField.svelte, apps/web/src/lib/components/ui/field.ts, apps/web/src/lib/components/ui/Checkbox.svelte, apps/web/src/lib/components/ui/Switch.svelte, apps/web/src/lib/components/ui/SearchField.svelte, apps/web/src/lib/components/ui/Modal.svelte, apps/web/src/lib/components/ui/ConfirmDialog.svelte, apps/web/src/lib/components/ui/Toast.svelte, apps/web/src/lib/components/ui/primitives.test.ts, apps/web/src/lib/components/ui/forms.test.ts, apps/web/src/lib/components/ui/core.test.ts, apps/web/src/lib/components/ui/ConfirmDialog.test.ts, apps/web/src/lib/components/ui/Kbd.svelte, apps/web/src/lib/components/ui/__fixtures__/TestIcon.svelte, apps/web/src/lib/components/ui/__fixtures__/FieldWiringHarness.svelte, apps/web/src/lib/components/ui/__fixtures__/FormsHarness.svelte, apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/styles/global.css, apps/web/src/modals/FrpConfigModal.test.ts, apps/web/tests/e2e/crud.spec.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @8359fbeb 2026-11-03T01:47:27+01:00
Review: approve (.ah-out/review/kern-web-4/T2.verdict.json)
Änderung: `@lucide/svelte` 1.66.0 als Abhängigkeit, `THIRD_PARTY_LICENSES.md` nennt das Web mit. Die Bausteine aus der Spec als eigene Kopie der Desktop-Fassung, Texte über die Props statt über das Desktop-i18n; `Modal` mit Anfangsfokus, Fokusfalle und `aria-labelledby`. Die Tests kommen aus `primitives.test.ts`, `forms.test.ts` und `core.test.ts` des Desktops, gekürzt auf die kopierten Bausteine. Mehr als acht Dateien, weil es eine Kopie mit ihren Tests ist und nur gemeinsam Sinn hat. SPDX in den neuen Dateien.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/components/ui
Doku: → T9
Abhängt von: T1

### T3 — Shell und Login (R-1082)  [x]
Komponente: web · Dateien: apps/web/src/lib/components/layout/Sidebar.svelte, apps/web/src/lib/components/layout/Sidebar.test.ts, apps/web/src/App.svelte, apps/web/src/pages/Login.svelte, apps/web/src/pages/Login.test.ts, apps/web/src/styles/global.css, apps/web/tests/e2e/smoke.spec.ts, apps/web/tests/e2e/theme.spec.ts, apps/web/tests/e2e/login.spec.ts, apps/web/index.html, apps/web/src/lib/stores/theme.ts, apps/web/src/lib/components/ui/Input.svelte
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @8b3ba5f7 2026-11-03T01:53:19+01:00
Review: approve (.ah-out/review/kern-web-4/T3.verdict.json)
Änderung: Sidebar wie im Desktop: Lucide-Icons statt der Inline-SVGs, aktiver Eintrag fett mit Balken, Theme-Umschalter, Benutzer und Abmelden als `IconButton`. Login auf `Panel`, `FormField`, `Input`, `Button`, Logo-SVG raus. Neue Tests für Sidebar (aktiver Eintrag, Abmelden, Theme) und Login (Fehler, Absenden). SPDX in den neuen Tests.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/components/layout/Sidebar.test.ts src/pages/Login.test.ts src/App.idle.test.ts src/mount.smoke.test.ts
Doku: → T9
Abhängt von: T2

### T4 — Seiten Benutzer, API-Keys, Zertifikate (R-1082)  [x]
Komponente: web · Dateien: apps/web/src/pages/Users.svelte, apps/web/src/pages/Users.test.ts, apps/web/src/pages/ApiKeys.svelte, apps/web/src/pages/ApiKeys.test.ts, apps/web/src/pages/Certificates.svelte, apps/web/src/pages/Certificates.test.ts, apps/web/src/styles/global.css, apps/web/tests/e2e/crud.spec.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @18720823 2026-11-03T01:58:36+01:00
Review: approve (.ah-out/review/kern-web-4/T4.verdict.json)
Änderung: Kopf mit Titel und Aktion, Tabelle im `Panel`, Rollen und Zustände als `Pill`, Zeilenaktionen als `Button`/`IconButton` mit den bisherigen zugänglichen Namen, leere Zustände über `EmptyState`. Neue Seitentests für Users und ApiKeys (Laden, leere Liste, Aktion öffnet den Dialog). SPDX in den neuen Tests.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Users.test.ts src/pages/ApiKeys.test.ts src/pages/Certificates.test.ts src/pages.load.test.ts
Doku: → T9
Abhängt von: T2

### T5 — Seiten Audit, Hooks, FRP (R-1082)  [x]
Komponente: web · Dateien: apps/web/src/pages/Audit.svelte, apps/web/src/pages/Audit.test.ts, apps/web/src/pages/Hooks.svelte, apps/web/src/pages/Hooks.test.ts, apps/web/src/pages/Frp.svelte, apps/web/src/pages/Frp.test.ts, apps/web/src/pages/Frp.preview.test.ts, apps/web/src/pages/Placeholder.svelte, apps/web/src/styles/global.css, apps/web/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @cf1ca016 2026-11-03T02:09:28+01:00
Review: approve (.ah-out/review/kern-web-4/T5.verdict.json)
Änderung: Wie T4: Audit mit `SearchField` und Filtern aus der Bibliothek, Hooks mit `Switch` für aktiv und `Pill` für das Ergebnis, FRP mit `Panel`-Abschnitten. Neuer Seitentest für Hooks. SPDX im neuen Test.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Audit.test.ts src/pages/Hooks.test.ts src/pages/Frp.test.ts src/pages/Frp.preview.test.ts src/pages/Placeholder.test.ts
Doku: → T9
Abhängt von: T2

### T6 — Dialoge Benutzer, API-Key, Registrierung, Webhook (R-1082)  [x]
Komponente: web · Dateien: apps/web/src/modals/UserModal.svelte, apps/web/src/modals/UserModal.test.ts, apps/web/src/modals/ApiKeyModal.svelte, apps/web/src/modals/KeyRevealModal.svelte, apps/web/src/modals/EnrollTokenModal.svelte, apps/web/src/modals/EnrollTokenModal.test.ts, apps/web/src/modals/WebhookTokenModal.svelte, apps/web/src/modals/copyButtons.test.ts, apps/web/src/styles/global.css
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @bcc45ad5 2026-11-03T02:14:33+01:00
Review: approve (.ah-out/review/kern-web-4/T6.verdict.json)
Änderung: Auf `Modal`, `FormField`, `Input`, `Select`, `Checkbox` und `Button`; Feld-IDs (`#ufUsername`, `#akName`, `#etTtl`) und `.key-reveal` bleiben. Kopier-Knöpfe als `IconButton` mit Namen.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/UserModal.test.ts src/modals/EnrollTokenModal.test.ts src/modals/copyButtons.test.ts
Doku: → T9
Abhängt von: T2

### T7 — Dialoge Hook und FRP (R-1082)  [x]
Komponente: web · Dateien: apps/web/src/modals/HookModal.svelte, apps/web/src/modals/HookModal.test.ts, apps/web/src/modals/HookRunResultModal.svelte, apps/web/src/modals/FrpConfigModal.svelte, apps/web/src/modals/FrpConfigModal.test.ts, apps/web/src/modals/FrpConfigPreviewModal.svelte, apps/web/src/modals/FrpStatusModal.svelte, apps/web/src/styles/global.css, apps/web/src/modals/copyButtons.test.ts, apps/web/src/modals/ApiKeyModal.test.ts, apps/web/src/styles/tokens.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @dfb39c04 2026-11-03T02:23:55+01:00
Review: approve (.ah-out/review/kern-web-4/T7.verdict.json)
Änderung: Wie T6; `#frp-config-form` bleibt. Danach trägt `global.css` keine verwaisten Klassen und keine Alias-Token mehr, die keine Regel nutzt.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/HookModal.test.ts src/modals/FrpConfigModal.test.ts src/styles/tokens.test.ts src/modals/copyButtons.test.ts src/modals/ApiKeyModal.test.ts
Doku: → T9
Abhängt von: T2

### T8 — Visuelle Baselines neu (R-1082)  [x]
Komponente: web · Dateien: apps/web/tests/e2e/login.spec.ts-snapshots/login-chromium-linux.png, apps/web/tests/e2e/smoke.spec.ts-snapshots/users-chromium-linux.png, apps/web/tests/e2e/smoke.spec.ts-snapshots/apikeys-chromium-linux.png, apps/web/tests/e2e/smoke.spec.ts-snapshots/certificates-chromium-linux.png, apps/web/tests/e2e/smoke.spec.ts-snapshots/audit-chromium-linux.png, apps/web/tests/e2e/smoke.spec.ts-snapshots/hooks-chromium-linux.png, apps/web/tests/e2e/smoke.spec.ts-snapshots/frp-chromium-linux.png
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @d393e961 2026-11-03T02:29:34+01:00
Review: approve (.ah-out/review/kern-web-4/T8.verdict.json)
Änderung: Die sieben `toHaveScreenshot`-Baselines (`login.spec.ts:61`, `smoke.spec.ts:58`) neu erzeugen, mit `npm run test:e2e:update` im offiziellen Playwright-Container in der Version aus `package-lock.json` (die Dev-Box hat keine Browser-Abhängigkeiten). Vorher die Bilder ansehen. Den Beweis liefert die PR-CI (`frontend-e2e`); weicht das Rendering des Containers von `ubuntu-latest` ab, kommen die Baselines aus dem `playwright-report`-Artefakt des roten Laufs, und das steht unter `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh web --strict -- src/mount.smoke.test.ts
Doku: keine (Testdaten)
Abhängt von: T3, T4, T5, T6, T7

### T9 — Doku DE+EN und Changelog (R-1082)  [x]
Komponente: web · Dateien: docs/developer/webui.html, docs/en/developer/webui.html, changelog.d/kern-web-4.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @16bafbb8 2026-11-03T02:30:21+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Entwickler-Doku Web-UI: Tokens nach DS-Stand, Bibliothek unter `lib/components/ui/` als Kopie der Desktop-Bausteine, Lucide; Changelog-Fragment.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh web --strict -- src/styles/tokens.test.ts
Doku: diese Task

## Entscheidungen
- T2: Texte der Bausteine über das Web-i18n (`$lib/i18n`, Keys `ui.search`/`ui.clear`/`ui.select` neu, Spinner nutzt `state.loading`, Modal-Schließen `action.close`) statt über Props: gleiche Gestalt wie die Desktop-Kopie, keine Prop-Durchreichung in jeder Seite.
- T2: `ConfirmDialog` behält das Web-Verhalten (Sitzungsbindung, Escape per Capture-Listener) und bekommt nur die neuen `Button`-Varianten; `Toast` bleibt der Web-Stapel (`.toast-stack .toast.<kind>`, Klick schließt) im Look des Desktop-Toasts.
- T2: `Kbd` kommt mit, weil `SearchField` ihn für `shortcut` nutzt. `@lucide/svelte` als `devDependency` wie alle Web-Pakete; `THIRD_PARTY_LICENSES.md` nennt es, weil die Icons im Bundle landen.
- T2: Desktop-Tests gekürzt um `Badge`, `RadioGroup`, `Slider` (nicht kopiert); `primitives.test.ts` hydriert eine Sitzung wie `ConfirmDialog.test.ts`.
- T2: E2E `crud.spec.ts:68/104` wählen „Schließen“ über `.modal-footer`: der Modal-Kopf trägt jetzt einen gleichnamigen `IconButton` (Prüfer-Blocker Runde 1).
- T3: Das Logo bleibt als SVG in Sidebar und Login wie im Desktop (Marke, kein Lucide-Icon); raus sind die Icon-Pfade. `Input` bekommt `required` (Login-Felder hatten es nativ). Die Klasse `login-form` bleibt (Anker in `App.idle.test.ts`), dazu `.login-card`, `.login-error`, `#loginUser`, `#loginPass`. `theme-color` folgt dem neuen Dunkel `#17181b` (Nit aus T1). `theme.spec.ts` prüft den Hintergrund `rgb(23, 24, 27)` statt True-Black.
- T4: Die globale Regel `.panel` gilt nur noch für `div.panel`: das `section.panel` der Komponente bekam sonst ihr Polster und ihren Schatten zusätzlich (traf schon das Login aus T3); T7 entfernt sie, sobald T5 die letzten `div.panel` ablöst. Löschen ist ein `IconButton` (Trash) mit dem Namen „Löschen“, Bearbeiten und Registrierungs-Token bleiben Text-Buttons. Zertifikate: der Zustand steht als `data-status` an der Zelle (der Test prüfte vorher die Klasse `.light`), Rollen und Rechte als `Pill`.
- T5: Hooks schaltet aktiv über einen `Switch` (Name „Aktiv“) statt über die Buttons Aktivieren/Deaktivieren; die verwaisten Keys `action.enable`, `action.disable`, `page.hooks.inactive` gehen raus (`i18n.test.ts` verlangt benutzte Keys), daher `dictionaries.ts` in T5. Scheitert das Umschalten, rendert `{#key}` den Switch neu, damit er wieder den Serverstand zeigt (er schaltet beim Klick selbst um). Audit: „Alle Actors“ ist der Wert `all`, weil `Select` für '' eine deaktivierte Platzhalter-Option zeigt; `load` schickt dafür keinen Filter. `global.css` bleibt in T5 unberührt, das Aufräumen macht T7.
- T6: Kopieren ist ein `IconButton` (Copy, Name „Kopieren“) neben dem Wert in `.reveal`, die Fußzeile schließt nur noch; `.key-reveal` nutzt `--success-bg`/`--success-border` statt fester Farben. Die Formulare nutzen eine eigene Klasse `form` statt `modal-form`, weil die globalen `.modal-form input/select`-Regeln die Bibliotheks-Felder überzeichnen würden (HookModal und FrpConfigModal brauchen sie bis T7). Select bindet Strings: TTL als `'10'`… mit `Number()` beim Senden, Permission mit Cast auf `ApiKeyPermission`. Der global.css-Hunk dieser Task (`.reveal`, `.key-reveal`) ging versehentlich mit dem T5-Commit bcc45ad5 (global.css stand in T5s `Dateien:`); der T6-Prüfer prüft ihn mit.
- T7: Die Bind-Port-Warnung ist der `hint` von FormField, das ihn per `aria-describedby` an das Feld hängt; das `data-testid` fällt weg (nur der Unit-Test nutzte es), der Test findet die Warnung über `aria-describedby` und prüft, dass sie im selben Feld steht. Die Port-Felder halten Strings; Svelte liest ein Zahlenfeld als Zahl bzw. leer als null zurück, `num()` nimmt alle drei. Die FRP-Vorschau trägt den Kopier-`IconButton` oben rechts auf dem Konfigtext. Aus `global.css` gehen die Regeln ohne Nutzer (`.btn*`, `div.panel`, `.badge*`, `.tag`, `.field*`, `.checkbox-label`, `.modal-form*`, `.status*`, `.server-card-body`, `.monitor-tab*`, `.check-detail-periods`) und die Alias-Token ohne `var()`-Nutzer (`--bg-surface`, `--bg-elevated`, `--bg-sidebar`, `--text-faint`, `--accent-bg`, `--shadow`, `--sp-1`); `.empty-state` bleibt, weil `EmptyState` die Klasse trägt. Neu `ApiKeyModal.test.ts` (Nit des T6-Prüfers: die gewählte Permission geht an `apikeys.create`, Gegenprobe rot).
- T8: Die Baselines entstehen im Container `mcr.microsoft.com/playwright:v1.60.0-noble` (Version aus `package-lock.json`) mit `npx playwright test --update-snapshots=all login.spec.ts smoke.spec.ts` (15 passed): ohne `=all` schreibt Playwright nur Bilder neu, die die Toleranz überschreiten, und sechs blieben alt. Alle sieben angesehen. Den Beweis gegen `ubuntu-latest` liefert die PR-CI `frontend-e2e`; weicht sie ab, kommen die Baselines aus ihrem `playwright-report`-Artefakt.
