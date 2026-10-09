<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Kleinpaket 2: Fehler ohne Code, Identitäts-Block nur mit Session, Tunnel beim Speichern — Task-Ledger
Status: erledigt · Branch: feature/desktop-kleinpaket-2 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (kleines Fund-Paket aus R-0243, R-0244, R-0245, von Kevin am 2026-10-09 in der Triage angenommen; Delegation Kevin 2026-10-05). Offene Fragen (Aufsicht): 1 Weg (b), nur starten, wenn kein Tunnel laeuft — ein Neustart bei jedem Speichern braeche laufende SSH-/RDP-Verbindungen; 2 Heavy linux-full nur mit desktop_e2e_tunnel und desktop_e2e_crud (Enrollment-UI ist eine Journey)
Spec: Roadmap R-0243, R-0244, R-0245 (Kurz-Ledger ohne Spec)
Heavy: linux-full — die Registrierung in den Einstellungen und das Speichern im Server-Modus ändern sich (Enrollment-UI, Tunnel); auf einer Pool-VM `run.sh e2e` nur mit `desktop_e2e_tunnel` (darin `settings-enroll.live.js`) und `desktop_e2e_crud` (darin `settings-mode.live.js`), kein Server- oder Gateway-Pfad (offene Frage 2).
DoD je Task: CLAUDE.md (Tests grün, eslint/prettier und svelte-check sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus drei Zeilen, die Kevin am 2026-10-09
triagiert und angenommen hat. Alle drei stammen aus dem Opus-Review über den Branch von R-0212 (#102). Die private
Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@bf383a7a.

### T1 — Einstellungen: Ein Fehler der Registrierung erscheint ohne `ERR_*`-Code (R-0243)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/errors.ts, apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @06fe43f6 2026-10-09T16:12:56+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: `onEnroll` zeigt einen Fehler als `enrollMsg = errMsg(err)` (`SettingsModal.svelte:163`), also samt Code,
etwa `ERR_TLS_UNKNOWN_ISSUER: AdminHelper: …`, wenn „Selbstsignierte erlauben“ im offenen Dialog aus ist.
- Der Login entfernt die Codes schon (`displayError`, `Login.svelte:59-61`), mit einer festen Liste.
- Die Liste wandert als kleine Funktion nach `lib/utils/errors.ts` (neben `errMsg`). Sie kennt alle vier Codes des
  Backends: `ERR_TLS_UNKNOWN_ISSUER`, `ERR_CA_PIN_MISMATCH`, `ERR_TOFU_PIN_MISMATCH`, `ERR_MTLS_CERT_REQUIRED`.
- Der Login und die Einstellungen nutzen sie. Für den Login ändert sich nichts Sichtbares, denn
  `ERR_MTLS_CERT_REQUIRED` zeigt dort ohnehin seinen eigenen Hinweis.

Test in `SettingsModal.enroll.test.ts`: `enrollWithToken` scheitert mit `ERR_TLS_UNKNOWN_ISSUER: <Text>`; die Meldung
enthält den Text, nicht den Code. Rot vor der Änderung. Die bestehenden Login-Tests (`Login.trust.test.ts`, „ohne
Code“ nach Abbrechen) bleiben grün.
CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile.
Beweis: origin/main@bf383a7a:
- `sed -n 163p apps/desktop/ui/src/components/SettingsModal.svelte` → `enrollMsg = errMsg(err);`;
- `sed -n 60p apps/desktop/ui/src/components/Login.svelte` → die Regex, die der Login anwendet.
Gefunden im Opus-Review über den Branch von R-0212.
HEAD: bf383a7a
Semantik: `docs/developer/desktop.html:125` zu `ERR_TLS_UNKNOWN_ISSUER`: „Abbrechen zeigt die Meldung (ohne Code)
inline.“ Der Code ist für die Maschine, der Nutzer liest den Text; die Einstellungen weichen davon ab.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG.md (Fixed)

### T2 — Einstellungen: Der Identitäts-Block erscheint nur mit Session (R-0244)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @2ebde36b 2026-10-09T16:17:44+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Der Block hängt an `{#if mode === 'server'}` (`SettingsModal.svelte:403`), und `mode` ist der Radio-Knopf im
Dialog, nicht der gespeicherte Modus.
- Wer in `local` oder `sync` nur „Server“ anklickt, sieht ohne Session das Token-Feld; vor R-0212 sah er dort schon den
  Reset-Block.
- Die Registrierung liefe dann gegen die URL im Feld (`$session?.serverUrl ?? serverUrl`, `:147`), und der Tunnel
  startet nicht, obwohl der Hinweis es verspricht.
- Künftig erscheint der Block nur, wenn eine Session besteht (`mode === 'server' && $session`).
- `onEnroll` nimmt die URL der Session; der Rückfall auf das Feld entfällt.

Test in `SettingsModal.enroll.test.ts`: ohne Session, Dialog auf „Server“: weder Token-Feld noch Zurücksetzen. Dafür
wird der Session-Mock schaltbar; die bestehenden Fälle laufen weiter mit Session. Rot vor der Änderung.
Beweis: origin/main@bf383a7a `sed -n 403p apps/desktop/ui/src/components/SettingsModal.svelte` → `{#if mode ===
'server'}`; `mode` setzt der Radio-Knopf (`onchange={() => (mode = 'server')}`). Gefunden im Opus-Review über den
Branch von R-0212.
HEAD: bf383a7a
Semantik: `docs/admin/benutzer.html:97`: „Ist mTLS nicht erzwungen und der Nutzer schon angemeldet, registriert er
das Gerät ohne Abmelden: in den Einstellungen (Modus Server) den Token eingeben“. Die Registrierung in den
Einstellungen ist für Angemeldete gedacht. Die Spec von R-0212 nennt die Einstellungen „im Modus `server` also nur
mit Session“ erreichbar.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (die Doku beschreibt schon den Fall mit Session)
Abhängt von: T1

### T3 — Speichern im Server-Modus scheitert nicht mehr an einem laufenden Tunnel (R-0245)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/settings.ts, apps/desktop/ui/src/lib/stores/settings.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @4b5b8c39 2026-10-09T16:22:43+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: `saveSettings` ruft im Modus `server` mit Session `void tunnelStore.startIfServerMode()`
(`stores/settings.ts:102`), ohne Rücksicht auf einen laufenden Tunnel.
- Läuft frpc schon, scheitert `start_frpc` an „frpc laeuft bereits“ (`frpc.rs:245-247`).
- Die Anzeige geht auf `disconnected`, die Statusleiste meldet einen Fehler, frpc läuft weiter.
- Das trifft schon eine Sprach- oder RDP-Einstellung im Server-Modus.

Der Plan folgt der Empfehlung zu offener Frage 1, Weg (b):
- Gestartet wird nur, wenn kein Tunnel läuft. Maßgeblich ist der Status des Tunnels (`tunnel_status` bzw. der
  Tunnel-Store), nicht die Anzeige allein.
- Ein laufender Tunnel bleibt unberührt.
- Bei Weg (a) stoppt `saveSettings` den Tunnel vor dem Start wie T7 von R-0212, und jedes Speichern startet ihn neu.

Tests in `stores/settings.test.ts`, im Block „saveSettings mode-switch orchestration“:
- Server bleibt Server, mit Session und laufendem Tunnel: kein Start (bei Weg (a): Stop vor Start).
- Ohne laufenden Tunnel: Start wie bisher.
- Die bestehenden Fälle (URL-Wechsel, Wechsel nach `local` bzw. `sync`) bleiben unverändert.
- Rot vor der Änderung.
CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile.
Beweis: origin/main@bf383a7a:
- `sed -n 102p apps/desktop/ui/src/lib/stores/settings.ts` → `void tunnelStore.startIfServerMode();`;
- `sed -n 245,247p apps/desktop/src-tauri/src/frpc.rs` → `if guard.child.is_some() { return Err(… "frpc laeuft bereits" …) }`.
Gefunden im Opus-Review über den Branch von R-0212.
HEAD: bf383a7a
Semantik: keine Stelle in docs/ sagt, was Speichern mit einem laufenden Tunnel tut. Gesucht wurde in
`docs/developer/desktop.html`, `docs/admin/frp-tunnel.html` und `docs/admin/benutzer.html` nach Tunnelstart und
Auto-Start. `docs/developer/desktop.html:147` beschreibt nur die Bedingung: „Der Auto-Start des Sidecars passiert nur
im Server-Mode: `startIfServerMode()` im Tunnel-Store bricht ab, wenn keine Session vorliegt oder `settings.mode !==
'server'`.“ Das gewollte Verhalten entscheidet offene Frage 1.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG.md (Fixed)

### T4 — Nachbesserung: Zurücksetzen ohne Anmeldung in der Doku, zwei Tests, CHANGELOG zu R-0244  [x]
Komponente: desktop-ui · Dateien: docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/developer/desktop.html, docs/en/developer/desktop.html, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts, apps/desktop/ui/src/lib/stores/settings.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @8c61d5c3 2026-10-09T16:55:02+02:00
Review: kein neuer Review (Nachbesserung, Aufsicht 2026-10-09)
Änderung: Aus dem Gesamt-Review (Opus), von der Aufsicht freigegeben (2026-10-09), ohne neuen Review.
- Nach einer Server-Neuinstallation scheitert ein registriertes Gerät mit `ERR_CA_PIN_MISMATCH` und kommt nicht
  mehr in eine Session. `troubleshooting.html:73` / EN `:74` schickten es zum Zurücksetzen in die Einstellungen;
  seit T2 gibt es den Block dort nur mit Session. Beide nennen jetzt den Knopf unter der Fehlermeldung auf dem
  Login-Screen (`login.resetDeviceId`) und die Einstellungen nur noch für Angemeldete.
- `docs/developer/desktop.html:129` / EN: „nur sichtbar wenn registriert und angemeldet“.
- Tests: Der Fall ohne Session wartet auf das Ergebnis von `isDeviceEnrolled` im DOM (`tick()`), nicht nur auf den
  Aufruf. Ein gescheiterter `tunnel_status` löst in `saveSettings` den Start trotzdem aus.
- CHANGELOG: eine Zeile zu R-0244 unter Fixed, weil sichtbar.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/troubleshooting.html + docs/en/admin/troubleshooting.html · docs/developer/desktop.html + docs/en/developer/desktop.html · CHANGELOG.md
Abhängt von: T2, T3
