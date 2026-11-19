<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Zug 18: RDAP-Fristen, Discovery je Abschnitt, Netz-Freigaben (kern-monitoring-18)

Roadmap: R-1406, R-1302, R-1267. Kevin 2026-11-18: nach 0.47.0 jetzt bauen.

## Problem je Zeile

**R-1406 — RDAP-Abfrage: Fristen.** Die RDAP-Abfrage (`apps/monitoring/app/central/rdap.py`) folgt
Weiterleitungen; die Frist, die `fetch.get` setzt, soll die ganze Abfrage begrenzen und nicht nur einen Sprung.

**R-1302 — Discovery: gone bei stets abgeschnittenem Scan.** Der Agent meldet sein Inventar als Ganzes `partial`,
sobald irgendein Abschnitt (Units, Container, Sockets, Marker, vHosts, Ports) unvollständig ist. Der Monitoring-Dienst
erklärt eine Instanz erst nach einem vollständigen Scan für verschwunden (`_update_findings`, `full_scan`). Auf einem
Host, dessen Scan stets an derselben Stelle abgeschnitten wird (etwa mehr Ports als die Kappung), meldet er also nie
gone, auch nicht für Abschnitte, die vollständig waren.

**R-1267 — Netz-Freigaben.** nfs-, nfs4-, cifs- und smb3-Mounts (etwa `/mnt/pve/*` auf Proxmox) überwacht bisher
nur der Platten-Collector, und der fragt `statfs` ohne Timeout ab (`apps/agent/internal/monitor/collector.go`
`collectDisks`). Eine hängende Freigabe hält so den ganzen Agent-Lauf an. Ob eine Freigabe hängt, fehlt oder voll
läuft, meldet niemand.

## Ziel & Nicht-Ziele
- R-1406: eine Gesamtfrist für eine RDAP-Abfrage samt Weiterleitungen und Kandidaten.
- R-1302: Das Inventar trägt je Abschnitt, ob er vollständig ist; gone braucht nur die Vollständigkeit des
  Abschnitts, aus dem die Instanz stammt. Alte Agents ohne das Feld verhalten sich wie heute.
- R-1267 (Kevin 2026-11-18):
  - Katalog-Modul `net_share`: Die Discovery meldet jeden Netz-Mount als Fund, ein übernommener Fund bekommt einen
    Agent-Check.
  - Der Mountpunkt und der Dateisystem-Typ dürfen an den Server, die Quelle (NAS-Name, Export-Pfad) nicht.
  - Netz-Mounts verlassen die Plattenliste (`skipFSTypes`).
  - Bewertung wie bei lokalen Platten: critical, wenn die Freigabe hängt (`statfs` antwortet nicht in 10 s) oder
    nicht mehr eingehängt ist; warning ab 85 %, critical ab 95 % belegt. Intervall 5 min.
- Nicht-Ziele:
  - Freigaben, die in `/etc/fstab` stehen, aber nie eingehängt waren.
  - autofs-Mounts, die noch nicht ausgelöst sind.
  - FreeBSD und Windows.
  - Eine Sonde ins LAN (Konzept, Entscheidung 4).

## Betroffene Komponenten & Dateien
- monitoring:
  - `app/central/fetch.py` (`get`, `_Watchdog`), `app/central/rdap.py` (`probe`, `_get`) — R-1406
  - `app/discovery.py` (`clean_inventory`, `_update_findings`, `apply_discovery`, Instanzen) — R-1302, R-1267
  - `app/catalog/model.py` (`Detect`, Zielarten, Instanz), `app/catalog/sensors.py` (`APP_VIEW_TARGETS`),
    `app/module_sync.py`, `app/catalog/modules/net_share.py` (neu) — R-1267
- agent:
  - `internal/discovery/discovery.go` (`Inventory`, `Run`) — R-1302, R-1267
  - `internal/monitor/collector.go` (`skipFSTypes`) — R-1267
  - `internal/probe/target.go`, `internal/probe/sensor_app.go`, eine neue Ansicht `net_share_usage` — R-1267

## Datenmodell / API / Migrationen
- Keine Alembic-Migration: die Stempel je Abschnitt liegen im JSON des gespeicherten Inventars, wie heute
  `full_scan_at`.
- Wire-Format Agent → Monitoring, nur additiv:
  - `discovery.complete`: ein Objekt mit einem Flag je Abschnitt.
  - `discovery.shares`: eine Liste `{mountpoint, fstype}`.
  - Ein alter Dienst ignoriert beide Felder. Ein neuer Dienst liest das Inventar eines alten Agents ohne
    `complete` wie heute über `partial`.
- Neue Zielart `share` und Instanzart `share`.

## Trade-offs & Alternativen
- `statfs` im Unterprozess (`stat -f` über `execx`, Timeout 10 s) statt in einer Goroutine: Eine Goroutine, die in
  einem hängenden `statfs` steckt, bleibt bis zum Ende des Agent-Prozesses hängen, einen Unterprozess beendet das
  Timeout. Empfehlung: Unterprozess.
- Den Ablauf misst der Check, nicht der Collector: So bleibt der 5-min-Lauf frei von Netz-I/O.

## Risiken & Rollback
- R-1302 ändert, wann Funde verschwinden. Der Test deckt beide Fälle ab: ein vollständiger Abschnitt bei
  abgeschnittenem anderem, und ein alter Agent.
- Netz-Mounts verschwinden aus der Plattenliste, die Verlaufsdaten bleiben. Ein Rollback ist das Zurücknehmen
  der Commits.

## Doku-Impact
`docs/admin/monitoring.html` (Discovery, Module, Plattenliste) und `docs/developer/agent.html` sowie
`docs/developer/monitoring.html` (Inventar-Format, Zielart `share`), jeweils DE und EN; dazu
`changelog.d/kern-monitoring-18.md`.

## Offene Fragen
Keine, Kevin hat am 2026-11-18 entschieden: Katalog-Modul, raus aus der Plattenliste, Schwellen wie bei Platten,
Mountpunkt erlaubt.
