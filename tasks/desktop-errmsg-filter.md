<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: der ERR_*-Filter zentral in errMsg — Task-Ledger
Status: aktiv · Branch: feature/desktop-errmsg-filter · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-11 (kleines Fund-Paket aus R-0276, Triage 2026-10-10 auf Kevins Delegation; Entscheidungen a und b wie im Plan; Bau erst nach dem Merge von Phase B (R-0224), mit origin/main hinein; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0276 (Kurz-Ledger ohne Spec)
Heavy: none — ein Textfilter der Desktop-UI (`desktop-ui`), der heute an jeder Stelle von Hand steht; kein Stack-, Gateway-, PKI- oder Install-Pfad, keine Live-Spec liest diese Texte, Komponenten- und Store-Tests decken die Wege ab.
DoD je Task: CLAUDE.md (Tests grün, svelte-check, ESLint und Prettier sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-11 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die die Aufsicht auf Kevins
Wort triagiert hat (2026-10-10). Sie stammt aus dem Plan von R-0261 (#112), offene Frage 1, Weg (b): der Filter zentral
in `errMsg`, die dritte Stelle derselben Klasse nach R-0243 und R-0248. Die private Roadmap ist in diesem Worktree nicht
lesbar; der Zeileninhalt kommt von der Aufsicht.

Baut auf `feature/device-certificate-register` (R-0224) auf: dort kommen `ERR_CERT_REVOKED` in `errors.ts` und
`certRevoked`/`resetInfo` in `Login.svelte` dazu. Gebaut wird nach dessen Merge, mit origin/main zuerst hineingemergt.
Zeilenangaben `feature/device-certificate-register@b7eae2d5`.

Bestand.
- `lib/utils/errors.ts:6` `errMsg` gibt `err.message` roh zurück; `:14-15` `ERROR_CODES`, `:18` `withoutErrorCodes`.
- Den Filter hängen die Aufrufer von Hand an: `NotificationPrefs.svelte:91` und `:138`, `stores/ansible.ts:80`,
  `stores/monitoring.ts:246` (auf `msg` aus `:238`), `SettingsModal.svelte:162`. Dazu filtert `stores/statusBar.ts:41`
  jeden Text, der über `reportError` kommt (R-0248). Jede neue Fehleranzeige muss daran denken; dreimal hat das eine
  eigene Roadmap-Zeile gekostet.
- Die Codes liest nur `Login.svelte`: `:57-68` (`caPinError`, `pinError`, `mtlsRequired`, `certUserMismatch`,
  `certRevoked`) und `:181` (`ERR_TLS_UNKNOWN_ISSUER`). Es setzt `error = errMsg(err)` an `:99`, `:131`, `:147` und
  `:232`, `msg = errMsg(err)` in `surfaceError` (`:180`), und zeigt `displayError = withoutErrorCodes(error)` (`:70`).
  `git grep -n "ERR_" -- apps/desktop/ui/src ':!*.test.ts' ':!*dictionaries.ts'` findet sonst nur Kommentare und `ERROR_CODES` selbst.
- Die beiden Wiederherstellungen nach einem Pin-Mismatch auf dem Login-Screen (`:322-331`, `:378-387`) haben kaum Tests:
  nur `Login.revoked.test.ts` geht einmal über den CA-Fall (Hinweis „nur lokal“), den TOFU-Fall prüft keiner. Filtert
  `errMsg` zentral und liest der Login danach versehentlich den gefilterten Text, verschwinden beide Knöpfe ohne roten
  Test. Darum kommen die Tests zuerst (T1).

### T1 — Login: Tests für beide Wiederherstellungen nach einem Pin-Mismatch (R-0276)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.pin.test.ts
Änderung: Neue Testdatei mit SPDX-Header, die Mocks wie in `Login.revoked.test.ts` (Bridge, `confirm`); am Produktcode
ändert sich nichts. Fälle:
- Login scheitert mit `ERR_TOFU_PIN_MISMATCH` in der Quellenkette: der Knopf „Gepinntes Server-Zertifikat
  zurücksetzen“ erscheint, die Meldung steht ohne Code; nach bestätigter Warnung `resetServerCertPin(url)`, nicht
  `resetDeviceIdentity`.
- Login scheitert mit `ERR_CA_PIN_MISMATCH`: der Knopf „Geräte-Identität zurücksetzen“; `resetDeviceIdentity(url)`,
  nicht `resetServerCertPin`.
- Die Registrierung mit Token (`enrollWithToken`) scheitert mit `ERR_TOFU_PIN_MISMATCH`: derselbe Knopf im
  Registrier-Formular (`:378-387`).
- Abgelehnte Warnung: nichts wird zurückgesetzt.
Die Tests sind vor T2 grün; sie halten fest, dass der Login die Codes weiter sieht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)
Beweis: Planung R-0261, Worker B, 2026-10-10, `feature/desktop-kleinpaket-4@cfb72ffa`, offene Frage 1 (b); die Lücke:
`git grep -l "ERR_TOFU_PIN_MISMATCH" -- 'apps/desktop/ui/src/components/Login*.test.ts'` ist leer.
Orakel: mutation-sample — `Login.svelte` mit dem gefilterten Text statt des rohen (T2): alle vier Fälle rot.
Dedup-Key: ref:desktop:errors.ts:central-filter
HEAD: b7eae2d5
Semantik: `docs/admin/troubleshooting.html:73`: „Ist der Wechsel erwartet: auf dem Login-Screen den Knopf
Geräte-Identität zurücksetzen unter der Fehlermeldung klicken“; `:72`: „Erscheint nach einer legitimen
Zertifikats-Rotation die Meldung AdminHelper TOFU: … hat sich geändert“ (die Meldung, die der Nutzer liest, beginnt ohne
Code).

### T2 — errMsg filtert zentral, der Login liest die Codes roh (R-0276)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/errors.ts, apps/desktop/ui/src/lib/utils/errors.test.ts, apps/desktop/ui/src/components/Login.svelte
Änderung: `errMsg` gibt die Meldung ohne die Codes aus `ERROR_CODES` zurück. Neu ist `errRaw(err)` mit dem rohen Text,
für den, der an den Codes verzweigt; der Kommentar in `errors.ts` sagt das. `Login.svelte` nimmt `errRaw` an den fünf
Stellen, an denen es `error` oder `msg` setzt (`:99`, `:131`, `:147`, `:180`, `:232`), und zeigt weiter `displayError`.
Die übrigen Verzweigungen am Text bleiben, weil der Filter nur die Codes nimmt: der Vergleich mit `SESSION_EXPIRED`
(etwa `stores/monitoring.ts:194`) und der Präfix `HTTP 409` in `stores/infra.ts:123`.
- Neue Testdatei `errors.test.ts` mit SPDX-Header: jeder Code aus `ERROR_CODES` fällt weg, auch mitten in einer
  reqwest-Kette, die Prosa bleibt vollständig; `SESSION_EXPIRED`, ein Text mit `HTTP 409` vorn und ein Nicht-`Error`-Wert
  bleiben unverändert;
  `errRaw` behält die Codes.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)
Abhängt von: T1
Orakel: mutation-sample — `errMsg` ohne Filter: `errors.test.ts` rot; `Login.svelte` mit `errMsg` statt `errRaw`: T1 rot.
Dedup-Key: ref:desktop:errors.ts:central-filter
Semantik: `docs/developer/desktop.html:125`: „Abbrechen zeigt die Meldung (ohne Code) inline.“; `errors.ts:12-13`:
„They are for the code, not the user“.

### T3 — Die Filter an den einzelnen Aufrufern fallen weg (R-0276)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationPrefs.svelte, apps/desktop/ui/src/lib/stores/ansible.ts, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/components/SettingsModal.svelte
Änderung: `withoutErrorCodes(errMsg(err))` wird `errMsg(err)` in `NotificationPrefs.svelte:91` und `:138`,
`stores/ansible.ts:80` und `SettingsModal.svelte:162`; in `stores/monitoring.ts:246` wird `withoutErrorCodes(msg)` zu
`msg`. Ungenutzte Imports gehen mit. `stores/statusBar.ts:41` behält seinen Filter: `reportError` nimmt auch Texte, die
nicht über `errMsg` kommen.
- Die Tests dieser Stellen bleiben unverändert und grün (`NotificationPrefs.test.ts`, `ansible.pipeline.test.ts`,
  `monitoring.test.ts`, `SettingsModal.enroll.test.ts`); danach hängen sie am Filter in `errMsg`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)
Abhängt von: T2
Metrik: Aufrufe von `withoutErrorCodes(` in `apps/desktop/ui/src` außer `errors.ts` und Tests, `git grep -c` (git
2.47.3): 7 → 2 (die Anzeige im Login und die Statusleiste).
Orakel: mutation-sample — `errMsg` ohne Filter: die Tests der vier Stellen rot.
Dedup-Key: ref:desktop:errors.ts:central-filter
