<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Kleinpaket 3: keine ERR_*-Codes in der Statusleiste — Task-Ledger
Status: bereit · Branch: feature/desktop-kleinpaket-3 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (kleines Fund-Paket aus R-0248, von Kevin am 2026-10-09 in der Triage angenommen; Delegation Kevin 2026-10-05). Offene Frage (Aufsicht): 1 Weg (a), der Filter sitzt zentral in reportError; die Inline-Stellen ausserhalb der Statusleiste sind eine eigene Roadmap-Zeile
Spec: Roadmap R-0248 (Kurz-Ledger ohne Spec)
Heavy: none — ein Textfilter im Store der Statusleiste (`desktop-ui`); kein Stack-, Gateway-, PKI- oder Install-Pfad, keine Live-Spec liest die Statusleiste (die `ERR_`-Prüfung in `enroll-trust-dialog.live.js` liest den Login-Fehler), der Komponententest deckt den Weg ab.
DoD je Task: CLAUDE.md (Tests grün, svelte-check, ESLint und Prettier sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin am 2026-10-09 als
„Kleinpaket Desktop 3“ triagiert hat. Sie stammt aus dem Gesamt-Review von Desktop-Kleinpaket 2 (#103). Die private
Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@33cf47b6.

### T1 — Statusleiste: `reportError` zeigt die Meldung ohne die Maschinen-Codes (R-0248)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/statusBar.ts, apps/desktop/ui/src/lib/stores/statusBar.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @c12faa2c 2026-10-09T20:46:15+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: R-0243 (#103) hat die Codes nur aus der Registrierung in den Einstellungen genommen (`withoutErrorCodes`,
`lib/utils/errors.ts:16`). Die Statusleiste zeigt sie weiter:
- Jede Meldung der Statusleiste geht über `reportError` (`stores/statusBar.ts:36`), heute 70 Aufrufe in Stores und
  Komponenten, meist `reportError(errMsg(err))`.
- Ein Netzwerkfehler aus dem Backend trägt die Codes in seiner Quellenkette (`AppError::Network`, `error.rs:55-80`),
  etwa `ERR_TOFU_PIN_MISMATCH` (`tofu.rs:256`) oder `ERR_CA_PIN_MISMATCH` nach einem Zertifikatswechsel am Server.
- So kommt beim Tunnel-Start (`frpc.rs:91`, Visitor-Bundle über `authenticated_get`) der Code als `Tunnel: …
  ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: …` in die Statusleiste (`stores/tunnel.ts:60`, ebenso `markError` `:78`).
- Die beiden Stellen aus der Zeile, `SettingsModal.svelte:118` und `:142`, können heute keinen Code tragen:
  `reset_server_cert_pin` und `reset_device_identity` geben immer `Ok(())` zurück (`commands.rs:66`, `:94`). Mit dem
  Filter an einer Stelle sind sie trotzdem abgedeckt.

Der Plan folgt der Empfehlung zu offener Frage 1, Weg (a): `reportError` schickt den Text durch `withoutErrorCodes`,
bevor er in den Store geht. Damit gilt die Regel für alle Aufrufer an einer Stelle, auch für die Zusammensetzung
`Tunnel: {message}`, denn die Codes werden überall im Text entfernt (`errors.ts:13`, global). `showStatus` bleibt,
wie es ist; Erfolgsmeldungen tragen keine Codes. Der Login liest die Codes weiter aus seinem eigenen Fehlertext
(`Login.svelte`), nicht aus der Statusleiste.

Tests in `statusBar.test.ts`, neben „reportError sets an error message“:
- Ein Text wie ihn der Tunnel-Start heute meldet (`Tunnel: error sending request …: ERR_TOFU_PIN_MISMATCH:
  AdminHelper TOFU: Das Server-Zertifikat …`) steht ohne `ERR_` in der Statusleiste, die Prosa bleibt vollständig.
- Ebenso ein Text mit `ERR_CA_PIN_MISMATCH` am Anfang.
- Rot vor dem Fix.

CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile.
Beweis: origin/main@33cf47b6, Probe-Test (nicht committet) unter `apps/desktop/ui/src/lib/stores/` mit dem echten
`statusBar`-Store und dem echten Tunnel-Store (Bridge, Session und `tNow` gemockt), `bridge.startTunnel` lehnt mit `error sending request for url
(https://x/api/frp/generate/visitor-bundle): client error (Connect): ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das
Server-Zertifikat für x hat sich seit dem ersten Verbinden geändert` ab. `npx vitest run <probe>` dreimal, dreimal
identisch rot: `STATUS TEXT: Tunnel: error sending request … ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: …` und
`AssertionError: expected 'Tunnel: error sending request for url…' not to contain 'ERR_'`.
Dedup-Key: bug:desktop:SettingsModal.svelte:raw-err-statusbar
HEAD: 33cf47b6
Semantik: `docs/admin/troubleshooting.html:72`: „Erscheint nach einer legitimen Zertifikats-Rotation die Meldung
AdminHelper TOFU: … hat sich geändert, in den Desktop-Einstellungen Gepinntes Zertifikat zurücksetzen klicken und neu
verbinden“. Die Meldung, die der Nutzer liest, beginnt ohne Code. `docs/developer/desktop.html:125` zu
`ERR_TLS_UNKNOWN_ISSUER`: „Abbrechen zeigt die Meldung (ohne Code) inline.“ Der Code ist für die Maschine (`errors.ts`:
„They are for the code, not the user“).
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG.md (Fixed); die Statusleiste beschreibt keine Seite unter docs/
