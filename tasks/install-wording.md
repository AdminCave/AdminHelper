<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Installer: die Zusammenfassung nennt den Desktop-Knopf, wie er heißt — Task-Ledger
Status: erledigt · Branch: feature/install-wording · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0242, Triage Kevin 2026-10-09; Heavy none ist die Teststrategie der Aufsicht, weil kein schwerer Pfad install.sh ausfuehrt und install_test.sh die Zeile hermetisch faehrt; ASCII-Umlaut; EN-Text nicht in diesem Paket; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0242 (Kurz-Ledger ohne Spec)
Heavy: none — kein Multibox- oder linux-full-Pfad führt `scripts/install.sh` aus (`box_serverbox.sh` startet den Stack mit compose, `multibox.sh` ruft nur `agent-install.sh`); die geänderte Zeile ist Text im Heredoc der Zusammenfassung, und `install_test.sh` (Unit-Layer, `scripts`) fährt `install.sh` hermetisch bis zu dieser Ausgabe.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-09 als
Loop-Futter triagiert. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@dba03852.

Gesucht nach weiteren alten Formulierungen in `scripts/install.sh` und `scripts/update.sh` (`git grep -i
'enroll\|registr\|Token\|Desktop'`): in `install.sh` noch der Kopfkommentar `:14-15` („enroll with token“), in
`update.sh` keine. Außerhalb der beiden Skripte, nicht Teil des Pakets: `docs/adr/0003-decoupled-enrollment-door.md:75`
nennt „Mit Token enrollen“ (ein ADR hält den Stand seiner Entscheidung fest); „enrollen“ als Verb im Fließtext
(`docs/admin/benutzer.html:100`, `docs/admin/betrieb.html:184`, `.env.example:115`) nennt keinen Knopf.

### T1 — install.sh: die Zusammenfassung nennt „Geraet mit Token registrieren“, ein Test hält sie am Desktop-Text (R-0242)  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 1 ok @8bbac2ff 2026-10-12T20:27:13+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `scripts/install.sh:300` (Heredoc der Zusammenfassung): `"Mit Token enrollen"` wird `"Geraet mit Token
  registrieren"`, der Text des Desktop-Knopfs (`apps/desktop/ui/src/lib/i18n/dictionaries.ts:304`,
  `'login.enroll.switch'`), mit ae/oe/ue wie jede Ausgabe dieses Skripts („oeffnen“, „gueltig“, „laeuft“). Der Rest
  der Zeile bleibt.
- Kopfkommentar `:14-15`: `("enroll with token")` wird der englische Text desselben Knopfs, `("Enroll this device
  with a token")` (`dictionaries.ts:920`).
- `scripts/tests/install_test.sh`, Fall 1 (signierter Bootstrap, `$out` nach `:102`): eine Prüfung, dass die
  Ausgabe den deutschen Text von `'login.enroll.switch'` aus `dictionaries.ts` nennt, in Anführungszeichen und mit
  ä/ö/ü/ß zu ae/oe/ue/ss gefaltet. Den Text liest der Test aus der Datei (erster Treffer, der deutsche Block), damit
  die nächste Umbenennung im Desktop den Test rot macht und nicht still auseinanderläuft; ist der gelesene Text leer,
  ist das ein eigener Fehler, keine leere Suche.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine — `docs/admin/installation.html:99` und `docs/en/admin/installation.html:76` nennen den Knopf schon so
Beweis: origin/main@dba03852: `git grep -n 'Mit Token enrollen' -- scripts/install.sh` → `scripts/install.sh:300`;
`bash scripts/tests/install_test.sh` → `install_test: 8 passed, 0 failed`, die Ausgabe enthält `"Mit Token enrollen"`
genau einmal und `Geraet mit Token registrieren` nie, dreimal identisch.
Orakel: mutation-sample — die alte Zeile zurück in `install.sh`: der neue Fall in `install_test.sh` rot; der Knopf in
`dictionaries.ts` umbenannt: ebenso rot.
Dedup-Key: ref:scripts:install.sh:enroll-wording
HEAD: dba03852
Semantik: `docs/admin/installation.html:99`: „Am Ende gibt das Script die Zugangsdaten aus: URL, Admin-Login und einen
Enrollment-Token. Den Token im Desktop-Client unter „Gerät mit Token registrieren" (Server-URL + Token) einlösen“.
