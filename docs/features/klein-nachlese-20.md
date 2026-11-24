<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-20 — Nachlese der Prüfungen kern-agent-20 bis kern-testdb-1

Zug `tasks/klein-nachlese-20.md` mit R-1730, R-1731, R-1733, R-1735, R-1736, R-1746 und R-1749. Nits aus den
Prüfungen vom 2026-11-23/24; alle Branches sind gemergt. `overlap.sh` (2026-11-24): kein offener Branch ändert die
betroffenen Dateien.

## Problem / Motivation
- **R-1730:** `parseScQuery` liefert bei 0 Diensten `nil`, `all_services` fehlt dann im Report (früher `null`);
  `SystemState.empty()` zählt Felder von Hand; `servicelogs_windows_test.go` hat einen doppelten Doc-Kommentar;
  der Kommentar an `parseZpoolList` nennt „pool maps“ statt `[]ZPool`.
- **R-1731:** zwei Test-Nits (toter `fire_event`-Patch in `test_bootstrap.py`, prozessweiter `threading.Event`-Patch
  in `test_scheduler_schema_gate.py`); `hooks.html` (DE+EN) liest die 10 s beim Herunterfahren als harte Grenze,
  ein gestarteter Hook läuft bis zu seinem Hook-Timeout weiter.
- **R-1733:** der Zweig `UsernameTaken` in `create_admin` (Wettlauf nach der Vorabprüfung) hat keinen Test.
- **R-1735:** Docstring von `monitoring_client.py` nennt die Proxy-Ausnahme nicht; im Test eine doppelte
  Notify-Barriere; der Tag-Sync-Test prüft die URL nur über den pytest-httpx-Teardown.
- **R-1736:** Fragment `changelog.d/kern-server-13.md` hat nicht die Form `- **Bereich: Titel:** Text`.
- **R-1746:** `env_int` kennt nur `minimum`; Ports (z. B. `SMTP_PORT=70000`) werden angenommen.
- **R-1749:** Docstrings in Monitoring-Tests nennen noch SQLite (die Tests laufen auf Postgres), eine
  Postgres-Funktion im Test.

## Ziel & Nicht-Ziele
Nur die genannten Stellen. Kein Wire-Format-Wechsel: der Report ohne Dienste bleibt wie er ist (prüfen,
kommentieren; ändert sich der Wire, wäre das eine Frage an Kevin und die Zeile fährt nicht mit).
R-1746 ist die einzige Verhaltensänderung: ein Port außerhalb 1–65535 stoppt den Dienst beim Start mit der
bekannten `ConfigError`-Meldung (wie schon bei Werten unter dem Minimum).

## Betroffene Komponenten & Dateien
agent (`apps/agent/internal/monitor/`), server (Tests, `cli.py` unverändert, `monitoring_client.py` Docstring,
`config.py`), pycommon (`ah_common/env.py`), monitoring (Tests, `config.py`), docs (`hooks.html` DE+EN), changelog.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs
`maximum` als optionaler Parameter von `env_int`/`parse_int` (wie `minimum`) statt eigener `env_port`-Funktion: eine
Zeile weniger Konzept, Meldung bleibt einheitlich.

## Risiken & Rollback
Eine bereits gesetzte, ungültige Port-Variable stoppt den Dienst nach dem Update beim Start (Meldung nennt Variable
und Wert). Rollback: Revert des Task-Commits.

## Doku-Impact
`docs/developer/hooks.html` + EN (Shutdown-Wortlaut); `changelog.d`-Fragment; die Port-Prüfung steht in den
Konfigurationsseiten nur, wo dort der Wertebereich genannt ist (T3 scannt per `grep`).

## Offene Fragen
Keine.
