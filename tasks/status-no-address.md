<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket status-no-address: Grund und Wochenlauf-Zeile ohne Box-Adresse (R-0335) — Task-Ledger
Status: bereit · Branch: harness/status-no-address · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket aus R-0335, Triage Kevin 2026-10-13; Bau nach status-classes; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0335 (Kurz-Ledger ohne Spec)
Heavy: none — heavy.sh mit heavy_test (Shims), session-status.sh mit session_status_test (Fixture-Reports); nur Platzhalter-Adressen (die bestehenden 10.x-Fixtures bleiben, neue aus RFC 5737), kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: harness/status-classes — beide ändern session-status.sh und session_status_test.sh; erst nach dessen
Merge bauen und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen.
Zeilenangaben origin/main@75ed3e09; beim Bau an Symbolen orientieren.

Vorab geprüft:
- AH-STATUS (session-status.sh `weekly_line` :161–189) druckt die erste Zeile des neuesten
  `.ah-out/weekly/*/report.md` wörtlich. Bei einem unverifizierten Lauf ist das `UNVERIFIED ($REASON)` (heavy.sh :932).
- `REASON` setzt heavy.sh `set_infra` (:108–112), oft mit einer Zeile, die `infra_marker` aus all.log übernimmt, etwa
  vm.py `no ssh: adminhelper@<adresse> refused for 900s`. So steht eine Box-Adresse im Block jeder Session.
- Die Box-Adressen kommen von vm.py als IPv4 (`vm_ipv4`). Ein Hostname kann vor allem als `<nutzer>@<host>` auftauchen.
- Der Rumpf von report.md (Summary-Zeilen mit `server=<adresse>` und mehr) erreicht den Block nicht. Er bleibt, wie er
  ist; report.md liegt gitignored unter `.ah-out`.

### T1 — heavy.sh schreibt den Grund ohne Box-Adresse  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @881aa646 2026-10-13T11:29:24+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `set_infra` (:108–112) maskiert im Grund jede IPv4-Adresse zu `<ip>` und jedes `<nutzer>@<host>` zu `<user>@<host>`,
  bevor er in `REASON` geht (sed unter `LC_ALL=C`).
  - Der Grund bleibt sonst wörtlich, damit die Triage ihn weiter lesen kann.
  - Die Kopfzeile von report.md und die Zeile `heavy.sh[…]: UNVERIFIED (…)` (:1049) tragen dann keine Adresse.
- `FINDINGS` (history.csv) und `NOTES` bleiben, wie sie sind; sie erreichen den Block nicht.
- Fälle in heavy_test:
  - Der bestehende Fall `vm.py: no ssh: adminhelper@10.0.0.9 refused for 900s` (:888) erwartet in der Kopfzeile
    `no ssh: <user>@<host> refused for 900s` und keine `10.0.0.9`.
  - Ein Fall mit nackter Adresse im Grund (`vm.py: sync failed: rsync to 198.51.100.7 exited 12`) ergibt `<ip>`.
Rot vorher: Auf main steht `10.0.0.9` in der Kopfzeile des Reports.
Beweis:
- origin/main@75ed3e09, heavy.sh :111 `REASON="$1$had_fail"`, :932 `echo "UNVERIFIED ($REASON)"`.
- Fund: Review status-guard, Worker A, 2026-10-13.
Dedup-Key: ref:scripts:session-status.sh:weekly-header-lab-address
HEAD: 75ed3e09
Semantik: CLAUDE.md §2 „Claude tut nie von sich aus: … Homelab-Namen … in versionierte Dateien schreiben“, und
die Session-Transkripte gehören in dieselbe Vorsicht. heavy.sh :109–111: der Grund ist für die Triage.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — Die Wochenlauf-Zeile zeigt keine Box-Adresse  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a6927285 2026-10-13T11:44:48+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `weekly_line` maskiert die Kopfzeile wie T1 (IPv4 zu `<ip>`, `<nutzer>@<host>` zu `<user>@<host>`), bevor sie in den
  Block geht.
  - Das deckt auch Reports, die vor T1 geschrieben wurden.
