<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Vorschlag passender Standard-Templates statt leerem Server

Roadmap R-0421 (FEAT) · Phase B von R-0420 · Kevin, Monitoring-Analyse und Lab nach der Installation v0.45.0,
2026-10-16. Stand des Codes: `origin/main@af4498a7`. Alle `datei:zeile` beziehen sich auf diesen Stand.

Hängt ab von: R-0417, R-0418, R-0419 (alle ändern `apps/agent/internal/monitor/report.go` und das Report-Beispiel
der Doku) und R-0420 (monitoring-templates, Phase A; deren Alembic-Revision ist hier `down_revision`).

## Problem / Motivation

Ein neuer Server wird nicht überwacht. Im Lab hatte ein frisch provisionierter Server nach dem ersten Push `0`
Checks und keine Template-Zuweisung. Zuweisung ist reines Opt-in (Dropdown im Server-Dialog mit Vorauswahl „keins“,
Monitoring-Tab, Tag-Bindung); Provisionierung und API weisen nichts zu. Das Docker-Template wird nie angeboten, auch
wenn Docker läuft. Die Entscheidung „keine Auto-Zuweisung nach OS-Typ“ steht in
`docs/features/monitoring-overhaul.md:50` und `:262` und gilt weiter (Kevin 2026-10-16) — gewünscht ist ein
Vorschlag, den der Admin annimmt oder ignoriert.

## Ziel & Nicht-Ziele

**Ziele (Kevin 2026-10-16: Vorschlag statt Auto-Zuweisung)**
- Der Agent meldet additiv einen Block `host` mit Betriebssystem, Plattform, Virtualisierung und erkannten
  Subsystemen (Docker, ZFS, Proxmox). Additive Report-Felder sind freigegeben (Kevin 2026-10-16).
- Der Monitoring-Dienst leitet daraus passende Standard-Templates ab. Im Monitoring-Tab eines Servers steht
  ein Vorschlag, z. B. „Vorgeschlagen: Linux Server — Standard, Docker Host“, mit **Zuweisen** und
  **Ignorieren**. Ignorieren wird je Server und Template gemerkt. Nichts passiert ungefragt.

**Nicht-Ziele (YAGNI, Kevin 2026-10-16)**
- Keine Auto-Zuweisung bei Provisionierung oder Server-Anlage (`monitoring-overhaul.md:50`).
- Kein Fallback auf `os_type` aus dem Server-Inventar für Agents ohne `host`-Block: Agents kommen aus dem
  Paket-Repo des Servers und sind nach dem Update aktuell; ein alter Agent liefert eben keinen Vorschlag.
- Der Vorschlag erscheint nur im Monitoring-Tab des Servers, nicht in der Monitoring-Übersicht.
- „Ignorieren“ ist vorerst nicht rückgängig zu machen; das Template lässt sich jederzeit von Hand zuweisen.
- Anpassungen, Tombstones und Versionierung der Templates: Vorhaben monitoring-templates (Phase A).

## Betroffene Komponenten & Dateien

**Agent (`apps/agent`)**
- `internal/monitor/report.go` — `BuildReport` `:22-77`, Report-Map `:43-48`.
- `internal/monitor/collector.go:15` — gopsutil `host` ist schon eingebunden (`host.Uptime` `:109`).
- Neu: `internal/monitor/hostfacts.go`, `internal/monitor/hostfacts_test.go`.

**Monitoring-Dienst (`apps/monitoring`)**
- `app/models.py`; `alembic/versions/` — eine neue Revision nach der Revision aus monitoring-templates T1.
- `app/template_sync.py` — `cleanup_server` `:421-455`.
- `app/routers/agent.py` — `agent_report` `:68-299` (Report ist ein freies `dict`, `:71`; Liveness `:86-91`,
  NUL-Prüfung `:96-109`).
- `app/routers/templates.py` — neue Routen neben `GET /templates/assignments/{server_id}` `:80`.
- Neu: `app/template_suggestions.py`.
- Tests: `tests/test_agent_report.py`, `tests/openapi.snapshot.json`; neu `tests/test_template_suggestions.py`.

**Desktop-UI (`apps/desktop/ui`)**
- `src/lib/api/monitoring.ts` — Template-Aufrufe `:109-184`.
- `src/components/infra/tabs/MonitoringTab.svelte` (Template-Abschnitt `:171-206`).
- `src/lib/i18n/dictionaries.ts` (DE + EN).

**Server (`apps/server`): keine Änderung.** Die neuen Routen liegen unter dem Proxy-Präfix `templates`
(`apps/server/app/modules/monitoring_proxy/router.py:59-66`).

**Desktop-E2E:** `apps/desktop/e2e/test/specs/monitoring-check.live.js` (der Orchestrator
`scripts/tests/desktop_e2e_monitoring.sh:59-66` fährt genau diese Spec; erweitert wird die Spec, nicht das Skript).

## Datenmodell / API / Migrationen

Migration und Routen sind von Kevin freigegeben (2026-10-16).

