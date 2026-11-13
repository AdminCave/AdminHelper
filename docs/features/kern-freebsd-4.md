<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Kommentare zu Swap und cpu_count, Komma in der Agent-Doku (`kern-freebsd-4`, Roadmap R-1332)

## Problem / Motivation

Seit R-1253 meldet der Agent Swap und `cpu_count` auch auf FreeBSD (`apps/agent/internal/monitor/collector.go:211`).
Drei Kommentare sagen noch „Linux“ bzw. „Linux only“: `apps/monitoring/app/checkers/agent.py:346` und `:360`,
`apps/desktop/ui/src/lib/api/types.ts:363`. In `docs/developer/agent.html:266` (DE+EN) fehlt nach dem frpc-Pfad ein
Komma vor „das rc.d-Skript“ bzw. „the rc.d script“.

## Ziel & Nicht-Ziele

Ziel: die drei Kommentare nennen Linux und FreeBSD; das Komma steht in beiden Sprachfassungen. Nicht-Ziel: jede
Verhaltensänderung.

## Betroffene Komponenten & Dateien

`apps/monitoring/app/checkers/agent.py`, `apps/desktop/ui/src/lib/api/types.ts`, `docs/developer/agent.html`,
`docs/en/developer/agent.html`.

## Datenmodell / API / Migrationen

Keine.

## Risiken & Rollback

Keine; nur Kommentare und ein Satzzeichen.

## Doku-Impact

Nur das Komma in `docs/developer/agent.html` DE+EN; kein `changelog.d`-Fragment (keine Nutzerwirkung).

## Offene Fragen

Keine.