- Fälle in session_status_test:
  - Ein neuester Report mit `UNVERIFIED (vm.py: no ssh: adminhelper@192.0.2.9 refused for 900s, last seen at
    198.51.100.7)` ergibt `… UNVERIFIED (vm.py: no ssh: <user>@<host> refused for 900s, last seen at <ip>)`, und keine
    der beiden Adressen steht im Block.
  - Die bestehenden Kopfzeilen ohne Adresse (`UNVERIFIED (doctor red)`, :143, :175) bleiben unverändert.
Rot vorher: Auf main steht `adminhelper@192.0.2.9` in der Zeile 4 des Blocks.
Beweis: origin/main@75ed3e09, session-status.sh :174 `head="$(head -1 "$f" …)"` und :185 `echo "$day ($n d): $head"`.
Dedup-Key: ref:scripts:session-status.sh:weekly-header-lab-address
HEAD: 75ed3e09
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — Nachbesserung aus dem Review am Ende: auch Host und Node des Hypervisors werden maskiert  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f312754e 2026-10-13T12:31:02+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 aus dem Review am Ende (Opus, `request_changes`: ein belegter Fund, zwei nits).
- vm.py hängt an `no ip: …` (`wait_for`) und `clone of … failed` den API-Fehler an:
  `POST <AH_PVE_URL>/api2/json/nodes/<node>/…`.
  - `infra_marker` übernimmt diese Zeilen, und T1/T2 ließen den Host der URL und den Node-Namen stehen.
- Neu: `mask_addr` in heavy.sh und `weekly_line` maskieren zusätzlich den Host jeder `http(s)://`-URL zu `<host>`
  und `/nodes/<name>` zu `/nodes/<node>`. Beide sed-Zeilen bleiben gleich.
- Fälle, Platzhalter:
  - heavy_test: der Grund `no ip` mit `POST https://pve.plchold.example:8006/api2/json/nodes/plchold-n1/…` ergibt
    `https://<host>:8006/…/nodes/<node>/…`, in der Kopfzeile und in der Urteilszeile.
  - session_status_test: ein Report mit `clone of … failed: POST https://203.0.113.5:8006/…/nodes/plchold-n1/…`.
- nit: Der Kopfkommentar von session-status.sh sagte „read verbatim“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T2

### T4 — Nachbesserung aus dem Re-Review: der Node in der Meldung von PVE und die UPID werden maskiert  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @760bf551 2026-10-13T12:52:51+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 aus dem Re-Review (Opus, `request_changes`: zwei belegte Funde). Behoben mit den Fällen
des Reviewers als Tests.
- Die Meldung von PVE `Configuration file 'nodes/<node>/qemu-server/<id>.conf' does not exist` trägt den Node ohne
  führenden Schrägstrich. vm.py übernimmt sie wörtlich, und die Regel aus T3 griff nur `/nodes/`.
  - Neu: `nodes/<name>` wird nach jedem Zeichen außer einem Wortzeichen zu `nodes/<node>`, auch am Zeilenanfang.
- Der Status-Pfad eines Tasks trägt die UPID (`UPID:<node>:…:<nutzer>@pve!<token-id>:`), URL-kodiert.
  - Neu: Jede UPID wird zu `<upid>`.
- Beide sed-Zeilen bleiben gleich. session_status_test prüft das jetzt: die Programme in heavy.sh und session-status.sh
  sind identisch.
- Fälle, Platzhalter `plchold`, `*.example`:
  - heavy_test: `clone … failed: … HTTP 500 Configuration file 'nodes/plchold-n1/…'` und ein Aufräumfehler mit
    `…/tasks/UPID%3Aplchold-n1%3A…/status`.
  - session_status_test: ein Report `no ip … Configuration file 'nodes/plchold-n1/…'`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T3
