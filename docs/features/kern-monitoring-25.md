<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: rebaseline mit unlesbaren Details (`kern-monitoring-25`, Roadmap R-1401)

## Problem / Motivation

`POST /checks/{check_id}/rebaseline` (`apps/monitoring/app/routers/checks.py:617`) liest `state.details` mit einem
nackten `json.loads`, während dieselbe Route `check.config` drei Zeilen davor gegen `JSONDecodeError`/`TypeError`
abfängt. Steht in `monitor_states.details` ein unlesbarer Text, antwortet die Route mit 500. Die Antwort selbst geht
über `MonitorState.to_dict` (`apps/monitoring/app/models.py:206`, `loads_readable`), das bei unlesbarem Text ebenso
wirft; ein Abfangen nur in der Route liefe also weiter in den 500.

## Ziel & Nicht-Ziele

**Ziel:** Unlesbare Details gelten in der Route als „keine Basislinie“ (nichts zu verwerfen, gespeicherter Text bleibt
unverändert), und `MonitorState.to_dict` meldet sie als `details: null` statt zu werfen. Damit antwortet rebaseline
mit 200, und jede andere Antwort, die einen Zustand zeigt, bricht an einer solchen Zeile nicht mehr ab.

**Nicht-Ziele:** `loads_readable` selbst bleibt streng (es dient auch Konfigurationen und Vorlagen, wo ein stilles
`None` einen Fehler verdecken würde); keine Bereinigung gespeicherter Zeilen; die übrigen `json.loads` in
`checks.py` bleiben, wie sie sind.

## Betroffene Komponenten & Dateien

`apps/monitoring/app/routers/checks.py` (rebaseline), `apps/monitoring/app/models.py` (`MonitorState.to_dict`),
`apps/monitoring/tests/test_central_rebaseline.py`.

## Datenmodell / API / Migrationen

Keine Migration. API: für gültige Zeilen unverändert; eine Zeile mit unlesbaren Details liefert jetzt `details: null`
statt 500.

## Trade-offs & Alternativen

- Nur die Route abfangen: reicht nicht (Antwort wirft weiter).
- `loads_readable` tolerant machen: träfe auch Konfiguration und Vorlagen; verworfen.

## Risiken & Rollback

Gering; ein Commit, einzeln revertierbar.

## Doku-Impact

Keine: das dokumentierte Verhalten (`docs/developer/monitoring.html`, `api-reference.html`) gilt für gültige Zeilen
unverändert; ein Fragment in `changelog.d/` ist für eine interne Robustheitsänderung nicht nötig.

## Offene Fragen

Keine.
