<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-1 — Task-Ledger
Status: geplant · Branch: feature/kern-agent-1 · Review: pro Task
Spec: docs/features/kern-agent-1.md (Roadmap R-0884, R-0885, R-0929, R-0878, R-0879, R-0881, R-0951)
Heavy: linux-full — apps/agent: frpc-Abgleich, TLS-Pin, Monitor-Befehle und run --once laufen im Sammellauf (go agent, agent_monitoring, repo_build)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@fd3a3b32`, vor dem Schreiben neu greppen; Pfade ohne Präfix unter
`apps/agent/`. Neue Code-Strings englisch, CHANGELOG umlautfrei in `changelog.d/kern-agent-1.md`. `security`
zusätzlich bei T1, T2, T3 (und wo `review.sh risk` es verlangt). Einzelheiten der SEC-Zeilen privat.

### T1 — frpc-Abgleich: Reload ohne systemd, kein Hash-Verlust beim Abbruch (R-0884, R-0879)  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_test.go, changelog.d/kern-agent-1.md
Änderung: `startFrpc` (`internal/frpc/sync.go:357`) lädt bei einem Fehler von `isActive` über die Admin-API, wenn ein Reload erlaubt ist, der gemeinsame Teil dem gestarteten entspricht und frpc auf seinem Admin-Port lauscht; sonst Fehler wie bisher. Ist `ctx` beendet, kehrt `startFrpc` vor `startedOn` (`:391`) zurück, `.started-hash` bleibt. Tests je Regel über die Seams, zuerst rot.
Beweis: Code-Lesung feature/agent-run-ctx@f3c2b1db internal/frpc/sync.go startFrpc (R-0879); Test: ctx beendet während reloadService → .started-hash noch vorhanden
Dedup-Key: bug:agent:sync.go:startFrpc-hash-on-cancel
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/...
Doku: changelog.d/kern-agent-1.md

### T2 — Direkter Pin prüft die Gültigkeit (R-0885)  [ ]
Komponente: agent · Dateien: apps/agent/internal/httpclient/httpclient.go, apps/agent/internal/httpclient/cafp_test.go, changelog.d/kern-agent-1.md
Änderung: `verifyAnchorFingerprint` (`internal/httpclient/httpclient.go:154`) prüft beim direkt gepinnten Zertifikat (`:176-178`) die Gültigkeit wie der Weg über die CA. Test zuerst rot: abgelaufenes, direkt gepinntes Zertifikat → abgewiesen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/httpclient/...
Doku: changelog.d/kern-agent-1.md

### T3 — Schlüssel der Server-TOML begrenzt prüfen (R-0929)  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/servertoml.go, apps/agent/internal/frpc/servertoml_test.go, changelog.d/kern-agent-1.md
Änderung: `keyTable.add` (`internal/frpc/servertoml.go:130-146`) bzw. die Zeilenprüfung davor weist Schlüssel ab, die mehr Segmente tragen, als der Server je schreibt; Meldung über `refuse`. Test zuerst rot: Schlüssel mit sehr vielen Segmenten → abgewiesen, ohne alle Präfixe zu bauen.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/...
Doku: changelog.d/kern-agent-1.md

### T4 — Monitor-Befehle: WaitDelay als Erfolg, Abbruch eigene Meldung (R-0878)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/updates_linux.go, apps/agent/internal/monitor/services.go, apps/agent/internal/monitor/services_test.go, changelog.d/kern-agent-1.md
Änderung: `runTimed` (`internal/monitor/plugins.go:61`) und `runTimedEnv` (`internal/monitor/updates_linux.go:38`) geben bei `exec.ErrWaitDelay` die Ausgabe ohne Fehler zurück; `commandFailure` (`internal/monitor/services.go:41`) meldet `context.Canceled` als Abbruch statt „did not start“. Tests zuerst rot.
Beweis: Code-Lesung feature/agent-run-ctx@f3c2b1db internal/monitor/services.go:41-50; Test: commandFailure(context.Canceled) ≠ "<name> did not start"
Dedup-Key: bug:agent:services.go:commandFailure-waitdelay
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: changelog.d/kern-agent-1.md

### T5 — `run --once` endet über ctx bei SIGINT/SIGTERM (R-0881)  [ ]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/run.go, apps/agent/cmd/adminhelper-agent/run_test.go, changelog.d/kern-agent-1.md
Änderung: `runCmd` (`cmd/adminhelper-agent/run.go:64-65`) startet `runOnce` mit einem `signal.NotifyContext` wie `runLoop` (`:84`). Test: ein Signal beendet den ctx des Durchlaufs (über einen Seam, ohne echtes Signal an den Testprozess, falls nötig).
Dedup-Key: ref:agent:run.go:once-no-signal-handler
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/...
Doku: changelog.d/kern-agent-1.md

### T6 — Paket-Hinweis nennt `--token-stdin` (R-0951)  [ ]
Komponente: agent · Dateien: apps/agent/deb/DEBIAN/postinst, apps/agent/rpm/adminhelper-agent.spec, apps/agent/cmd/adminhelper-agent/packaging_rpm_test.go, changelog.d/kern-agent-1.md
Änderung: Der Einrichtungs-Hinweis in `deb/DEBIAN/postinst:32`, `rpm/adminhelper-agent.spec:94` und in der Fixture `cmd/adminhelper-agent/packaging_rpm_test.go:54` gibt den Token über stdin (`--token-stdin`) statt als Argument, wie `docs/admin/agent-deployment.html`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./cmd/...
Doku: changelog.d/kern-agent-1.md

## Entscheidungen
