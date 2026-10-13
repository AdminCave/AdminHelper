<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket status-no-address: Grund und Wochenlauf-Zeile ohne Box-Adresse (R-0335) — Task-Ledger
Status: freigegeben · Branch: harness/status-no-address · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket aus R-0335, Triage Kevin 2026-10-13; Bau nach status-classes; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0335 (Kurz-Ledger ohne Spec)
Heavy: none — heavy.sh mit heavy_test (Shims), session-status.sh mit session_status_test (Fixture-Reports); nur Platzhalter-Adressen aus 10.0.0.0/8 wie in den Tests heute, kein Stack-, Gateway-, PKI- oder Install-Pfad.
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

### T1 — heavy.sh schreibt den Grund ohne Box-Adresse  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung:
- `set_infra` (:108–112) maskiert im Grund jede IPv4-Adresse zu `<ip>` und jedes `<nutzer>@<host>` zu `<user>@<host>`,
  bevor er in `REASON` geht (sed unter `LC_ALL=C`).
  - Der Grund bleibt sonst wörtlich, damit die Triage ihn weiter lesen kann.
  - Die Kopfzeile von report.md und die Zeile `heavy.sh[…]: UNVERIFIED (…)` (:1049) tragen dann keine Adresse.
- `FINDINGS` (history.csv) und `NOTES` bleiben, wie sie sind; sie erreichen den Block nicht.
- Fälle in heavy_test:
  - Der bestehende Fall `vm.py: no ssh: adminhelper@10.0.0.9 refused for 900s` (:888) erwartet in der Kopfzeile
    `no ssh: <user>@<host> refused for 900s` und keine `10.0.0.9`.
  - Ein Fall mit nackter Adresse im Grund ergibt `<ip>`.
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

### T2 — Die Wochenlauf-Zeile zeigt keine Box-Adresse  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Änderung:
- `weekly_line` maskiert die Kopfzeile wie T1 (IPv4 zu `<ip>`, `<nutzer>@<host>` zu `<user>@<host>`), bevor sie in den
  Block geht.
  - Das deckt auch Reports, die vor T1 geschrieben wurden.
- Fälle in session_status_test:
  - Ein neuester Report mit `UNVERIFIED (vm.py: no ssh: adminhelper@10.0.0.9 refused for 900s)` ergibt
    `… UNVERIFIED (vm.py: no ssh: <user>@<host> refused for 900s)`, und `10.0.0.9` steht nirgends im Block.
  - Die bestehenden Kopfzeilen ohne Adresse (`UNVERIFIED (doctor red)`, :143, :175) bleiben unverändert.
Rot vorher: Auf main steht `adminhelper@10.0.0.9` in der Zeile 4 des Blocks.
Beweis: origin/main@75ed3e09, session-status.sh :174 `head="$(head -1 "$f" …)"` und :185 `echo "$day ($n d): $head"`.
Dedup-Key: ref:scripts:session-status.sh:weekly-header-lab-address
HEAD: 75ed3e09
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
