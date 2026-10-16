<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Vertrauensdialog beim Erstkontakt sichtbar über dem Login — Task-Ledger
Status: aktiv · Branch: feature/desktop-trust-dialog · Review: am Ende
Spec: Roadmap R-0399
Heavy: linux-full — die Journey (Erstkontakt gegen das interne PKI-Leaf, Dialog in der echten Tauri-GUI) prüft nur `desktop_e2e_crud.sh` mit `enroll-trust-dialog.live.js` im Sammellauf (`run.sh e2e`); jsdom kennt kein Stacking, der Unit-Test belegt nur die Struktur
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Befund (origin/main@0f43781a): `.trust-overlay` (`Login.svelte:403-439`, `z-index: 60` in `:443-453`) ist Geschwister nach
`.login-screen` (`:241-401`); `.login-screen` ist `position: fixed`, `z-index: 300`, deckender Hintergrund
(`apps/desktop/ui/src/styles/app.css:1138-1146`). Beide liegen im Wurzel-Stacking-Kontext, der Login-Screen deckt den Dialog.
Die Live-Spec sieht es nicht: sie wartet nur auf Existenz und klickt per `jsClick` (umgeht den Hit-Test).
Vorbild für die Ebene: `ConfirmDialog` liegt seit R-0395 in `App.svelte` in `.confirm-layer` (`z-index: 310`).

### T1 — Login: der Vertrauensdialog liegt über dem Login-Screen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/Login.trust.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @8ba6b908 2026-10-16T15:36:09+02:00
Review: am Ende (Branch-Review)
Änderung: Den Trust-Dialog in den Stacking-Kontext des Login-Screens holen: den `{#if trustPrompt}`-Block (`Login.svelte:403-439`) als letztes Kind in `.login-screen` (`:241`) verschieben, sodass sein `z-index: 60` innerhalb der Ebene 300 über `.login-card` liegt (Alternative, falls das Layout bricht: `.trust-overlay` auf eine Ebene über 300 heben wie `.confirm-layer` in `App.svelte`, mit Kommentar fürs Warum). Test zuerst rot in `Login.trust.test.ts` (Beschreibung „the trust dialog lies in the login screen layer“): nach `submitEnroll` mit `UNKNOWN_ISSUER` ist `container.querySelector('.login-screen [data-testid="trust-dialog"]')` nicht null; die bestehenden Trust-Tests (`:71` ff.) bleiben grün. CHANGELOG unter `[Unreleased]` → `### Fixed`: der Vertrauensdialog beim ersten Kontakt war vom Login-Screen verdeckt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Login.trust.test.ts
Doku: CHANGELOG.md (Fixed); keine Doku-Änderung, das Verhalten stand schon so in docs/admin/troubleshooting.html:71
Beweis: origin/main@0f43781a · `Login.svelte:403-439` (Overlay Geschwister nach `.login-screen` `:241-401`), `:450` `z-index: 60`; `styles/app.css:1138-1146` `.login-screen` fixed, `z-index: 300`, `background: var(--bg)`; Builder-Probe R-0395 T1 (headless Firefox, Dialog verdeckt) — in der echten App nicht geprüft
Orakel: contract — der Strukturtest legt fest, dass der Dialog in der Ebene des Login-Screens liegt; die echte Stapelung belegt T2 live
Dedup-Key: bug:desktop:Login.svelte:trust-overlay-zindex
HEAD: 0f43781a
Semantik: docs/admin/troubleshooting.html:71 — „der allererste Login- bzw. Enrollment-Versuch mit Standard-Einstellungen öffnet deshalb einen Dialog, ob dem Server dennoch vertraut werden soll“

### T2 — Live-Spec: der Vertrauensdialog ist wirklich sichtbar und anklickbar  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/enroll-trust-dialog.live.js
Änderung: Nach `waitForExist` des Dialogs (`enroll-trust-dialog.live.js:27`) prüft die Spec per `browser.execute`, dass `document.elementFromPoint` am Mittelpunkt des Knopfs `[data-action="trust-accept"]` diesen Knopf (oder ein Kind) liefert, sonst Fehler mit klarer Meldung („trust dialog covered by …“ mit der Klasse des getroffenen Elements); dazu `isDisplayed()`. Der Klick (`:35-37`) bleibt `jsClick`, der Kommentar wird richtiggestellt (der Hit-Test scheiterte am verdeckenden Login-Screen, nicht an der Statusleiste — die gibt es vor dem Login nicht). Ohne T1 ist die neue Prüfung in der echten GUI rot (Beleg im Heavy-Lauf).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T1
Beweis: origin/main@0f43781a · `enroll-trust-dialog.live.js:27` nur `waitForExist`, `:35-37` `jsClick` mit dem Kommentar zum abgelehnten Hit-Test; `apps/desktop/e2e/test/lib/live.js:238-240` begründet `jsClick` mit der Statusleiste, die auf dem Login-Screen nicht gerendert ist
Dedup-Key: bug:desktop:Login.svelte:trust-overlay-zindex
HEAD: 0f43781a
Semantik: docs/admin/troubleshooting.html:71 (wie T1)
