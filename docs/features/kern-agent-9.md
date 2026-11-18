<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-9 — Exponierte Container-Ports jenseits der Kappung (R-1524)

## Problem / Motivation
Der Agent meldet je Container höchstens 64 exponierte Ports (`maxContainerPorts`,
`apps/agent/internal/discovery/discovery.go:521`, nach Port sortiert gekürzt); der Server kürzt ebenso
(`MAX_CONTAINER_PORTS`, `apps/monitoring/app/discovery.py:52`). Fehlen die lauschenden Ports (`listening` null),
fällt `_seen_ports` (`apps/monitoring/app/module_sync.py:211`) auf die exponierten zurück. Ist die Liste gekappt,
gilt ein Port jenseits des Schnitts als fehlend: `_lacks_port` bindet den Check nicht („container … has no port …“),
`_alternative` wählt die falsche Alternative oder keine.

## Ziel & Nicht-Ziele
Ziel: eine exponierte Liste, die die Grenze erreicht, gilt wie eine unbekannte (keine gesehenen Ports, der Agent
entscheidet), so wie `listeningIn` eine Liste über der Grenze schon als unbekannt meldet.
Nicht-Ziel: die Grenze anheben oder den Agent-Vertrag ändern (ein Abschneide-Flag); der Agent bleibt unverändert.

## Betroffene Komponenten & Dateien
monitoring: `apps/monitoring/app/module_sync.py` (`_seen_ports`), `apps/monitoring/tests/test_module_sync.py`,
`changelog.d/kern-agent-9.md`.

## Datenmodell / API / Migrationen
Keine. Keine Vertragsänderung zwischen Agent und Server.

## Trade-offs & Alternativen
- Empfohlen: Server-seitig, Liste mit `MAX_CONTAINER_PORTS` Einträgen = vielleicht gekürzt = unbekannt. Ein Container
  mit genau 64 exponierten Ports verliert die Vorprüfung, der Agent entscheidet (`pickPort`): harmlos.
- Abschneide-Flag im Vertrag: genauer, aber Vertrags-Drift Agent ↔ Server für einen Randfall.
- Agent sendet bei Überlauf keine Ports: verliert die Anzeige im Inventar.

## Risiken & Rollback
Gering; ein Commit, revertierbar.

## Doku-Impact
Keine Seite beschreibt die Kappung beim Rückfall; Changelog-Fragment.

## Offene Fragen
Keine.
