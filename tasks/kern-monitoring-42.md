# vHosts von nginx und Apache im Container — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-42 · Review: pro Task
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

### T2 — R-1503: nginx im Container: vHosts auf veröffentlichten Ports  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts_container.go, apps/agent/internal/probe/web_vhosts_container_test.go, apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/sensor_local.go, tasks/kern-monitoring-42.md, apps/agent/internal/probe/target.go, apps/agent/internal/probe/container_archive.go, apps/agent/internal/probe/container_archive_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @7d363bb87 2026-11-17T10:00:41+01:00
Review: approve (.ah-out/review/kern-monitoring-42/T2.verdict.json)
Änderung: Laufende Container, deren Kommando nginx nennt, mit veröffentlichtem TCP-Port: `nginx.conf` und ihre
Includes (Muster über das Verzeichnis-Archiv) zu einem Dump in der Form von `nginx -T` fügen und `nginxVhosts`
lesen lassen; nur vHosts auf einem veröffentlichten Container-Port, gemeldet mit dem Host-Port, `App` leer. `WebVhosts`
nimmt sie dazu, der Host gewinnt bei gleichem Namen und Port. Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5
Abhängt von: T1

### T3 — R-1503: Apache (httpd) im Container  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts_container.go, apps/agent/internal/probe/web_vhosts_container_test.go, apps/agent/internal/probe/web_vhosts.go, tasks/kern-monitoring-42.md, apps/agent/internal/probe/web_vhosts_container_apache.go, apps/agent/internal/probe/web_vhosts_container_apache_test.go, apps/agent/internal/probe/container_archive.go, apps/agent/internal/probe/container_archive_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6d4537744 2026-11-17T10:10:23+01:00
Review: approve (.ah-out/review/kern-monitoring-42/T3.verdict.json)
Änderung: Container, deren Kommando httpd, `httpd-foreground` oder `apache2-foreground` nennt: Hauptdatei
(`/usr/local/apache2/conf/httpd.conf`, `/etc/apache2/apache2.conf`, `/etc/httpd/conf/httpd.conf`), `ServerRoot`,
`Include`/`IncludeOptional` samt Mustern, daraus die `<VirtualHost>`-Blöcke mit `ServerName`, `ServerAlias`,
`SSLEngine`, `SSLCertificateFile` (bestehende `apacheDirectives`/`block`); Port und Host-Port wie T2.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5
Abhängt von: T2

### T4 — R-1503: Zertifikatsdatei eines Container-vHosts  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhost_cert.go, apps/agent/internal/probe/web_vhost_cert_linux_test.go, apps/agent/internal/probe/web_vhosts.go, tasks/kern-monitoring-42.md, apps/agent/internal/probe/web_vhosts_container.go, apps/agent/internal/probe/web_vhosts_container_test.go, apps/agent/internal/probe/web_vhosts_container_apache.go, apps/agent/internal/probe/web_vhosts_container_apache_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @659e25dda 2026-11-17T10:19:26+01:00
Review: approve (.ah-out/review/kern-monitoring-42/T4.verdict.json)
Änderung: `webVhostCert` holt für einen Container-vHost die Zertifikatsdatei einzeln per Archiv (Deckel
`maxCertFileBytes`), sonst wie bisher; erstes Zertifikat lesen, Schlüssel in der Datei ungeparst, eine Schlüsseldatei
nie. Test: `reload_missing` und `file_days_left` für einen Container-vHost, Schlüsselname wird nie geholt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5
Abhängt von: T2

