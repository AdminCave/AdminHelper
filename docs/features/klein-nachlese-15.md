<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-15 — Spec

## Problem
Neun Nachlese-Zeilen (REF) aus Prüfer-Nits, ohne gemeinsame Funktion:
- **R-1608** (arch-monitoring-neu-p0): ADR 0004 nennt „118 Fälle“, die Aufteilung (101 Szenarien, 4 benannte
  Abweichungen) fehlt; `docs/features/arch-monitoring-neu-p0.md` nennt einen Build-Test über `dist/`, gebaut ist
  `isolation.test.ts`; im Mockup (`exceptions.ts` `withoutRule`) kann der Grund-Satz die ausgenommene Regel nennen,
  wenn eine andere Regel derselben Stufe feuert.
- **R-1627** (arch-monitoring-neu-p0-abnahme): die Auswahlmarke der Serverliste folgt einer neuen Reihenfolge nicht,
  die Lagekarte zählt mit eigener Bedingung statt `needsLook`, „Filter aufheben“ setzt `more` nicht zurück, ADR 0004
  Abschnitt 3.1 nennt nicht, dass die Lagekarte erst ab 40 Servern auf 20 kappt.
- **R-1620** (kern-monitoring-47): `docs/developer/monitoring.html` (DE+EN) sagt „Was die Glocke verwirft“, gemeint
  ist, was der Hub nicht annimmt. Der zweite Teil der Zeile (Hub-POST in `toggle_check`/`delete_check` synchron, bis
  5 s im Request) wird **nicht** gebaut, siehe Entscheidungen im Ledger; er wird eine eigene Zeile.
- **R-1621** (kern-monitoring-46): `Check.instance` filtert nur beim Anlegen (`_belongs`); bekommt ein bestehender
  Katalog-Check später `instance`, bleiben seine Zeilen an anderen Instanzen, und `_update` bindet sie neu.
- **R-1623** (kern-monitoring-49): kein Test für `send_all_clears` in `sync_assignment`; der gone-Test prüft nur
  `lag_target`, nicht dass `catch_up_bell` ok sendet.
- **R-1652** (arch-monitoring-neu-p1): Docstrings `_container_object`/`_guest_object` nennen fehlende Agent-Daten,
  obwohl der Agent seit kern-agent-11 `compose_number`/`cluster_name` sendet; `barrier.wait(timeout=10)` unter der
  30-s-Frist aus `testing.md`.
- **R-1624** (kern-agent-10): Changelog nennt nicht, dass ein Prozess-Ziel busybox/toybox jetzt `count 0` meldet;
  `programName` liest den Multicall-Namen doppelt; der busybox-Linux-Test skippt ohne busybox, CI-Runner unbelegt.
- **R-1632**: i18n-Schlüssel `monitoring.services.journal.notLinux` passt im Namen nicht mehr (Text nennt Windows und
  FreeBSD).
- **R-1635**: `tasks/desktop-blocking.md`, `host-uid-guard.md`, `kern-server-7.md` stehen auf `main` auf
  `Status: bereit`, obwohl ihre PRs gemergt sind.

## Ziel / Nicht-Ziele
Jede Zeile genau wie beschrieben beheben; kein neues Verhalten außer R-1621 (eine Zeile, die nicht zur Instanz
gehört, bleibt unangetastet statt neu gebunden zu werden). Nicht-Ziel: Hub-POST asynchron machen (eigene Zeile).

## Betroffene Komponenten & Dateien
Docs (ADR 0004, Feature-Spec, `docs/developer/monitoring.html` DE+EN), `apps/desktop/ui` (Mockup `monitoring-neu`,
`dictionaries.ts`, `ServiceList.svelte`), `apps/monitoring` (`module_sync.py`, `checkers/plugins.py`, Tests), `apps/agent`
(`internal/probe`), drei Ledger-Köpfe.

## Datenmodell / API / Migrationen
Keine. R-1621 ändert nur, welche Zeilen ein Adopt/Katalog-Sync anfasst; nichts wird gelöscht.

## Trade-offs
R-1621: die Zeile bleibt „wie der Admin sie ließ“ (wie eine aus dem Katalog gefallene) statt gelöscht. Löschen wäre
datenwirksam und nicht Sache einer Nachlese.

## Doku-Impact
`monitoring.html` DE+EN (Wortlaut), ADR 0004, Feature-Spec; Changelog-Fragment für R-1624, R-1621 und die UI-Nits.

## Risiken & Rollback
Gering; je Task ein Commit, einzeln zurücknehmbar.

## Offene Fragen
Keine.
