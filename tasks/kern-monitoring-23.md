# Monitoring: frps-Ports ohne Fehlalarm — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-23 · Review: am Ende
Spec: docs/features/kern-monitoring-23.md (Roadmap R-1375)
Heavy: linux-full — apps/agent (Protokoll-Erkennung) und apps/monitoring (Katalog-Modul); geht in den nächtlichen Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1375: Schließen nach gelungenem Connect ist ok  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/sensor_proto_test.go, apps/agent/internal/probe/discover.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @487620f55 2026-11-12T12:24:22+01:00
Review: am Ende (Branch-Review)
Änderung: `recognizeOn` wertet eine Gegenstelle, die nach dem Connect ohne erkennbares Protokoll schließt, als
`unknown` mit `ok: true` (in TLS `tls`) statt `closed`; schließt sie schon vor `HEAD`, versucht `recognize` noch TLS.
Connect-Fehler (refused, Timeout) bleiben ein Fehlschlag. Tests: Listener, der nach dem TLS-Handshake schließt
(`tls`, ok); TLS-Listener mit SNI-Zwang, der ohne passenden Namen schließt (ok); Listener, der sofort schließt
(`unknown`, ok); geschlossener Port bleibt nicht ok. Doc-Kommentar von `RecognizePort` ohne `closed`.
Beweis: apps/agent/internal/probe/sensor_proto.go:1022 auf main@1b19e1f71 (`closed` ohne `ok`); Dedup-Key: BUG:agent:sensor_proto.go:recognizeOn-closed
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: → T3

### T2 — R-1375: Katalog-Modul frps beansprucht den frps-Container  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/frps.py, apps/monitoring/tests/test_catalog_frps.py, apps/monitoring/tests/test_discovery_match.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5ced858e1 2026-11-12T12:31:15+01:00
Review: am Ende (Branch-Review)
Änderung: neues Modul `frps` (SPDX-Header), `detect.container_images` `ghcr.io/admincave/adminhelper/frps` und
`snowdreamtech/frps`, `instance: container`, ein Check `running` (Sensor `container`, `state != running` →
critical). Tests: Katalog lädt das Modul fehlerfrei; ein Inventar mit frps-Container und veröffentlichten Ports
7000/7443 ergibt die Instanz `frps` und keine `port`-Instanz `tcp-7000`/`tcp-7443`; ein fremder Port daneben
bleibt eine `port`-Instanz.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_frps.py tests/test_discovery_match.py tests/test_catalog.py
Doku: → T3

### T3 — R-1375: Doku Modul-Katalog und Port-Check, Changelog  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-23.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ce096d0ca 2026-11-12T12:43:06+01:00
Review: am Ende (Branch-Review)
Änderung: Modul-Abschnitt nennt drei Module (`frps`: erkannt am Container, Check Containerzustand, seine Ports sind
keine `port`-Instanzen); Port-Check: schließt der Dienst nach dem Connect ohne erkennbares Protokoll, ist das ok
(`unknown`/`tls`), critical nur, wenn der Connect scheitert; alte frps-Port-Instanzen werden ein Fund „gone“.
Changelog `### Fixed`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html · docs/en/admin/monitoring.html · changelog.d/kern-monitoring-23.md
Task-Review: am Ende
Abhängt von: T1, T2

## Entscheidungen
