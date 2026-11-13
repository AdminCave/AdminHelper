<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Katalog: Ports von Units, lauschende Container-Ports, Ziel-Alternativen, Image-Tags — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-29 · Review: pro Task
Spec: docs/features/kern-monitoring-29.md (Roadmap R-1399, R-1384, R-1387, R-1393, R-1397)
Heavy: linux-full — Inventar des Agents (`apps/agent/internal/discovery`, cgroup und Netz-Namespace der Container auf echten Boxen) und Bindung im Monitoring; kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1399, R-1393: Unit je Socket und lauschende Ports je Container im Inventar  [ ]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_linux.go, apps/agent/internal/discovery/discovery_other.go, apps/agent/internal/discovery/discovery_test.go, apps/agent/internal/probe/target_linux.go, apps/agent/internal/probe/target_freebsd.go, apps/agent/internal/probe/target_windows.go
Änderung: `Socket` bekommt `unit` (systemd-Unit des Prozesses aus seiner cgroup, `.service` unter `system.slice`,
sonst ""; je PID gecacht), `Container` bekommt `listening` (TCP-Ports, auf denen im Netz-Namespace eines laufenden
Containers mit eigenem Netz außerhalb von Loopback etwas lauscht, sortiert, gedeckelt wie `ports`; über eine
exportierte Naht um `namespaceListeners`). Nicht-Linux: leer. Tabellentests für den cgroup-Pfad (v2, v1, user-Slice,
Scope) und für `listening` über die Naht.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/discovery/ ./internal/probe/
Doku: → T7

### T2 — R-1399: Unit-Instanzen beanspruchen die Ports ihrer Unit  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_discovery_match.py
Beweis: feature/arch-monitoring-apps-1@c60316eeb: match_inventory mit gitea.service + Socket 0.0.0.0:3000 ergibt ('gitea','gitea') und ('port','tcp-3000')
Dedup-Key: bug:monitoring:app/discovery.py:match_inventory-unit-ports
Änderung: `_socket` übernimmt `unit` (Text ≤ 255, fehlt → ""). `match_inventory` beansprucht die Ports der Sockets,
deren Unit eine gefundene Unit des Moduls ist (Instanz `unit` und Ersatz-Instanz mit `matched_by unit:`). Test
zuerst rot: gitea.service + 0.0.0.0:3000 mit `unit` ergibt nur ('gitea','gitea'); ohne `unit` wie heute.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py
Doku: → T7

### T3 — R-1393: Container-Checks binden an lauschende Ports; OnlyOffice-Docservice  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_catalog_onlyoffice.py
Änderung: `_container` übernimmt `listening` (Ports, gedeckelt). `_lacks_port` nimmt `listening`, wenn der Scan es
meldet, sonst die exponierten TCP-Ports. `onlyoffice` (Version + 1) bekommt für das Image einen `http`-Check
`GET /healthcheck` auf 8000 (Testobjekt, 900 s, `status_code ne 200` kritisch); Docstring nachziehen. Tests: Port
nur in `listening` bindet, Port weder dort noch exponiert nicht, ohne `listening` wie heute.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_catalog_onlyoffice.py
Doku: → T7

### T4 — R-1384: Nextcloud ohne Compose oder unter anderem Dienstnamen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/modules/nextcloud.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_catalog_nextcloud.py
Änderung: `Target.image_fallback` (bool, nur mit `service`). `_target_name`: findet sich der Dienst nicht, bindet
ein solcher Check an den einzigen Projekt-Container mit dem Image des Moduls, dessen Dienst kein anderer Check des
Moduls nennt, bzw. an den einzelnen Container ohne Compose; mehrdeutig ungebunden mit Grund. `nextcloud` (Version
+ 1): `app` und `status` mit `image_fallback`, `cron` ohne. Der bisherige Test
`test_a_container_outside_compose_is_found_but_gets_no_status_check` wird auf das neue Verhalten umgestellt
(gewollte Verhaltensänderung, gleichwertiger Ersatz).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_catalog_nextcloud.py tests/test_catalog.py
Doku: → T7

### T5 — R-1387: Ziele mit Port-Alternativen; HTTP-Check am Bitwarden-nginx  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/modules/bitwarden.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_catalog_bitwarden.py, apps/monitoring/tests/test_catalog.py
Änderung: `Target.alternatives` (1–4 Einträge `{port_hint, scheme}`, nicht zusammen mit `port_hint`/`scheme`).
`probe_config` nimmt die erste Alternative, deren Port der letzte Scan am Container sah (`listening`, sonst
exponiert), ohne gesehene Ports die erste. `bitwarden` (Version + 1): Check `GET /alive` am Dienst `nginx`
(8443 https, 8080 http, `status_code ne 200` kritisch); Docstring nachziehen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_catalog_bitwarden.py tests/test_catalog.py
Doku: → T7
Abhängt von: T3

### T6 — R-1397: Checks je Image-Tag; Wiki.js 2 /healthz  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/model.py, apps/monitoring/app/discovery.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/modules/wikijs.py, apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_catalog_wikijs.py, apps/monitoring/tests/test_catalog.py
Änderung: `Check.image_tags` (1–8 Glob-Muster, nur mit Container-Ziel). `image_tag()` neben `image_repo`; die
Zusammenfassung einer Container-/Compose-Instanz trägt `tag_checks` (die passenden tag-gebundenen Checks), nur bei
Modulen mit solchen Checks. `probe_config` bindet einen tag-gebundenen Check nur bei passendem Tag; `_adopt`
schaltet einen nicht mehr passenden aus. `wikijs` (Version + 1): `/healthz` für `2`, `2.*`; `/favicon.ico` bleibt.
Tests: Tag 2.5 bindet beide, 3 nur favicon, `latest` nur favicon, Wechsel 2→3 macht den Fund geändert und schaltet
`/healthz` beim Übernehmen aus.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_discovery_match.py tests/test_catalog_wikijs.py tests/test_catalog.py
Doku: → T7
Abhängt von: T4

### T7 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-29.md
Änderung: Erkennung (Unit-Ports, lauschende Container-Ports), Modultabelle (Nextcloud, Bitwarden, OnlyOffice,
Wiki.js), Bindung (`image_fallback`, `alternatives`, `image_tags`, `_lacks_port`), je DE + EN; Fragment mit Added/Fixed.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-29.md
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5, T6

## Entscheidungen
- R-1383 und R-1388 fahren nicht mit (Quellen nicht belegt), nächster Zug `kern-monitoring-33`.
- Das 3CX-Zertifikat aus R-1387 wird eine eigene Zeile: es braucht ein Ziel außerhalb der Unit-Instanz (nginx des Hosts).
