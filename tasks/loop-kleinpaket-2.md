<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Loop-Kleinpaket 2: Zertifikatspfad im Troubleshooting, Kostendatei in der CI/CD-Doku — Task-Ledger
Status: freigegeben · Branch: feature/loop-kleinpaket-2 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-10 (kleines Fund-Paket aus R-0275 und R-0268, Loop-Futter aus Kevins Triage 2026-10-10; reine Doku; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0275, R-0268 (Kurz-Ledger ohne Spec)
Heavy: none — nur Doku unter docs/ (DE+EN); kein Code, kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Doku DE+EN im selben Commit, Doku-Smoke und docs-pairs sauber).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-10 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus zwei Zeilen, die Kevin am 2026-10-10 als
Loop-Futter triagiert hat. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der
Aufsicht. R-0242 (`scripts/install.sh`) bleibt draußen: Es fällt unter die Install-Regel für Heavy und passt nicht in
einen reinen Doku-Lauf. Zeilenangaben origin/main@d4515a1e.

### T1 — Troubleshooting: der Zertifikatspfad des Agents ist `/etc/adminhelper/identity/agent.crt`, DE und EN (R-0275)  [ ]
Komponente: scripts · Dateien: docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html
Änderung: Der Abschnitt „Agent meldet sich nicht mehr“ (`docs/admin/troubleshooting.html:82`) prüft den Ablauf mit
`openssl x509 -in /etc/adminhelper/client.crt -noout -enddate`. Diese Datei schreibt der Agent nicht:
- Die Identität liegt in `AgentPkiDir()` = `MonitorDir()/identity` (`apps/agent/internal/config/paths.go:30`).
  `MonitorDir()` ist unter Linux `/etc/adminhelper` (`paths_linux.go:21-25`).
- Die Dateien heißen `agent.key`, `agent.crt` und `ca.crt` (`apps/agent/internal/enroll/enroll.go:35-37`).
- Die FRP-Seite nennt den Pfad schon richtig (`docs/admin/frp-tunnel.html:112` und EN `:112`: `openssl x509 -in
  /etc/adminhelper/identity/agent.crt -noout -enddate`).

Die Zeile in DE heißt künftig `/etc/adminhelper/identity/agent.crt`. Die EN-Seite hat im Abschnitt „Agent doesn't
check in“ (`docs/en/admin/troubleshooting.html:61-65`) nur einen Codeblock ohne diese Prüfung. Er bekommt die Zeile
`openssl x509 -in /etc/adminhelper/identity/agent.crt -noout -enddate   # client cert expired?`, wie die FRP-Seite sie
schreibt. Die übrigen Unterschiede zwischen DE und EN in diesem Abschnitt bleiben; sie sind nicht Teil der Zeile.
Beweis: bundle/messlauf-2@d8f1d941 (Opus-Branch-Review messlauf-2, Aufsicht 2026-10-10; der Fund lag außerhalb des
Diffs). Frisch auf origin/main@d4515a1e:
- `grep -n 'client.crt' docs/admin/troubleshooting.html` → `:82`.
- `grep -rn 'client.crt' apps/agent --include=*.go | grep -v _test.go` → kein Treffer. Die vier Treffer in
  `apps/agent/internal/frpc/apply_test.go:52-81` sind Testdaten für das alte PKI-Bundle von frpc, das unter
  `/etc/frp` entpackt würde. Der Server schickt es leer (`apps/server/app/modules/provisioning/helpers.py:112`:
  `"pkiBundle": ""`).
- `grep -n 'agent.crt' docs/en/admin/troubleshooting.html` → kein Treffer.
Dedup-Key: bug:docs:troubleshooting.html:agent-cert-path
HEAD: d4515a1e
Semantik: `apps/agent/internal/enroll/enroll.go:33-37` („File layout inside the agent identity directory“: `agent.key`,
`agent.crt`, `ca.crt`) und `docs/admin/frp-tunnel.html:112` („Zertifikats-Ablauf prüfen (openssl x509 -in
/etc/adminhelper/identity/agent.crt -noout -enddate)“).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/troubleshooting.html + docs/en/admin/troubleshooting.html (die Task ist die Doku)

### T2 — CI/CD-Doku: der Worker zählt die Reviewer-Kosten aus seiner Kostendatei, DE und EN (R-0268)  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: `docs/developer/cicd.html:311-312` und EN `:305-306` sagen noch: `task-close.sh` druckt die Kosten als Zeile
`review cost_usd=<x> round=<n>`, und der Worker zählt sie in sein Lauf-Budget. Seit R-0250 (4717d016, T1 von
loop-kleinpaket-1) gilt:
- `task-close.sh` nimmt `--cost-file <datei>` und schreibt die Zeile nach einem Reviewer-Lauf mit Verdict auch dorthin
  (`scripts/dev/task-close.sh:11-16`, `:436-445`).
- `close_task` gibt je Close eine frische Datei im Loop-Verzeichnis mit und liest die Kosten nur von dort, nicht aus
  dem Close-Log, das die Suite und was sie hinterlässt mitbeschreiben (`scripts/dev/ledger-loop.sh:860-869`).
- Ohne brauchbares Verdict, bei `unknown` und bei einer Runde, deren Reviewer ohne Kostendatei lief, zählt der Deckel
  `REVIEW_BUDGET_MAX`.

Der Satz in DE und EN beschreibt das künftig, in einem Satz: Die Zeile steht weiter in der Ausgabe von task-close, der
Worker zählt aber die aus seiner Kostendatei, und unbekannte Kosten zählen mit dem Deckel.
Beweis: harness/loop-kleinpaket-1@91ca486a (Bau loop-kleinpaket-1, Worker A, 2026-10-10). Frisch auf
origin/main@d4515a1e: `grep -rn 'cost-file' docs/` → kein Treffer; `grep -n 'cost-file' scripts/dev/task-close.sh
scripts/dev/ledger-loop.sh` → `task-close.sh:11`, `:13`, `:87`, `:436`, `:444`, `ledger-loop.sh:865`.
Dedup-Key: ref:docs:cicd.html:cost-file
HEAD: d4515a1e
Semantik: keine Stelle in docs/ beschreibt die Kostendatei; das gewollte Verhalten steht im Kopf von
`scripts/dev/task-close.sh:13-16` („The worker reads the reviewer's cost from there, not from this script's output,
which the suite and whatever it leaves running share (R-0250).“) und in `AUTONOMOUS.md:263-264` („unbekannte Kosten
zählen mit ihrem Deckel“).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (die Task ist die Doku)
