<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Erneuerung und Provisionierung sperren die Identität — Task-Ledger
Status: aktiv · Branch: feature/agent-identity-lock · Review: am Ende
Spec: Roadmap R-0384
Heavy: linux-full — `apps/agent/internal/enroll` und `internal/provision` sind Agent-Enrollment und -Erneuerung; läuft im Sammellauf (`/feature-build` §5); Windows ohne VM: `lock_windows.go` prüft der CI-Job `agent-windows` nativ (`go test ./...`)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: `/feature-plan --kurz R-0384`; die Sperre umfasst die ganze Operation, nicht nur Staging und Commit (Antwort am Gate). Grund: Hält nur `Store` die Sperre, kann eine Erneuerung, die vor einer Provisionierung beim Issuer war, ihr Zertifikat danach zurückschreiben. Die Provisionierung hat dessen Linie aber mit `Replaces` widerrufen (R-0224, R-0293), und der Agent ist dann ebenso ausgesperrt. Hält jede Operation die Sperre vom ersten Lesen der Identität bis zum Commit, sieht die zweite das Ergebnis der ersten: Eine wartende Provisionierung nennt das erneuerte Zertifikat als `Replaces`, und eine wartende Erneuerung findet ein frisches Zertifikat und erneuert nicht. Eine Provisionierung wartet höchstens eine laufende Erneuerung ab (`run.go:119`, Timeout 30 s).

### T1 — Sperre der Identität als eigene Funktion  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/lock.go, apps/agent/internal/enroll/lock_linux.go, apps/agent/internal/enroll/lock_windows.go, apps/agent/internal/enroll/lock_test.go
Änderung: Neu ist `LockIdentity(dir string) (unlock func(), err error)`. Die Funktion legt `dir` an wie `Store` (`MkdirAll` 0700, `config.SecureDir`), öffnet die Sperrdatei `dir/agent.lock` (0600) und wartet auf eine exklusive Sperre: unter Linux `unix.Flock(LOCK_EX)`, unter Windows `windows.LockFileEx(LOCKFILE_EXCLUSIVE_LOCK)`, beides aus `golang.org/x/sys` (schon direkte Abhängigkeit). `unlock` gibt die Sperre frei und schließt die Datei. Die Plattformteile liegen nach Dateisuffix getrennt wie `securedir_linux.go`/`securedir_windows.go`; alle vier Dateien sind neu und bekommen den SPDX-Header. Tests in `lock_test.go`: (a) Ein zweites `LockIdentity` auf demselben `dir` kehrt nicht zurück, solange das erste hält, und kehrt nach `unlock` zurück (Kanäle mit Zeitgrenze, kein Sleep als Beweis). (b) Regressionstest aus der Probe: Zwei Goroutinen rufen je unter `LockIdentity` `Store` mit verschiedenen Identitäten, 3000 Durchläufe, danach prüft `tls.LoadX509KeyPair` das Paar; erwartet 0 unpassende Paare. Ohne die Sperre ist genau dieser Ablauf rot (Beweis).
Verify: bash scripts/dev/verify.sh agent --strict -- -run LockIdentity
Doku: keine (intern)
Beweis: main@aa7decf6 · Probe in einer Kopie von `apps/agent` im Scratchpad: Test mit zwei Goroutinen, die gleichzeitig `Store` mit verschiedenen Identitäten rufen, 3000 Durchläufe, `tls.LoadX509KeyPair(CertPath, KeyPath)` je Durchlauf; `go test -count=1 -run TestProbeConcurrentStoreLeavesMatchingPair ./internal/enroll/` → dreimal rot: `561 mismatches in 3000 trials`, `473 …`, `531 …`. Ursache: `stageIdentity` (`enroll.go:197`) gibt einen Commit zurück, der Key, Cert und CA nacheinander umbenennt, ohne Sperre; zwei Commits verschränken sich.
Orakel: property — nach jedem Paar gleichzeitiger Schreibvorgänge passen Key und Cert zusammen
Dedup-Key: bug:agent:enroll:store-commit-race
HEAD: aa7decf6
Semantik: docs/adr/0001-unified-pki-and-secure-deployment.md:167 — „Native: automatisch bei ~50 % Laufzeit + Überlappung → ein kurzzeitig nicht erreichbarer Issuer sperrt niemanden aus.“ Das Paar aus Key und Cert selbst beschreibt nur der Code-Kommentar an `Store` (`enroll.go:130-138`: ein neuer Key mit altem Cert „locks the agent out until it is re-provisioned“); unter docs/ steht zu gleichzeitiger Erneuerung und Provisionierung nichts.

### T2 — Erneuerung hält die Sperre von der Prüfung bis zum Commit  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/renew.go, apps/agent/internal/enroll/renew_test.go, apps/agent/internal/enroll/enroll.go
Änderung: `MaybeRenew` (`renew.go:90`) prüft zuerst wie heute `Provisioned` (nicht provisioniert: No-op, keine Sperrdatei, kein Verzeichnis), nimmt dann `LockIdentity(dir)`, prüft unter der Sperre erneut und hält sie über das Lesen des Zertifikats, `NeedsRenewal` und `renewFunc` (also `Renew` bis zu dessen `Store`, `renew.go:85`) hinweg. `Store` selbst sperrt nicht: Ein zweiter Deskriptor im selben Prozess würde sich an der Sperre des Aufrufers selbst blockieren. Der Kommentar an `Store` (`enroll.go:130-138`) nennt die Sperre als Vorbedingung der Aufrufer. Test in `renew_test.go`: Der Test hält `LockIdentity`; `MaybeRenew` in einer Goroutine (`renewFunc` ersetzt, Identität fällig) ruft `renewFunc` nicht, solange die Sperre gehalten wird, und ruft es nach `unlock`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run MaybeRenew
Doku: keine (intern)
Abhängt von: T1
Dedup-Key: bug:agent:enroll:store-commit-race

### T3 — Provisionierung hält die Sperre vom Lesen der alten Identität bis zum Commit  [ ]
Komponente: agent · Dateien: apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, CHANGELOG.md
Änderung: `runEnrollment` (`provision.go:247`) nimmt `enroll.LockIdentity(dir)` vor dem Verwerfen einer fremden Identität (`:272`) und hält sie über `checkStorable` (`:280`), das Lesen von `Replaces` (`:288`), `enroll.Submit` und `storeIdentity` (`:294`). Tests in `provision_test.go` mit dem vorhandenen Issuer-Fake: (a) Hält der Test die Sperre, schickt `runEnrollment` keine Anfrage, bis sie frei ist. (b) Speichert der Test, während er die Sperre hält, eine neue Identität (eine Erneuerung, die vorher fertig wird), nennt die Anfrage danach genau deren Fingerprint als `Replaces`, nicht den der alten. CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run RunEnrollment
Doku: CHANGELOG.md (Fixed); docs/ keine
Abhängt von: T1
Dedup-Key: bug:agent:enroll:store-commit-race
