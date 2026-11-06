<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-4 — Optionen und Sitzungsverlauf: wer was darf, Jump-Host-Format

Roadmap R-1140, R-1143, R-1158 (Zug `tasks/kern-verbindungen-4.md`), Folgearbeit zu `kern-verbindungen-3`
(Optionen je Verbindung, Sitzungsverlauf). Kevins Entscheidungen vom 2026-11-06 stehen in den Roadmap-Zeilen.
Stand `origin/main@ddfec795`.

## Problem / Motivation
- **R-1140:** `POST`/`PUT /api/connections` nehmen `options` von jedem Schreibberechtigten an, also auch von einem
  `read_write`-API-Key (`write_dep`, `apps/server/app/modules/connections/router.py:44`). Einige Optionen ändern,
  wohin und womit der Desktop eine Sitzung aufbaut: `ssh.agentForwarding`, `ssh.forwards`, `ssh.jumpHost`,
  `rdp.drives`, `rdp.printers`, `rdp.gateway` und `rdp.nla = false`. Diese Felder soll nur ein Nutzer-Login setzen
  oder ändern.
- **R-1143:** `GET /api/connections/{id}/sessions` (`router.py:267`) liefert den Verlauf jedem Lesezugriff im
  Scope der Liste, auch API-Keys. Verlauf und Gerätenamen sind für Nutzer-Konten gedacht.
- **R-1158:** Der Jump-Host nimmt IPv6-Literale (`[2001:db8::1]`) in jedem Hop an (Server
  `apps/server/app/modules/connections/schemas.py:58`, Desktop `apps/desktop/src-tauri/src/validation.rs:95`). Nur den
  letzten Hop nimmt OpenSSH selbst auseinander; die Hops davor gibt es unverändert weiter, und dort bleibt ein
  Literal in Klammern nicht so, wie es geschrieben steht (geprüft mit OpenSSH 10.0p2, `ssh -vvv -J`). Kevin wollte
  IPv6 nur dort, wo OpenSSH es richtig weitergibt; das ist der letzte Hop.

## Ziel & Nicht-Ziele
Ziel:
- Ein API-Key bekommt `403`, wenn seine `options` eines der Felder aus R-1140 anders setzen als gespeichert
  (beim Anlegen: als ungesetzt). Unverändert mitgesendete Werte gehen durch, damit ein Key eine Verbindung lesen,
  ändern und zurückschreiben kann.
- Ein API-Key bekommt auf `GET …/sessions` `403`, unabhängig vom Scope.
- Ein IPv6-Literal steht im Jump-Host nur im letzten Hop; Server und Desktop prüfen das gleich.

Jede Änderung kommt mit einem Test, der ohne sie rot ist.

Nicht-Ziele:
- Rechte für Nicht-Admin-Nutzer. Sie schreiben keine Verbindungen (`write_dep` verlangt Admin), und den Verlauf
  sehen sie im Scope der Liste wie bisher.
- Der Import (nur Admin) und Hook-Skripte (`storage.save_connections`, Admin-Code).
- Das eingebettete RDP (#404), das `options` noch nicht liest.

## Betroffene Komponenten & Dateien
- Server: `apps/server/app/modules/connections/router.py` (`create_connection`, `update_connection`,
  `list_connection_sessions`), `apps/server/app/modules/connections/schemas.py` (`_JUMP_RE`); Tests
  `tests/test_connections_options_authz.py` (neu), `tests/test_api_key_server_binding.py`,
  `tests/test_connection_sessions.py`, `tests/test_connections_options.py`.
- Desktop (Rust): `apps/desktop/src-tauri/src/validation.rs` (`JUMP_RE`), Test-Fixture in
  `apps/desktop/src-tauri/src/connection/ssh.rs`.
- Desktop-UI: Hinweistext des Jump-Host-Felds (`apps/desktop/ui/src/lib/i18n/dictionaries.ts`).

## Datenmodell / API / Migrationen
Keine Migration und kein neues Feld. Neu sind zwei `403`-Antworten, beide mit englischem `detail`:
- auf `POST`/`PUT /api/connections` für einen API-Key, der die genannten Optionen ändert;
- auf `GET /api/connections/{id}/sessions` für jeden API-Key.

`422` statt `403` für ein IPv6-Literal ab dem zweiten Hop. Die OpenAPI-Beschreibungen der Routen bleiben, weil
Docstrings nicht geändert werden (Snapshot).

## Externe Integrationen
OpenSSH `ssh(1)` `-J` / `ProxyJump` (<https://man.openbsd.org/ssh_config#ProxyJump>): `ssh` verbindet zum letzten
Hop über einen `ProxyCommand`, der die Hops davor unverändert als `-J` weitergibt. Gemessen mit OpenSSH 10.0p2
(`debug1: Setting implicit ProxyCommand from ProxyJump`).

## Trade-offs & Alternativen
- **Vergleich mit dem gespeicherten Wert statt Verbot jedes Mitsendens:** Ein Key, der eine Verbindung mit
  Jump-Host liest und ohne Änderung zurückschreibt, scheitert nicht. Empfohlen und gebaut.
- **`nla`:** Geschützt ist nur der Wert `false`. NLA einschalten oder auf den globalen Standard zurücksetzen
  bleibt für Keys offen (Kevin: „nla=false“).
- **`403` vor dem Scope-Check bei `…/sessions`:** Alle Keys bekommen dieselbe Antwort, ob die Verbindung existiert
  oder nicht. Damit gibt es kein Existenz-Orakel.

## Risiken & Rollback
Automationen, die per API-Key diese Optionen setzen oder den Verlauf lesen, bekommen `403`. Das ist gewollt; der
CHANGELOG nennt es. Rollback per Revert der Task-Commits; Daten ändern sich nicht. Ein gespeicherter Jump-Host mit
IPv6 in einem späteren Hop lässt sich weiter lesen. Erst beim nächsten Speichern (Server) oder Start (Desktop)
meldet die Prüfung den Fehler.

## Doku-Impact
`docs/developer/api-reference.html` DE+EN (die drei Routen), `docs/admin/index.html` DE+EN (Jump-Host-Format im
Reiter *Optionen*), `changelog.d/kern-verbindungen-4.md`.

## Offene Fragen
Keine; Kevins Antworten vom 2026-11-06 decken alle drei Zeilen.
