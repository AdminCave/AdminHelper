<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: gespeicherte Texte und Dienste-Fehlerzeilen nachziehen (kern-monitoring-27)

Roadmap: R-1372, R-1373, R-1415 · Ledger: `tasks/kern-monitoring-27.md`

## Problem / Motivation

- **R-1372:** `send_to_rule` (`apps/monitoring/app/alerter.py:140`) schreibt den Fehlertext eines Alarmkanals
  unverändert in `MonitorAlertLog.error`. Ein Text mit NUL oder einem einzelnen Surrogat lässt sich in Postgres nicht
  speichern; der Commit des Durchlaufs scheitert. `check_engine.py` hat dafür schon `_storable` (`:254`), der Alerter
  nutzt es nicht.
- **R-1373:** `loads_readable` (`apps/monitoring/app/models.py:45`) liest gespeichertes JSON für API-Antworten. Ältere
  Zeilen können Surrogat-Escapes (`"\ud800"`) tragen; `json.loads` macht daraus einzelne Surrogate, die die Antwort
  nicht kodieren kann (500).
- **R-1415:** Nachhärtung der Dienste-Fehlerzeilen (Server-Ansicht „Dienste“, Desktop „Mehr Log“), bevor der Agent
  Zeilen sendet: Negativtests für die Berechtigung der beiden Routen, ein Schalter-Wechsel, der nicht mit einem
  laufenden Bericht kollidiert, ein schärferer Laufzeit-Test der Schwärzung und eine
  engere Unit-Prüfung im Desktop. Einzelheiten privat.

## Ziel & Nicht-Ziele

Ziel:
- Ein gemeinsamer Helfer `storable()` in `app/core/bounds.py`; `check_engine` und `alerter` nutzen ihn.
- `loads_readable` gibt Strings und Schlüssel mit einzelnen Surrogaten als U+FFFD zurück; die gespeicherte Zeile bleibt.
- R-1415 wie oben; die Grenzen der Schwärzungsregeln bleiben, wie sie sind (gewollt, lineare Laufzeit).

Nicht-Ziele: keine Migration, kein Umschreiben alter Zeilen, keine Änderung an der Schwärzungslogik selbst.

## Betroffene Komponenten & Dateien

- Monitoring: `app/core/bounds.py`, `app/check_engine.py`, `app/alerter.py`, `app/models.py`,
  `app/service_inventory.py`, `app/routers/checks.py` und ihre Tests.
- Desktop (Rust): `apps/desktop/src-tauri/src/connection/ssh.rs`.

## Datenmodell / API / Migrationen

Keine Migration, keine Vertragsänderung.

## Trade-offs & Alternativen

Ersetzen statt Ablehnen: ein Fehlertext oder eine Altzeile ist Diagnose, ein U+FFFD an der Stelle ist besser als ein
verlorener Durchlauf oder eine 500. Für den Schalter eine Zeilensperre auf dem Inventar statt eines zweiten
Löschlaufs: beide Schreiber serialisieren sich, der Bericht sieht den neuen Schalter.

## Risiken & Rollback

Gering. Die Zeilensperre hält ein Inventar nur für die Dauer einer Transaktion. Rollback: Revert je Task.

## Doku-Impact

Keine Seite beschreibt das betroffene Verhalten; CHANGELOG über `changelog.d/kern-monitoring-27.md`.

## Offene Fragen

Keine.
