# kern-agent-24 — Task-Ledger
Status: bereit · Branch: feature/kern-agent-24 · Review: pro Task
Spec: docs/features/kern-agent-24.md (Roadmap R-1760, R-1769, R-1772)
Heavy: linux-full — apps/agent (RAM-Wert des Reports, Self-Update-Client, Plattensammler FreeBSD)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1760: memory_percent ohne den ARC über c_min  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/loadgate.go, apps/agent/internal/monitor/collector_test.go, apps/agent/internal/monitor/loadgate_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @52d77b102 2026-11-25T05:08:12+01:00
Review: approve (.ah-out/review/kern-agent-24/T1.verdict.json)
Änderung: `collectMemory` zieht unter Linux und FreeBSD außerhalb eines Containers `resourceCalls.arc()` von `Used` ab (höchstens bis 0) und rechnet `memory_percent` daraus. `loadReadingOf` nimmt `100 - memory_percent` ohne zweiten ARC-Zuschlag. Tests: ZFS-Host bereinigt, Container und Windows unverändert, ARC größer als Used, Last-Tor ohne Doppelzählung. Der R-1688-Test in `loadgate_test.go` zieht mit der gewollten Verhaltensänderung um (Kevin 2026-11-25).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T4

### T2 — R-1769: Self-Update-Client prüft das Serverzertifikat wie der Server-Push  [x]
Komponente: agent · Dateien: apps/agent/internal/selfupdate/client.go, apps/agent/internal/selfupdate/client_test.go, apps/agent/internal/httpclient/httpclient.go, apps/agent/internal/httpclient/httpclient_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @551fee29b 2026-11-25T05:12:10+01:00
Review: approve (.ah-out/review/kern-agent-24/T2.verdict.json)
Änderung: Ein enrollter Host holt das Update mit dem CA-Bundle der Enrollment-Zeit und derselben Ausstellerprüfung wie `httpclient.NewMTLS`, ohne Client-Zertifikat. Der Kommentar in `client.go` beschreibt das genau. Tests: Ein enrollter Host übergeht `insecure=true` und ein abweichendes `cacert`, und ein Zertifikat eines anderen Ausstellers scheitert. Risikopfad: `security` je Task. Der Hinweis zu `reprovisionHelps` (`apps/agent/internal/frpc/sync.go:603`) wird gesichtet und als Entscheidung festgehalten.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/selfupdate/ ./internal/httpclient/
Doku: keine (Verhalten wie dokumentiert: das Self-Update vertraut dem CA-Bundle der Enrollment-Zeit)

### T3 — R-1772: FreeBSD-Plattensammler mit einer offenen Abfrage je Mount  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/disks_bounded.go, apps/agent/internal/monitor/disks_freebsd.go, apps/agent/internal/monitor/disks_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @0c37911cb 2026-11-25T05:22:30+01:00
Review: approve (.ah-out/review/kern-agent-24/T3.verdict.json)
Änderung: `boundedStats` merkt sich Mounts, deren Abfrage noch hängt, und fragt sie erst nach deren Antwort wieder; bis dahin fehlt der Mount wie bei einer Zeitüberschreitung. Ein lokaler Mount, dessen Pfad unter einem Netz-Mount liegt, wird mit Frist gelesen (reine Funktion ohne Build-Tag, unter Linux getestet). Wackler-Gegenprobe der neuen Tests mit `-count`, Summary in den Commit-Body. Nicht auf FreeBSD gefahren: Im Pool ist keine Box, der Cross-Build läuft in der Verify.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/monitor/
Doku: → T4

### T4 — Doku: RAM ohne rückforderbaren ARC, Netz-Mounts unter FreeBSD  [x]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-24.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c546177d5 2026-11-25T05:34:00+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: `collectMemory` und das Last-Tor nennen die Bereinigung um den ARC über `c_min`. Die RAM-Schwelle von `agent_resources` nennt die Abweichung von `free`. Platten unter FreeBSD: eine Abfrage je Mount, lokale Mounts unter Netz-Mounts mit Frist. Changelog-Fragment ohne Umlaute.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/agent.html DE+EN · docs/admin/monitoring.html DE+EN · changelog.d/kern-agent-24.md
Task-Review: am Ende
Abhängt von: T1, T3

## Entscheidungen
- 2026-11-25 T1 (R-1760): `collectMemory` rechnet `memory_percent` nur neu, wenn ARC abgezogen wird; sonst bleibt `UsedPercent` von gopsutil (Windows: `dwMemoryLoad`, nicht Used/Total). Fund des Task-Pruefers.
- 2026-11-25 T2 (R-1769): Hinweis zu `reprovisionHelps` (`apps/agent/internal/frpc/sync.go:603`) gesichtet, bleibt wie gebaut: `stopFrpc` deaktiviert den Dienst und loescht `frpc.toml` zusammen; ein Dienst ohne Config traegt keinen Tunnel, eine Dienstpruefung aenderte die Entscheidung nicht.
- 2026-11-25 T2 (R-1769): neuer `httpclient.NewGateway` (CA-Bundle ohne System-Roots, `verifyGatewayIssuer`, kein Client-Zertifikat) teilt `gatewayTLS` mit `NewMTLS`; der Self-Update-Client eines enrollten Hosts nimmt ihn statt `New`.
