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

### T1 — Sperre der Identität als eigene Funktion  [x]
Komponente: agent · Dateien: apps/agent/internal/enroll/lock.go, apps/agent/internal/enroll/lock_linux.go, apps/agent/internal/enroll/lock_windows.go, apps/agent/internal/enroll/lock_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6609e6e4 2026-10-16T11:21:59+02:00
Review: am Ende (Branch-Review)
Änderung: Neu ist `LockIdentity(dir string) (unlock func(), err error)`. Die Funktion legt `dir` an wie `Store` (`MkdirAll` 0700, `config.SecureDir`), öffnet die Sperrdatei `dir/agent.lock` (0600) und wartet auf eine exklusive Sperre: unter Linux `unix.Flock(LOCK_EX)`, unter Windows `windows.LockFileEx(LOCKFILE_EXCLUSIVE_LOCK)`, beides aus `golang.org/x/sys` (schon direkte Abhängigkeit). `unlock` gibt die Sperre frei und schließt die Datei. Die Plattformteile liegen nach Dateisuffix getrennt wie `securedir_linux.go`/`securedir_windows.go`; alle vier Dateien sind neu und bekommen den SPDX-Header. Tests in `lock_test.go`: (a) Ein zweites `LockIdentity` auf demselben `dir` kehrt nicht zurück, solange das erste hält, und kehrt nach `unlock` zurück (Kanäle mit Zeitgrenze, kein Sleep als Beweis). (b) Regressionstest aus der Probe: Zwei Goroutinen rufen je unter `LockIdentity` `Store` mit verschiedenen Identitäten, 3000 Durchläufe, danach prüft `tls.LoadX509KeyPair` das Paar; erwartet 0 unpassende Paare. Ohne die Sperre ist genau dieser Ablauf rot (Beweis).
Verify: bash scripts/dev/verify.sh agent --strict -- -run LockIdentity
Doku: keine (intern)
Beweis: main@aa7decf6 · Probe in einer Kopie von `apps/agent` im Scratchpad: Test mit zwei Goroutinen, die gleichzeitig `Store` mit verschiedenen Identitäten rufen, 3000 Durchläufe, `tls.LoadX509KeyPair(CertPath, KeyPath)` je Durchlauf; `go test -count=1 -run TestProbeConcurrentStoreLeavesMatchingPair ./internal/enroll/` → dreimal rot: `561 mismatches in 3000 trials`, `473 …`, `531 …`. Ursache: `stageIdentity` (`enroll.go:197`) gibt einen Commit zurück, der Key, Cert und CA nacheinander umbenennt, ohne Sperre; zwei Commits verschränken sich.
Orakel: property — nach jedem Paar gleichzeitiger Schreibvorgänge passen Key und Cert zusammen
Dedup-Key: bug:agent:enroll:store-commit-race
HEAD: aa7decf6
Semantik: docs/adr/0001-unified-pki-and-secure-deployment.md:167 — „Native: automatisch bei ~50 % Laufzeit + Überlappung → ein kurzzeitig nicht erreichbarer Issuer sperrt niemanden aus.“ Das Paar aus Key und Cert selbst beschreibt nur der Code-Kommentar an `Store` (`enroll.go:130-138`: ein neuer Key mit altem Cert „locks the agent out until it is re-provisioned“); unter docs/ steht zu gleichzeitiger Erneuerung und Provisionierung nichts.

### T2 — Erneuerung hält die Sperre von der Prüfung bis zum Commit  [x]
Komponente: agent · Dateien: apps/agent/internal/enroll/renew.go, apps/agent/internal/enroll/renew_test.go, apps/agent/internal/enroll/enroll.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a85922fc 2026-10-16T11:27:12+02:00
Review: am Ende (Branch-Review)
Änderung: `MaybeRenew` (`renew.go:90`) prüft zuerst wie heute `Provisioned` (nicht provisioniert: No-op, keine Sperrdatei, kein Verzeichnis), nimmt dann `LockIdentity(dir)`, prüft unter der Sperre erneut und hält sie über das Lesen des Zertifikats, `NeedsRenewal` und `renewFunc` (also `Renew` bis zu dessen `Store`, `renew.go:85`) hinweg. `Store` selbst sperrt nicht: Ein zweiter Deskriptor im selben Prozess würde sich an der Sperre des Aufrufers selbst blockieren. Der Kommentar an `Store` (`enroll.go:130-138`) nennt die Sperre als Vorbedingung der Aufrufer. Test in `renew_test.go`: Der Test hält `LockIdentity`; `MaybeRenew` in einer Goroutine (`renewFunc` ersetzt, Identität fällig) ruft `renewFunc` nicht, solange die Sperre gehalten wird, und ruft es nach `unlock`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run MaybeRenew
Doku: keine (intern)
Abhängt von: T1
Dedup-Key: bug:agent:enroll:store-commit-race

