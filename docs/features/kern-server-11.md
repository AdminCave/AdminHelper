# kern-server-11 — Ein Weg für neue Benutzer, FRP-Startprüfungen aus main.py

Roadmap: R-0690 (REF, Code-Audit 2026-10-21).

## Problem / Motivation

Ein Admin entsteht heute auf vier Wegen, jeder mit eigenen Regeln:

| Weg | Datei | Event `user.created` | Audit | Policy-Sync | Wettlauf um den Namen |
|---|---|---|---|---|---|
| `POST /api/users` | `modules/users/router.py:52` | ja | `user.created` | ja | `IntegrityError` → 409 |
| `POST /api/auth/bootstrap` | `modules/users/auth_router.py:400` | nein | `auth.bootstrap` | nein | Advisory-Lock, kein Fang |
| `python -m app.cli create-admin` | `app/cli.py:52` | ja | `user.created` (Akteur `cli`) | nein | Vorprüfung, kein Fang |
| `ADMIN_PASSWORD` beim Start | `app/main.py:78` (`_ensure_admin`) | nein | keiner | nein | `IntegrityError` → still |

Dazu trägt `app/main.py` (589 Zeilen) die FRP-Startprüfungen (`_tell_admins`, `_remove_rejected_extra_config`,
`_report_rejected_fields`, `_check_frps_server_configs`, `_ensure_frps_config`, `main.py:228-387`).
`_report_rejected_fields` liest die Werte zurück, indem es den eben erzeugten `frps.toml`-Text zeilenweise an
` = ` zerlegt (`main.py:279-284`): eine Formatänderung im Generator bricht die Prüfung still.

## Ziel & Nicht-Ziele

Ziel:
- `app/modules/users/service.py` mit `create_user(...)`: der einzige Ort, der einen `User` anlegt. Er legt die
  Basis-Abo-Regel eines Admins an, reiht `user.created` ein, committet, fängt den Wettlauf um den Namen
  (`UsernameTaken`), gleicht die FRP-Policy ab und schreibt den Audit-Eintrag. Die vier Wege rufen ihn auf und
  behalten nur ihre Eingangsprüfung (Bootstrap: Token, Lock, Zertifikat; CLI: Eingaben; Start: `ADMIN_PASSWORD`).
- Damit feuern Bootstrap und `ADMIN_PASSWORD` ebenfalls `user.created`, alle vier gleichen die Policy ab, und der
  Start-Admin bekommt einen Audit-Eintrag (Akteur `system`).
- `config_generator.frps_fields(config) -> dict` liefert die Schlüssel und Werte vor dem TLS-Block;
  `generate_frps_toml` schreibt daraus, `_report_rejected_fields` liest daraus. Der erzeugte Text bleibt
  Byte für Byte gleich.
- Die FRP-Startprüfungen ziehen nach `app/modules/frp/startup_checks.py`; `main.py` ruft sie nur noch auf.

Nicht-Ziele: keine neue Route, keine Änderung an Antworten oder Statuscodes, keine Migration, kein neues
Bootstrap-Verfahren. Das Audit-Ereignis des Bootstraps bleibt `auth.bootstrap`.

## Betroffene Komponenten & Dateien

Server: `app/modules/users/service.py` (neu), `users/router.py`, `users/auth_router.py`, `app/cli.py`,
`app/main.py`, `app/modules/frp/config_generator.py`, `app/modules/frp/startup_checks.py` (neu); Tests
`test_users_service.py` (neu), `test_bootstrap.py`, `test_cli.py`, `test_config_generator.py`,
`test_frp_extra_config.py`, `test_frp_docker_manager.py` und die Tests, die die verschobenen Funktionen patchen.

## Datenmodell / API / Migrationen

Keine Migration, keine API-Änderung (OpenAPI-Snapshot unverändert). Sichtbar ändert sich nur das Event- und
Audit-Verhalten der Wege ohne Event (siehe Ziel); der Hook- und Benachrichtigungs-Katalog nennt es.

## Externe Integrationen

FRP: `frps.toml` (TOML, https://gofrp.org/en/docs/reference/server-configures/). Der Text bleibt gleich; Beleg
ist der Vergleich vorher/nachher in `test_config_generator.py`.

## Trade-offs & Alternativen

- **Ein Service für alle Benutzer** statt nur `create_admin`: `POST /api/users` legt auch Nicht-Admins an, und
  zwei Wege für dasselbe Insert wären wieder zwei Regelsätze. Empfehlung: `create_user(..., is_admin=...)`.
- **Audit-Aktion als Parameter**: der Bootstrap behält `auth.bootstrap` (Filter und Doku hängen daran), alle
  anderen schreiben `user.created`.
- **Policy-Sync auch für Admins**: bisher nur die API; der Abgleich ist idempotent, ein zusätzlicher Lauf beim
  ersten Start kostet nichts.

## Risiken & Rollback

Bootstrap und Anmeldung sind Risikopfade (`security` je Task). Ein Fehler im Service träfe jeden neuen Benutzer;
die Tests decken alle vier Wege. Rollback: Revert des Merge-Commits, keine Daten berührt.

## Doku-Impact

`docs/developer/hooks.html` + EN (Event-Katalog: `user.created` auch beim Bootstrap und beim Start-Admin),
`docs/developer/api-reference.html` + EN (Bootstrap feuert `user.created`), `changelog.d/kern-server-11.md`.

## Offene Fragen

Keine aus Kevins Bereich: die Roadmap-Zeile nennt die vier Wege mit ihren Abweichungen als Fehler und schlägt den
einen Service vor.
