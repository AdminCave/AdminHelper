# vHosts von nginx und Apache im Container — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-42 · Review: pro Task
Spec: docs/features/kern-monitoring-42.md (Roadmap R-1503)
Heavy: linux-full — apps/agent (Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1503: Archiv eines Container-Pfads lesen (Allowlist, Deckel, Links, Muster, Schlüssel)  [x]
Komponente: agent · Dateien: apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/probe/container_archive.go, apps/agent/internal/probe/container_archive_test.go, tasks/kern-monitoring-42.md, apps/agent/internal/execx/execx.go, apps/agent/internal/execx/execx_unix_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d50fcdc2b 2026-11-17T09:51:13+01:00
Review: approve (.ah-out/review/kern-monitoring-42/T1.verdict.json)
Änderung: Allowlist `docker cp -- <container>:<ctrpath> -` (Container-ID, einfacher absoluter Pfad). Ein Leser holt
eine Datei oder ein Verzeichnis per `runTool` und liest das tar: Deckel 4 MiB je Container, Links selbst aufgelöst
(höchstens 8 Stufen), bei einem Verzeichnis nur Einträge, die zum Muster passen; `*.key`, `*.pem` und Einträge über dem
Deckel ungelesen übersprungen. Neue Datei mit SPDX-Header. Tests mit gebauten tar-Strömen über `runTool`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5

### T2 — R-1503: nginx im Container: vHosts auf veröffentlichten Ports  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts_container.go, apps/agent/internal/probe/web_vhosts_container_test.go, apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/sensor_local.go, tasks/kern-monitoring-42.md
Änderung: Laufende Container, deren Kommando nginx nennt, mit veröffentlichtem TCP-Port: `nginx.conf` und ihre
Includes (Muster über das Verzeichnis-Archiv) zu einem Dump in der Form von `nginx -T` fügen und `nginxVhosts`
lesen lassen; nur vHosts auf einem veröffentlichten Container-Port, gemeldet mit dem Host-Port, `App` leer. `WebVhosts`
nimmt sie dazu, der Host gewinnt bei gleichem Namen und Port. Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5
Abhängt von: T1

### T3 — R-1503: Apache (httpd) im Container  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts_container.go, apps/agent/internal/probe/web_vhosts_container_test.go, apps/agent/internal/probe/web_vhosts.go, tasks/kern-monitoring-42.md
Änderung: Container, deren Kommando httpd, `httpd-foreground` oder `apache2-foreground` nennt: Hauptdatei
(`/usr/local/apache2/conf/httpd.conf`, `/etc/apache2/apache2.conf`, `/etc/httpd/conf/httpd.conf`), `ServerRoot`,
`Include`/`IncludeOptional` samt Mustern, daraus die `<VirtualHost>`-Blöcke mit `ServerName`, `ServerAlias`,
`SSLEngine`, `SSLCertificateFile` (bestehende `apacheDirectives`/`block`); Port und Host-Port wie T2.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5
Abhängt von: T2

### T4 — R-1503: Zertifikatsdatei eines Container-vHosts  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhost_cert.go, apps/agent/internal/probe/web_vhost_cert_linux_test.go, apps/agent/internal/probe/web_vhosts.go, tasks/kern-monitoring-42.md
Änderung: `webVhostCert` holt für einen Container-vHost die Zertifikatsdatei einzeln per Archiv (Deckel
`maxCertFileBytes`), sonst wie bisher; erstes Zertifikat lesen, Schlüssel in der Datei ungeparst, eine Schlüsseldatei
nie. Test: `reload_missing` und `file_days_left` für einen Container-vHost, Schlüsselname wird nie geholt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5
Abhängt von: T2

### T5 — R-1503: Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-42.md, tasks/kern-monitoring-42.md
Änderung: Abschnitt `app-module-vhosts`, Inventar-Liste und Zeile `web_domain`: vHosts im Container (Archiv-GET,
veröffentlichte Ports, Host-Port, Deckel, Schlüssel ungelesen, kein `docker exec`, Nicht-Ziele); Entwickler-Doku zum
Inventar. CHANGELOG-Fragment unter „### Added“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Dateien dieser Task
Task-Review: am Ende

## Entscheidungen