### T3 — Provisionierung hält die Sperre vom Lesen der alten Identität bis zum Commit  [x]
Komponente: agent · Dateien: apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @0e883e5d 2026-10-16T11:34:02+02:00
Review: am Ende (Branch-Review)
Änderung: `runEnrollment` (`provision.go:247`) nimmt `enroll.LockIdentity(dir)` vor dem Verwerfen einer fremden Identität (`:272`) und hält sie über `checkStorable` (`:280`), das Lesen von `Replaces` (`:288`), `enroll.Submit` und `storeIdentity` (`:294`). Tests in `provision_test.go` mit dem vorhandenen Issuer-Fake: (a) Hält der Test die Sperre, schickt `runEnrollment` keine Anfrage, bis sie frei ist. (b) Speichert der Test, während er die Sperre hält, eine neue Identität (eine Erneuerung, die vorher fertig wird), nennt die Anfrage danach genau deren Fingerprint als `Replaces`, nicht den der alten. CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run RunEnrollment
Doku: CHANGELOG.md (Fixed); docs/ keine
Abhängt von: T1
Dedup-Key: bug:agent:enroll:store-commit-race

Branch-Review 2026-10-16 (security, reviewer, tester): request_changes. Kevin am selben Tag: Wartezeit der Sperre begrenzen und die Erneuerung erst nach der Fälligkeitsprüfung sperren (T4); die Box-Prüfung auf das Zertifikat als eigene Task im Branch verschärfen (T5, Harness-Pfad auf Kevins Wort, den PR merged Kevin).

### T4 — Sperre mit Frist; Erneuerung sperrt erst, wenn sie fällig ist  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/lock.go, apps/agent/internal/enroll/lock_linux.go, apps/agent/internal/enroll/lock_windows.go, apps/agent/internal/enroll/lock_test.go, apps/agent/internal/enroll/renew.go, apps/agent/internal/enroll/renew_test.go, apps/agent/internal/provision/provision_test.go
Änderung: Eine Sperre, die ein anderer Prozess nicht freigibt, darf weder die Provisionierung noch den Dienst-Zyklus unbegrenzt anhalten. `LockIdentity` wartet höchstens eine Frist (Paket-Variable, 60 s; Tests verkürzen sie): unter Linux `flock(LOCK_EX|LOCK_NB)` in einer Schleife mit kurzer Pause, unter Windows `LockFileEx` mit `LOCKFILE_FAIL_IMMEDIATELY`; nach Ablauf ein Fehler, der die Sperrdatei nennt. Unter Windows nimmt `LockIdentity` nur eine Sperrdatei, deren Eigentümer SYSTEM oder die Administratoren sind (`GetSecurityInfo`), sonst ein klarer Fehler; die Entscheidung über den Eigentümer-SID ist eine eigene, testbare Funktion. `MaybeRenew` (`renew.go`) prüft `Provisioned` und die Fälligkeit zuerst ohne Sperre (nicht fällig: keine Sperre), nimmt dann die Sperre und prüft beides unter ihr erneut; ein Fehler der Sperre kommt als Fehler zurück, `maybeRenewIdentity` (`run.go:111-128`) protokolliert ihn und der Zyklus läuft weiter. Tests: die Frist läuft ab, wenn ein zweiter Deskriptor die Sperre hält (Fehler statt Hängen); `MaybeRenew` mit gehaltener Sperre kehrt innerhalb der Frist mit Fehler zurück, ohne `renewFunc`; eine nicht fällige Identität nimmt keine Sperre; Fehlerpfade (`agent.lock` als Verzeichnis: `LockIdentity` liefert einen Fehler, `MaybeRenew` gibt `(false, err)` ohne `renewFunc`, `runEnrollment` schickt keine Anfrage); die Eigentümer-Entscheidung mit SYSTEM, Administratoren und einem fremden SID (Windows, CI-Job `agent-windows`). Die bestehenden Tests aus T1 bis T3 bleiben grün.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Lock|MaybeRenew|RunEnrollment
Doku: keine (intern; der CHANGELOG-Eintrag aus T3 deckt das Verhalten)
Abhängt von: T3
Dedup-Key: bug:agent:enroll:store-commit-race

### T5 — Box-Prüfung verlangt das Zertifikat, nicht irgendeine Datei  [ ]
Komponente: scripts · Dateien: scripts/tests/box_agentbox.sh, scripts/tests/box_agentbox_rpm.sh
Änderung: `box_agentbox.sh:56` und `box_agentbox_rpm.sh:38` prüfen `test -f …/agent.crt || ls …/identity/ | grep -q .`; seit T1 liegt nach jeder Provisionierung `agent.lock` im Verzeichnis, und ein gescheitertes Enrollment (best-effort, `provision` endet trotzdem mit `AGENT_PROVISION_OK`) meldet dann `AGENT_CERT_OK` bzw. `RPM_CERT_OK` (`multibox.sh:219`, `:237`). Der `|| ls`-Zweig fällt in beiden weg, geprüft wird `test -s …/agent.crt`. Vorher in der Geschichte der Zeile nachsehen (`git log --follow -S`), ob der Fallback einen Grund hatte, und ihn im Commit nennen. Die Box-Skripte laufen nur auf einer VM; der hermetische Teil ist `multibox_test.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Dedup-Key: bug:agent:enroll:store-commit-race
