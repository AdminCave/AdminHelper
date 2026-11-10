# Betriebsskripte: .env-Leser, Rollen-Passwörter, PostgreSQL-18-Umzug (ops-7)

Roadmap: R-1114, R-1115, R-1138 (Kevin 2026-11-09 Triage, vor 0.47.0). Der PR ändert `scripts/update.sh`: Kevin
merged (CLAUDE.md §2).

## Problem / Motivation
- **R-1114:** Der gemeinsame `.env`-Leser (`ENV_TOK` in `scripts/backup.sh`, `scripts/diagnostics.sh`,
  `scripts/restore.sh`) liest Schlüssel mit Nicht-ASCII-Bytes in einem Randfall anders als Docker Compose.
- **R-1115:** `restore.sh` (`role_password`) lehnt ein Rollen-Passwort mit `$$` ab, obwohl
  `docs/admin/installation.html` genau diese Form für ein wörtliches `$` empfiehlt; die Meldung nennt den Ausweg über
  die Umgebungsvariable nicht. Test 29 in `scripts/tests/restore_guard_test.sh` prüft `SCHEDULER_DB_PASSWORD` nur
  auf nicht-leer und hat keinen Fall „Backslash in Quotes“ und keinen Gegenfall „`$` in einfachen Quotes“.
- **R-1138:** Der Umzug auf PostgreSQL 18 in `scripts/update.sh` (`pg18_migrate`) löscht die frisch angelegte
  Datenbank im neuen Container (`DROP DATABASE adminhelper`), ohne vorher zu prüfen, dass dieser Container wirklich
  PostgreSQL 18 auf `postgres18-data` ist (ein Compose-Override könnte anderes starten).

## Ziel & Nicht-Ziele
Ziel: die drei Zeilen beheben, je mit Test. Nicht-Ziele: kein neuer Leser, keine Änderung an install.sh oder an der
Prüfung der `.env` in update.sh, keine neue Option.

## Betroffene Komponenten & Dateien
- `scripts/backup.sh`, `scripts/diagnostics.sh`, `scripts/restore.sh` (`ENV_TOK`, gleich in allen drei,
  `diagnostics_test.sh` (r) hält sie gleich).
- `scripts/restore.sh` (`role_password`), `scripts/tests/restore_guard_test.sh` (29).
- `scripts/update.sh` (Block `pg18-migration`), `scripts/tests/update_test.sh` (Docker-Stub mit
  `AH_TEST_PG_MOUNTS`).
- Doku: `docs/admin/betrieb.html`, `docs/en/admin/operations.html` (Restore und Rollen-Passwörter),
  `changelog.d/ops-7.md`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Docker Compose `.env`-Format (compose-go dotenv: Schlüssel aus Buchstaben, Ziffern und `_ . - [ ]`; Interpolation:
`$$` ist ein wörtliches `$`, einfach gequotete Werte wörtlich,
https://docs.docker.com/reference/compose-file/interpolation/). PostgreSQL `server_version_num`.

## Trade-offs & Alternativen
- **R-1114:** Ein Schlüssel mit einem Byte ab `\200` gilt dem Leser als einer, den Compose ablehnen könnte (`tbad`):
  die Filter nehmen dann den vorsichtigeren Weg. Alternative: Unicode-Klassen in awk nachbauen; unter `LC_ALL=C` nicht
  verlässlich, verworfen.
- **R-1115:** Ein Wert außerhalb einfacher Quotes, dessen `$` alle paarweise als `$$` stehen, wird angenommen und als
  ein `$` je Paar gelesen, wie Compose; ein einzelnes `$` stoppt den Restore weiter. Die Meldung nennt den Ausweg:
  das Passwort in der Umgebung setzen.
- **R-1138:** Vor dem `DROP DATABASE`: der laufende postgres-Container hat `postgres18-data` eingehängt und meldet
  `server_version_num` ab 180000 und unter 190000; sonst schlägt der Schritt fehl und der vorhandene Rollback
  greift (die alte Datenbank auf `postgres-data` bleibt unberührt).

## Risiken & Rollback
Gering: jede Änderung macht ein Skript vorsichtiger oder nimmt eine dokumentierte Form an. Rollback: Revert des PR.

## Doku-Impact
`betrieb.html`/`operations.html`: Rollen-Passwörter mit `$$` und der Ausweg über die Umgebung. Der Umzug auf 18 und
der `.env`-Leser ändern kein dokumentiertes Verhalten; CHANGELOG über `changelog.d/ops-7.md`.

## Offene Fragen
Keine.