### T5 — R-1503: Doku DE+EN und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-42.md, tasks/kern-monitoring-42.md, apps/agent/internal/probe/web_vhost_cert.go, apps/agent/internal/probe/web_vhost_cert_linux_test.go, apps/agent/internal/probe/web_vhosts_container.go, apps/agent/internal/probe/web_vhosts_container_apache.go, docs/developer/agent.html, docs/en/developer/agent.html, docs/features/kern-monitoring-42.md
Evidenz: run.sh[quick] agent scripts: 8 passed, 0 failed, 10 skipped @6657308ff 2026-11-17T11:03:04+01:00
Review: approve (.ah-out/review/kern-monitoring-42/T5.verdict.json)
Änderung: Abschnitt `app-module-vhosts`, Inventar-Liste und Zeile `web_domain`: vHosts im Container (Archiv-GET,
veröffentlichte Ports, Host-Port, Deckel, Schlüssel ungelesen, kein `docker exec`, Nicht-Ziele); Entwickler-Doku zum
Inventar. CHANGELOG-Fragment unter „### Added“.
Verify: bash scripts/dev/verify.sh agent scripts --strict
Doku: die Dateien dieser Task

## Entscheidungen
- T2: Ein Container, in dem keiner der bekannten Pfade (`/etc/nginx/nginx.conf`, `/usr/local/nginx/conf/nginx.conf`
  oder das `-c` seines Kommandos) eine Hauptdatei liefert, zählt als kein nginx, ohne Fehler.
- T1/T2: Ein passender Eintrag über dem Datei-Deckel oder ein Archiv über dem Container-Budget wird nicht still
  übersprungen, sondern macht den Container zum Fehler (Liste unvollständig). Das entspricht den Risiken der Spec,
  der Ledger-Text von T1 („ungelesen übersprungen“) gilt nur für nicht passende und schlüsselartige Einträge.
- T1/T2: Jeder Exit ≠ 0 von `docker cp` zählt als „Pfad nicht da“: stderr wird verworfen, damit kein Pfad in eine
  Meldung gerät; ein Daemon, der nicht antwortet, fällt schon bei `docker ps`/`inspect` als Fehler auf.
- T2: Ein Wildcard-Muster nimmt keinen Namen mit führendem Punkt (nginx glob(3) ohne GLOB_PERIOD, Apache
  APR_FNM_PERIOD); `path.Match` täte es (Nit des T1-Prüfers).
- T3: Im Container fehlt `apachectl -S`: jeder `<VirtualHost>` zählt, auch einer in `<IfModule>`/`<IfDefine>`, der
  nicht geladen würde; ein Block ohne `ServerName` meldet nur seine Aliase (wie auf dem Host). Erkannt wird Apache
  am Kommando `httpd`, `httpd-foreground`, `apache2`, `apache2-foreground`, `apache2ctl` oder `apachectl`.
- T3 (Nit des T2-Prüfers): Ein Include, dessen Verzeichnis selbst ein Muster ist, macht den Container zum Fehler
  (`errContainerPattern`, Liste unvollständig), statt still ausgelassen zu werden.
- T4: Die Zertifikatsdatei eines Container-vHosts holt `webVhostCert` per `fileOf` mit `keyFileName` (`*.key`):
  ein Name auf `.key` und ein Link auf einen wird nie angefragt; `.pem` bleibt erlaubt (Zertifikate enden oft
  darauf, ein Schlüssel in derselben Datei bleibt ungeparst wie auf dem Host). Apache-vHosts tragen die Datei nur
  mit `SSLEngine on`.
- T4 (Nit des T3-Prüfers): Debians `mods-enabled` (LoadModule und Modul-Einstellungen, kein `<VirtualHost>`) liest
  der Agent im Container nicht: jeder Eintrag ist ein Link und kostete ein eigenes `docker cp` (Regel 2026-11-09,
  Monitoring kostet keine Dienst-Leistung). Ein Verzeichnis-Include liest nur die oberste Ebene (Apache auch
  Unterverzeichnisse); der Agent listet keine Verzeichnisbäume, ein vHost dort fehlt.
- T5 (Nits des T4-Prüfers): Die Fehler des Container-Lesers beim Zertifikat sagt `containerCertErr` in den Worten
  von `readCapped` („is not in its container“, „is larger than … bytes“), statt von der Konfiguration zu sprechen;
  T5 trägt dafür Code und wird von Task-Prüfer geprüft (Verify `agent scripts`).
