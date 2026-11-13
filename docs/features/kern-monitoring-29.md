<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-29 — Monitoring-Katalog: Ports von Units, lauschende Container-Ports, Ziel-Alternativen, Image-Tags

Zug der Kern-Session (Roadmap R-1399, R-1384, R-1387, R-1393, R-1397). R-1383 (Nextcloud All-in-One) und R-1388
(Jitsi-Last) fahren nicht mit: Die Quellen zu Backup-Fenster bzw. Metrik-Namen sind nicht belegt (nächster Zug
`kern-monitoring-33`).

## Problem
- **R-1399 (BUG):** Eine Anwendung aus dem Paket (Instanz `unit`, etwa `gitea.service` auf 3000, slapd 389, Odoo
  8069) beansprucht ihren Port nicht; er erscheint zusätzlich als Fund des Moduls `port`. `match_inventory`
  (`apps/monitoring/app/discovery.py:378`) beansprucht nur Container, `detect.processes` und `port_hints`; das
  Inventar sagt nicht, zu welcher Unit ein Socket gehört. Beweis: `match_inventory` mit `gitea.service` und einem
  Socket `0.0.0.0:3000` ergibt `('gitea','gitea')` und `('port','tcp-3000')`.
- **R-1384:** Nextclouds Checks binden an die Compose-Dienste `app` und `cron` (`catalog/modules/nextcloud.py`); ein
  Container ohne Compose (`docker run`) oder unter anderem Dienstnamen wird erkannt, bekommt aber keinen
  `status.php`-Check (`_target_name`, `apps/monitoring/app/module_sync.py:78`).
- **R-1387:** Ein Check hat genau einen `port_hint`. Bitwardens nginx lauscht auf 8080 und mit TLS auf 8443 und
  leitet dann HTTP um; deshalb fragt das Modul nginx gar nicht über HTTP (`catalog/modules/bitwarden.py`).
- **R-1393:** `_lacks_port` (`module_sync.py:116`) kennt nur die Port-Map des Containers. Das OnlyOffice-Image
  exponiert nur 80/443, der Docservice lauscht im Container auf 8000; ein Check dort bindet nie.
- **R-1397:** Der Katalog matcht Images ohne Tag. Wiki.js 2 hat `/healthz` (mit DB-Pool), Wiki.js 3 nicht;
  `wikijs` fragt deshalb nur `/favicon.ico`.

## Ziel & Nicht-Ziele
- **Agent (R-1399, R-1393):** Das Inventar meldet je Socket die systemd-Unit seines Prozesses (`unit`, aus der
  cgroup, nur Linux; sonst leer) und je laufendem Container mit eigenem Netz die TCP-Ports, auf denen im
  Netz-Namespace des Containers außerhalb von Loopback etwas lauscht (`listening`, nur Linux). Beides additiv;
  ein älterer Monitoring-Dienst verwirft unbekannte Felder (`clean_inventory`).
- **R-1399:** Eine gefundene Unit-Instanz (und die Ersatz-Instanz `matched_by unit:`) beansprucht die Ports der
  Sockets ihrer Unit. Ohne `unit` (älterer Agent) bleibt es wie heute.
- **R-1393:** `_lacks_port` nimmt die lauschenden Ports, sobald der Scan sie meldet, sonst wie heute die
  exponierten. OnlyOffice-Image bekommt einen Container-Check `GET /healthcheck` auf 8000 (Testobjekt, 900 s).
- **R-1384:** Ein Ziel kann `image_fallback` tragen: Findet sich der Compose-Dienst nicht, bindet der Check an den
  einzigen Container der Instanz mit dem Image des Moduls, dessen Dienst kein anderer Check des Moduls nennt (oder
  an den einzelnen Container ohne Compose). Mehrdeutig bleibt er ungebunden. Nextcloud: `app` und `status`.
- **R-1387:** Ein Ziel kann geordnete Alternativen `[{port_hint, scheme}]` tragen; `probe_config` nimmt die erste,
  deren Port der Scan am Container lauschen sah, ohne gesehene Ports die erste. Bitwarden-nginx bekommt
  `GET /alive` (8443 https, sonst 8080 http).
- **R-1397:** Ein Check kann `image_tags` (Glob-Muster) tragen; er bindet nur, wenn der Tag des Zielcontainers
  passt. Die Zusammenfassung einer Instanz nennt die passenden tag-gebundenen Checks (`tag_checks`), damit ein
  Versionssprung den Fund „geändert“ macht; beim Übernehmen schaltet `_adopt` einen nicht mehr passenden
  tag-gebundenen Check aus. Wiki.js: `/healthz` für die Tags `2` und `2.*`, `/favicon.ico` bleibt für alle.