**Eine Revision `…_host_facts_suggestions`** (`down_revision` = Revision aus monitoring-templates T1)
- Neue Tabelle `monitor_host_facts`: `server_id String PK`, `os String NULL`, `platform String NULL`,
  `platform_version String NULL`, `virt_system String NULL`, `virt_role String NULL`,
  `subsystems Text NOT NULL server_default '[]'`, `updated_at DateTime`.
- Neue Tabelle `monitor_template_suggestion_dismissals`: `id String PK`, `server_id String NOT NULL` (Index),
  `builtin_slug String NOT NULL`, `dismissed_at DateTime`, `UniqueConstraint(server_id, builtin_slug)`.
- `cleanup_server` löscht beide Zeilenarten des Servers mit.

**Neue Routen (alle `require_internal`, nur über den Admin-Proxy erreichbar)**
| Methode | Pfad | Zweck | Fehler |
|---|---|---|---|
| GET | `/templates/suggestions/{server_id}` | `[{slug, templateId, templateName, reason}]` | — (leer, wenn nichts bekannt) |
| POST | `/templates/suggestions/{server_id}/dismiss` | Body `{"slug": "<builtin_slug>"}`, idempotent | 422 unbekannter Slug |

Der OpenAPI-Snapshot des Monitoring-Dienstes wächst um die beiden Pfade.

**Report-Format (additiv)**
```json
"host": {
  "os": "linux",
  "platform": "ubuntu",
  "platform_version": "24.04",
  "virtualization": {"system": "kvm", "role": "guest"},
  "subsystems": ["docker"]
}
```
Der Server liest es tolerant: `os` nur aus `{linux, windows, darwin}`, Strings auf 64 Zeichen gekürzt,
`subsystems` nur aus `{docker, zfs, proxmox}`; alles andere wird verworfen. Fehlt der Block (alter Agent),
ändert sich nichts. Die Subsysteme erkennt der Agent per `exec.LookPath` (`docker`, `zpool`, `pvesh`) — bewusst
unabhängig vom Erfolg der Collector, damit ein kaputter Plugin-Collector den Vorschlag nicht verhindert.

**Vorschlagsregel:** `linux` → `linux-base`, `windows` → `windows-base`, `docker` → `docker-host`, `zfs` →
`zfs-storage`, `proxmox` → `proxmox-host`. Vorgeschlagen wird ein Slug nur, wenn sein Template existiert,
dem Server nicht zugewiesen ist (gleich welche Quelle) und nicht ignoriert wurde.

## Externe Integrationen

- gopsutil v4.26.5 `host.PlatformInformation()` und `host.Virtualization()` (`os` aus `runtime.GOOS`; `host.Info()` bricht bei jedem Teilfehler ganz ab) —
  Felder per Quelle der eingebundenen Version (`go.mod`) beim Bau gegenprüfen; unter Windows liefert `Platform`
  den Produktnamen. Nicht verifiziert: Werte unter Proxmox-Hosts (`role: host`).
- Vorbild, nur als Begründung: Checkmk legt neu gefundene Dienste als „undecided“ ab und lässt den Admin
  entscheiden (https://docs.checkmk.com/latest/en/wato_services.html).

## Trade-offs & Alternativen

1. **Vorschlag aus Agent-Fakten vs. aus vorhandenen Report-Blöcken (`docker`, `zfs`, `proxmox`).** Die Blöcke fehlen
   bei Collector-Fehlern und geben kein OS her. Ein eigener `host`-Block ist robust. **Gewählt: `host`.**
2. **Vorschlag vs. Auto-Zuweisung.** Auto-Zuweisung wäre bequemer, ist aber seit `monitoring-overhaul.md:50`
   abgelehnt und von Kevin am 2026-10-16 bestätigt. **Gewählt: Vorschlag.**

## Risiken & Rollback

- **Report-Block `host`:** additiv; ein alter Server ignoriert ihn (`agent_report` nimmt ein freies `dict`).
  NUL-Bytes werden schon vorher abgewiesen (`agent.py:96-109`); Fehler beim Speichern der Fakten kosten nie den
  Report (eigener Commit, nur geloggt).
- **Rollback:** Revert des Merge-Commits plus `alembic downgrade` um die neue Revision; die Tabellen tragen nur
  Metadaten.

## Doku-Impact

Sichtbare Änderung, DE + EN: `docs/admin/monitoring.html` und `docs/en/admin/monitoring.html` („Templates zuweisen“
`:171-181`: Vorschlag im Monitoring-Tab, Zuweisen/Ignorieren, keine Auto-Zuweisung, ältere Agents ohne Vorschlag),
`docs/developer/monitoring.html` und EN (Report-Beispiel `:95-121` um `host`, Routen der Vorschläge),
`CHANGELOG.md`.

## Offene Fragen

Keine. Entschieden von Kevin am 2026-10-16: eigenes Vorhaben nach R-0417/R-0418/R-0419 und R-0420 Phase A;
Migration und Routen freigegeben; Vorschlag nur im Monitoring-Tab; „Ignorieren“ vorerst nicht rückgängig;
kein Fallback auf `os_type`.
