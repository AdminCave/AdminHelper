<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Kleinpaket 4: keine ERR_*-Codes in Fehleranzeigen im Fenster — Task-Ledger
Status: aktiv · Branch: feature/desktop-kleinpaket-4 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-10 (kleines Fund-Paket aus R-0261, von Kevin am 2026-10-10 in der Triage angenommen; Delegation Kevin 2026-10-05). Offene Frage (Aufsicht): 1 Weg (a), der Filter an den drei Stellen; (b) zentral in errMsg ist eine eigene Roadmap-Zeile mit den Pin-Tests als erstem Schritt
Spec: Roadmap R-0261 (Kurz-Ledger ohne Spec)
Heavy: none — ein Textfilter an drei Fehleranzeigen der Desktop-UI (`desktop-ui`); kein Stack-, Gateway-, PKI- oder Install-Pfad, keine Live-Spec liest diese Anzeigen, die Komponenten- und Store-Tests decken die Wege ab.
DoD je Task: CLAUDE.md (Tests grün, svelte-check, ESLint und Prettier sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-10 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin triagiert hat. Sie
stammt aus dem Plan von R-0248 (#108). Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt
von der Aufsicht. Zeilenangaben origin/main@8fb8f648.

Bestand. Alle Stellen der Desktop-UI, die `errMsg(err)` oder einen daraus gebauten Text zeigen, ohne über
`reportError` zu gehen (der filtert seit R-0248):
- `NotificationPrefs.svelte:91` und `:138` setzen `errorMsg = errMsg(err)`; `:223` zeigt ihn. → T1.
- `stores/ansible.ts:80-81` legt den Text als `loadError` ab; `pages/Ansible.svelte:64` zeigt ihn als „Fehler:
  {message}“. → T2.
- `stores/monitoring.ts:238-246` legt den Text als `error` ab; `MonitoringOverview.svelte:80` zeigt ihn als „Monitoring:
  {message}“. → T2.
- `ExpandChart.svelte:45` aus der Roadmap-Zeile zeigt den Text nicht: `error` ist dort nur ein Schalter, angezeigt wird
  der feste Text `monitoring.detail.error` („Fehler beim Laden“, `:79-80`). Kein Fix.
- Schon ohne Code: `Login.svelte` (`displayError`, `:59`), die Registrierung in `SettingsModal.svelte:159` (R-0243). Der
  Fehler der Verbindungsliste geht über `reportError` (`stores/settings.ts:55`). `MonitoringLog.svelte:29` zeigt den
  Fehler eines Alert-Eintrags vom Server, keinen Fehler der App.
- Die Codes liest nur der Login (`Login.svelte:52-57`, `:137`). Er muss sie weiter im eigenen Fehlertext sehen.

Der Plan folgt der Empfehlung zu offener Frage 1, Weg (a): `withoutErrorCodes` an den drei Stellen, wie R-0243 und
R-0248.

### T1 — Benachrichtigungen: die Fehleranzeige zeigt die Meldung ohne die Maschinen-Codes (R-0261)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationPrefs.svelte, apps/desktop/ui/src/components/NotificationPrefs.test.ts, CHANGELOG.md
Änderung: `NotificationPrefs.svelte` setzt bei einem Fehler beim Laden (`:91`) und beim Speichern (`:138`) `errorMsg =
errMsg(err)`. Ein Netzwerkfehler aus dem Backend trägt die Codes in seiner Quellenkette (`AppError::Network`,
`error.rs`), etwa `ERR_TOFU_PIN_MISMATCH` nach einem Zertifikatswechsel am Server. Künftig `errorMsg =
withoutErrorCodes(errMsg(err))`, wie in `SettingsModal.svelte:159`.

Tests in `NotificationPrefs.test.ts`, neben dem bestehenden Round-Trip-Test, mit den Mocks von dort:
- `fetchPrefs` lehnt mit einer Netzwerk-Kette samt `ERR_TOFU_PIN_MISMATCH` ab: `.np-err` zeigt die Prosa vollständig,
  ohne `ERR_`.
- Ebenso `savePrefs` nach erfolgreichem Laden.
- Rot vor dem Fix.

CHANGELOG unter `[Unreleased]` → `### Fixed`, ein Eintrag, den T2 erweitert.
Beweis: origin/main@8fb8f648, Probe-Test (nicht committet, danach gelöscht) mit der echten Komponente, nur
`notificationsApi`, `monitoringApi` und die Session gemockt. `fetchPrefs` lehnt mit `error sending request for url
(https://t/api/x): client error (Connect): ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für t hat sich
geändert` ab. `npx vitest run` dreimal, dreimal identisch rot: `PREFS ERROR: error sending request … ERR_TOFU_PIN_MISMATCH:
AdminHelper TOFU: …`.
HEAD: 8fb8f648
Semantik: `docs/admin/troubleshooting.html:72`: „Erscheint nach einer legitimen Zertifikats-Rotation die Meldung
AdminHelper TOFU: … hat sich geändert, in den Desktop-Einstellungen Gepinntes Zertifikat zurücksetzen klicken und neu
verbinden“. Die Meldung, die der Nutzer liest, beginnt ohne Code. `docs/developer/desktop.html:125`: „Abbrechen zeigt
die Meldung (ohne Code) inline.“ `lib/utils/errors.ts:11`: „They are for the code, not the user“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG.md (Fixed); keine Seite unter docs/ beschreibt diese Anzeigen

### T2 — Ansible und Monitoring-Übersicht: der Ladefehler ohne die Maschinen-Codes (R-0261)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/ansible.ts, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/lib/stores/ansible.pipeline.test.ts, apps/desktop/ui/src/lib/stores/monitoring.test.ts, CHANGELOG.md
Änderung: Zwei Stores legen den Ladefehler als Text ab, den eine Seite inline zeigt:
- `loadAnsibleData` (`stores/ansible.ts:80-81`) setzt `loadError: msg`.
- `loadMonitoring` (`stores/monitoring.ts:238-246`) setzt `error: msg === SESSION_EXPIRED ? null : msg`.

Künftig geht der abgelegte Text durch `withoutErrorCodes`. Der Vergleich mit `SESSION_EXPIRED` bleibt am rohen Text.
Gefiltert wird im Store, nicht in der Seite: `ansibleLoadError` und `monitoringError` haben je nur diesen einen Leser,
eine Anzeige.

Tests:
- In `ansible.pipeline.test.ts` (mockt `ansibleApi` schon): `fetchPlaybooks` lehnt mit der Kette samt
  `ERR_TOFU_PIN_MISMATCH` ab, `ansibleLoadError` ist die Prosa ohne `ERR_`.
- In `monitoring.test.ts` (mockt `fetchStatus` schon): ebenso für `monitoringError`; `SESSION_EXPIRED` ergibt weiter
  `null`.
- Rot vor dem Fix.

Der CHANGELOG-Eintrag aus T1 nennt beide Seiten.
Beweis: origin/main@8fb8f648, Probe-Test (nicht committet, danach gelöscht) mit den echten Stores, nur Session, die
beiden APIs und `tNow` gemockt. `npx vitest run` dreimal, dreimal identisch rot: `MONITORING ERROR: error sending
request … ERR_TOFU_PIN_MISMATCH: …` und `ANSIBLE ERROR: error sending request … ERR_TOFU_PIN_MISMATCH: …`.
HEAD: 8fb8f648
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG.md (der Eintrag aus T1)