- **Nicht-Ziele:** Nextcloud AIO und Jitsi-Last (s. o.); das Zertifikat der 3CX-Weboberfläche (braucht ein Ziel
  über die Unit-Instanz hinaus auf den nginx des Hosts; neue Roadmap-Zeile); FreeBSD/Windows-Fassung von `unit`
  und `listening`; ein anderes Wire-Format zwischen Monitoring und Agent für Probes (Alternativen und Tags löst der
  Monitoring-Dienst auf, der Agent bekommt weiter einen `port_hint`).

## Betroffene Komponenten & Dateien
- Agent: `apps/agent/internal/discovery/discovery.go` (`Socket`, `Container`, `collectSockets`,
  `collectContainers`), `discovery_linux.go`/`discovery_other.go` (Nähte), `apps/agent/internal/probe/target_linux.go`
  (`namespaceListeners`, `CgroupsOf`), Tests `discovery_test.go`.
- Monitoring: `app/discovery.py` (`_socket`, `_container`, `_instances`, `match_inventory`), `app/module_sync.py`
  (`_target_name`, `_lacks_port`, `probe_config`, `_adopt`), `app/catalog/model.py` (`Target`, `Check`),
  Module `nextcloud.py`, `bitwarden.py`, `onlyoffice.py`, `wikijs.py`; Tests `test_discovery_match.py`,
  `test_module_sync.py`, `test_catalog_{nextcloud,bitwarden,onlyoffice,wikijs}.py`, `test_catalog.py`.

## Datenmodell / API / Migrationen
Keine Migration, keine öffentliche API. Das Inventar (Report-Block `discovery`) bekommt zwei additive Felder
(`sockets[].unit`, `containers[].listening`); gespeicherte Inventare ohne sie bleiben gültig. Katalog-Schema:
`Target.image_fallback`, `Target.alternatives`, `Check.image_tags` (Katalog ist Code, kein Vertrag nach außen).
Geänderte Module bekommen `version` + 1; die Katalog-Version ändert sich, `sync_catalog` legt neue Checks an
übernommenen Instanzen still an (bestehender Mechanismus).

## Externe Integrationen
- systemd-cgroup-Pfade (`/proc/<pid>/cgroup`, v2 `0::/system.slice/<unit>.service`; v1 Hierarchie `name=systemd`):
  die Unit ist die letzte Pfad-Komponente mit `.service` unter `system.slice`. Andere Slices (user, machine) bleiben
  leer.
- OnlyOffice Docs: ob der Docservice im Image auf allen Adressen oder nur auf Loopback lauscht, ist nicht verifiziert;
  lauscht er nur auf Loopback, meldet `listening` 8000 nicht und der Check bleibt ungebunden (kein Fehlalarm).
- Wiki.js 2 `/healthz`: im bestehenden Modul-Docstring beschrieben (R-1243).

## Trade-offs & Alternativen
- Unit aus der cgroup statt `systemctl status <pid>`: kein Kommando je Socket, die cgroup liest der Agent für
  Container ohnehin. Empfehlung: cgroup.
- Port-Alternativen im Monitoring auflösen statt im Agent: kein Wire-Wechsel, gemischte Versionen bleiben
  verträglich; dafür entscheidet der letzte Scan. Empfehlung: Monitoring.
- Tag-Wechsel: `tag_checks` in der Zusammenfassung statt des Tags selbst, sonst machte jedes Patch-Update den Fund
  „geändert“.

## Risiken & Rollback
- Neue Felder im Inventar wachsen den Report: `unit` ≤ 255 Zeichen je Socket, `listening` ≤ 32 Ports je Container
  (Deckel wie `ports`).
- Ein Fund `port` für einen Unit-Port verschwindet nach dem Update (gewollt; ein übernommener wird nach zwei Scans
  `gone`).
- Rollback: Revert je Task; Inventare mit den neuen Feldern liest ein älterer Dienst ohne sie.

## Doku-Impact
`docs/admin/monitoring.html` (Erkennung: Unit-Ports, lauschende Container-Ports; Modultabelle Nextcloud,
Bitwarden, OnlyOffice, Wiki.js) und `docs/developer/monitoring.html` (Bindung: `image_fallback`, Alternativen,
`image_tags`, `_lacks_port`), je DE + EN; `changelog.d/kern-monitoring-29.md`.

## Offene Fragen
Keine aus Kevins Bereich: kein API-Vertrag, keine Migration; sichtbar neu sind nur zusätzliche Checks und
weniger doppelte Port-Funde.
