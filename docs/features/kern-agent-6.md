<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Wächter, Listener-Liste und Discovery — Zug kern-agent-6

Roadmap: R-1440, R-1441, R-1442, R-1447, R-1516 (R-1448 fährt im Zug `tasks/kern-agent-7.md`).

## Problem / Motivation
- **R-1441:** Unter Linux liest der Wächter die lauschenden Sockets über gopsutil. gopsutil fasst Internet-Sockets
  nach (Typ, lokale Adresse, ferne Adresse, Zustand) zusammen (`connectionDedupKey`, gopsutil v4 `net/net_linux.go`)
  und behält dabei eine zufällige PID. Hält systemd eine Socket für einen Dienst, der sie ebenfalls hält, sieht der
  Wächter mal systemd, mal den Dienst: Das Urteil über den Aktivator hängt an der Reihenfolge.
- **R-1440:** Härtung des Wächters für Verbindungen mit Zugangsdaten (Einzelheiten privat).
- **R-1442:** Der FreeBSD-Box-Lauf ist auf `main` rot: Tests der BBB- und Caddy-Views fragen den echten
  `peerSocket` (getcred), was als Box-Nutzer `operation not permitted` ergibt.
- **R-1447:** `listeningIn` (`apps/agent/internal/discovery/discovery.go:398`) kappt mehr als 64 lauschende Ports
  still. Der Monitoring-Server hält die gekappte Liste für vollständig und wertet einen höheren Port als fehlend.
- **R-1516:** `docker ps --all` + `inspect` samt Behandlung verschwundener Container steht dreimal im Agent
  (`dockerPublications` in `sensor_local.go:267`, `wpDBContainer` in `app_wordpress_cron.go:328`,
  `inspectAllContainers` in `app_nextcloud_aio.go:114`).

## Ziel & Nicht-Ziele
- Ziel: Unter Linux sieht der Wächter jede lauschende Socket mit allen Prozessen, die sie halten. Verbindungen mit
  Zugangsdaten folgen Kevins Entscheidung vom 2026-11-16. Der FreeBSD-Box-Lauf ist grün. Discovery meldet „unbekannt“
  statt einer gekappten Liste. Es gibt nur noch einen Weg, die Container zu inspizieren.
- Nicht-Ziel: FreeBSD-rc.d-Dienste als Units (R-1448, eigener Zug: braucht eine Namensregel zwischen Agent und
  Katalog). Keine neue Konfiguration, kein API-Vertrag.

## Betroffene Komponenten & Dateien
Nur `apps/agent`:
- `internal/probe/`: `guard.go`, `target.go`, `listen_gopsutil.go` (danach nur Windows), neu `listen_linux.go`,
  `sockstat.go`, `guard_windows.go`, `sensor_local_linux.go`, `sensor_local_freebsd.go`, `sensor_local.go`,
  `app_nextcloud_aio.go`, `app_wordpress_cron.go`, Tests;
- `internal/discovery/discovery.go`.

Doku: `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `changelog.d/kern-agent-6.md`.

## Datenmodell / API / Migrationen
Keine. Der Discovery-Vertrag kennt `listening: null` schon (`apps/monitoring/app/module_sync.py` `_seen_ports`
nimmt dann die exponierten Ports).

## Externe Integrationen
- `/proc/net/tcp` und `tcp6`: Spalten nach proc_pid_net(5) (man-pages 6.19), Inode-Zuordnung über `/proc/<pid>/fd`.
- FreeBSD sockstat(1) mit `-n`; FreeBSD ip(4) zu `net.inet.ip.portrange.reserved*`; Linux ip-sysctl
  `ip_unprivileged_port_start`.

## Trade-offs & Alternativen
- **R-1441:** Den eigenen Leser von `/proc/net/tcp` ziehe ich einem Patch an gopsutil vor. Der Upstream-Schlüssel ist
  gewollt, und ein Fork bindet uns an seine Releases. Der Leser macht dieselbe Arbeit wie gopsutil (eine Datei je
  Familie, ein Gang über `/proc/*/fd`) und kostet nicht mehr.
- **R-1447:** `nil` (unbekannt) statt 64 Ports. Ein höheres Limit verschöbe das Problem nur.

## Risiken & Rollback
- Neuer Linux-Leser: Ein Fehler im Leser lässt den Wächter fail-closed abweisen. Die Gegenprobe ist der Vergleich mit
  gopsutil im Test.
- R-1440: Checks mit Zugangsdaten auf bestimmten Zielen werden `not_allowed`. Der Ausweg ist ein Unit- oder
  Container-Ziel. Die Doku nennt die Regel.
- Rollback: je Task ein Commit, einzeln revertierbar.

## Doku-Impact
`docs/admin/monitoring.html` DE+EN: Regel für Fühler mit Zugangsdaten, Discovery-Ports „unbekannt“ ab 64. Dazu
`changelog.d/kern-agent-6.md`.

## Offene Fragen
Keine: R-1440 hat Kevin am 2026-11-16 entschieden.
