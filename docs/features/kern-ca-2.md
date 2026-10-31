<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-2 — CA-Issuer: Rotation nach einem Leck, Uhrprüfung der Rotation, Server-Scope im Agent

Zug der Kern-Session (Roadmap R-0982, R-0945, R-0943). R-0911 und R-0793 fahren nicht mit (offene Fragen, siehe
unten).

## Problem
- **R-0982:** `rotation._rotate` prüft die Uhr am aktuellen `<scope>.crt` (`apps/ca-issuer/app/rotation.py:79`),
  bevor feststeht, ob es überhaupt ein Zwischenzertifikat dieses Scopes ist (`pki.intermediate_problem` erst in
  `_retired_after`, :180). Ein fremdes Zertifikat mit einem notBefore in der Zukunft hält so die Rotation auf, obwohl
  die Rotation genau der Weg ist, ein falsches `<scope>.crt` zu ersetzen.
- **R-0945:** `rotate-intermediates` behält das abgelöste Zwischenzertifikat jedes Scopes bis zu seinem Ablauf
  (`<scope>-retired.pem`, im Trust-Bundle von Gateway und frps und in `/renew`). Nach einem Leck eines
  Zwischenzertifikat-Schlüssels ist das die falsche Antwort: die Zertifikate, die der Schlüssel signiert hat oder
  noch signieren kann, bleiben vertraut. `docs/admin/betrieb.html#ca-rotation` nennt den Fall nicht.
- **R-0943:** Der Agent nimmt nach dem Enrollment jedes Server-Zertifikat unter der gepinnten Root an
  (`httpclient.NewMTLS`, `apps/agent/internal/httpclient/httpclient.go:77`), also auch das frps-Leaf (Scope
  `tunnel`). Das Gateway-Leaf stammt immer vom `access`-Zwischenzertifikat (`storage.ensure_gateway_cert`).

## Ziel & Nicht-Ziele
- Ziel: die Rotation ersetzt ein `<scope>.crt`, das kein Zwischenzertifikat seines Scopes ist, ohne Uhrprüfung;
  die Uhrprüfung gilt nur dem eigenen Zwischenzertifikat.
- Ziel: `rotate-intermediates --compromised <scope>` (mehrfach angebbar): für diesen Scope bleibt weder das
  abgelöste noch ein früheres Zwischenzertifikat im Trust-Bundle oder bei `/renew` (`<scope>-retired.pem` leer).
  Die Geräte des Scopes werden widerrufen und neu eingerichtet. Die Betriebsdoku beschreibt beide Wege, wann welcher
  gilt und was die Rotation allein nicht schließt (Abschlussprüfung 2026-10-30: die wirksame Sperre ist R-1009).
- Ziel: über `NewMTLS` nimmt der Agent nur ein Server-Zertifikat an, das ein `access`-Zwischenzertifikat
  (CN `AdminHelper Access Intermediate`, mit oder ohne Datum) signiert hat.
- Nicht-Ziel: Root-Erneuerung und Ablaufanzeige (R-0793), Sperrlisten, OCSP.
- Nicht-Ziel: der Client ohne Identität (`httpclient.New`, Provisionierung mit `--cacert`/`--ca-fp`): er kann einer
  fremden CA vertrauen.

## Betroffene Komponenten & Dateien
- `ca-issuer`: `app/rotation.py`, `app/cli.py`, `tests/test_rotation.py`, `tests/test_cli.py`.
- `agent`: `internal/httpclient/httpclient.go`, `internal/httpclient/httpclient_test.go`.
- Doku: `docs/admin/betrieb.html#ca-rotation`, `docs/en/admin/operations.html#ca-rotation`,
  `changelog.d/kern-ca-2.md`.

## Datenmodell / API / Migrationen
Keine Migration, keine HTTP-API. Neu ist die CLI-Option `--compromised` von `rotate-intermediates`.

## Externe Integrationen
Go `crypto/tls` `Config.VerifyConnection` (läuft nach der Kettenprüfung, `ConnectionState.VerifiedChains`):
https://pkg.go.dev/crypto/tls#Config

## Trade-offs & Alternativen
- `--compromised` je Scope statt „alles verwerfen“: ein Leck betrifft einen Schlüssel; die anderen Scopes
  rotieren wie bisher, ihre Geräte bleiben unberührt. Empfehlung: je Scope.
- Agent-Prüfung über den CN des signierenden Zwischenzertifikats statt über ein Merkmal des Leafs: das
  Server-Leaf trägt keinen Scope (`pki.build_server_leaf`), und bestehende Gateway-Leaves sollen weiter passen.

## Risiken & Rollback
- `--compromised` macht alle Zertifikate des Scopes ungültig; das ist der Zweck, die Doku nennt die Folgen
  (Neu-Provisionierung der Agenten bei `tunnel`/`access`, Neu-Enrollment der Desktops bei `access`).
- Die Agent-Prüfung lehnt ein Gateway ab, dessen Leaf nicht vom `access`-Zwischenzertifikat stammt; das erzeugt
  der ca-issuer nie. Rollback: Revert des Task-Commits.

## Doku-Impact
`betrieb.html`/`operations.html` Abschnitt „Zwischenzertifikate rotieren“ (DE+EN): Rotation nach einem Leck;
Changelog.

## Offene Fragen (nicht in diesem Zug)
- **R-0911:** offene Frage an Kevin (Details privat); fährt im nächsten Zug.
- **R-0793:** Root-Erneuerung und Ablaufanzeige sind je ein eigenes Vorhaben mit sichtbarem Verhalten über
  Server, Web, Desktop und Agent (gepinnte Root, `--ca-fp`). Frage an Kevin: in zwei Zeilen teilen und jeweils
  voll planen? Der Teil „Rotation nach Leck“ ist R-0945 in diesem Zug.
