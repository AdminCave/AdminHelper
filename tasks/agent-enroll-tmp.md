<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Provisionierung und Erneuerung teilen keine Temp-Dateien mehr — Task-Ledger
Status: geplant · Branch: feature/agent-enroll-tmp · Review: am Ende
Spec: Roadmap R-0308
Heavy: linux-full — `apps/agent/internal/enroll` (Store, Renew, CheckStorable) ist Agent-Enrollment; läuft im Sammellauf (`/feature-build` §5); Windows ohne VM: kein Build-Tag, `agent-windows` fährt `go test` nativ
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Risikopfad (`apps/agent/internal/enroll/*`, PKI/mTLS): Branch-Review zusätzlich mit `security`.

### T1 — Staging und CheckStorable mit eigenen Temp-Namen je Aufruf  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/enroll.go, apps/agent/internal/enroll/enroll_test.go, CHANGELOG.md
Änderung: `stageIdentity` (`enroll.go:196`) und `CheckStorable` (`enroll.go:160`) schreiben heute dieselben festen Namen `agent.key.tmp`, `agent.crt.tmp`, `ca.crt.tmp` (`tmpSuffix` `:126`); läuft eine Provisionierung (`adminhelper-agent provision` → `CheckStorable`) zwischen Staging und Commit einer Erneuerung (Dienst → `Renew` → `Store`), überschreibt die Probe die gestagten Dateien, und die Erneuerung benennt die Probe-Bytes als `agent.key`/`agent.crt`/`ca.crt` ein. Ein Helfer legt jede Temp-Datei per `os.CreateTemp` im Zielverzeichnis an (Muster `<name>.*.tmp`, write, Sync, Chmod, Close, bei Fehler Remove); `stageIdentity` und `CheckStorable` nutzen ihn, `CheckStorable` räumt genau seine eigenen Dateien. Neuer Test `TestCheckStorableDuringAStagedRenewKeepsTheRenewal` (Beweis unten). Die Tests, die heute ein Verzeichnis am festen `.tmp`-Pfad als Blocker nutzen (`TestStageIdentityCleansUpStagedTempsOnWriteError` `enroll_test.go:197`, `TestCheckStorableReportsAStagedFileThatCannotBeWritten` `:282`), bekommen einen Seam (`createTemp`) statt des Blockers; Namen und Zusicherungen bleiben. CHANGELOG unter Fixed.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: CHANGELOG (Fixed)
Beweis: main@c18098a4 · Test oben als Kopie auf HEAD (`git archive`), `go test ./internal/enroll -run TestCheckStorableDuringAStagedRenewKeepsTheRenewal -count=1` → dreimal rc 1, identisch: `agent.key: erwartet die Erneuerung "-----BEGIN PRIVATE KEY--", beobachtet "xxxxxxxxxxxxxxxxxxxxxxxx"` (ebenso `agent.crt`, `ca.crt`)
Orakel: crash — die Identität auf Platte ist nach dem Rennen unbrauchbar
Dedup-Key: bug:agent:enroll:checkstorable-tmp-names
HEAD: c18098a4
Semantik: docs/admin/agent-deployment.html:148 — „Cert + Key landen unter <code>/etc/adminhelper/identity/</code> (Key <code>0600</code>) … und erneuert es automatisch bei ~50 % Laufzeit.“; dazu `docs/adr/0001-unified-pki-and-secure-deployment.md:167-168` — „Native: automatisch bei ~50 % Laufzeit + Überlappung → ein kurzzeitig nicht erreichbarer Issuer sperrt niemanden aus.“
