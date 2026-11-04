<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-6 — Zertifikatsprüfung an Desktop und Server angleichen

Roadmap R-1053, R-1109 (Zug `tasks/kern-ca-6.md`). Stand `origin/main@ba79469e`. Details zu beiden Zeilen nur in
`tasks/private/sec-kern-ca-6-notes.md`.

## Problem / Motivation
- **R-1053:** Der Desktop prüft das Server-Zertifikat im registrierten Zustand (`CaPinVerifier`,
  `apps/desktop/src-tauri/src/enrollment.rs:854`) enger an der gepinnten CA, aber anders als der Agent
  (`verifyGatewayIssuer`, `apps/agent/internal/httpclient/httpclient.go:108`). Beide sollen dieselbe Regel tragen.
  Ein zweiter Teil der Zeile fährt als eigene Zeile (R-1112).
- **R-1109:** Der Server übernimmt die Gültigkeit eines vom Gateway gemeldeten Client-Zertifikats
  (`get_client_identity`, `apps/server/app/core/identity.py:208`), ohne die Laufzeit gegen die Uhr zu prüfen; das
  Gateway hält TLS-Sessions bis zu einer Stunde (`apps/gateway/nginx.conf:29`).

## Ziel & Nicht-Ziele
Ziel: Der Desktop nimmt im registrierten Zustand als Server nur ein Zertifikat an, das der Agent ebenso annähme
(Aussteller ist ein Access-Intermediate, `AdminHelper Access Intermediate` oder mit Datums-Suffix); der Server
behandelt ein Client-Zertifikat außerhalb seiner Laufzeit wie keines. Jeder Fall mit einem Test, der ohne den Fix
rot ist. Nicht-Ziele: Hostname-Prüfung im Desktop (bleibt bewusst aus, Doku `developer/desktop.html`), Änderungen am
Gateway, an der Session-Dauer oder am Wire-Format; der zweite Teil von R-1053 (R-1112).

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/enrollment.rs` (Verifier + Tests); `apps/server/app/core/identity.py`,
`apps/server/tests/test_identity_source.py` bzw. ein Test daneben; Doku `docs/developer/desktop.html` +
`docs/en/developer/desktop.html` (Abschnitt „Enrollter Zustand“); `changelog.d/kern-ca-6.md`.

## Datenmodell / API / Migrationen
Keine. Die Fehlermeldung bei einem fremden Aussteller nutzt den bestehenden Code `ERR_CA_PIN_MISMATCH` nicht (der
bietet das Zurücksetzen der Identität an, was hier nicht hilft), sondern eine Meldung ohne Code.

## Externe Integrationen
rustls `ServerCertVerifier` (0.23), `x509-parser` 0.18 (schon Abhängigkeit).

## Trade-offs & Alternativen
- R-1053 Desktop: Aussteller-CN des Leafs nach erfolgreicher Kettenprüfung prüfen (wie der Agent) statt die
  Trust-Anker auf Intermediates zu verengen: Die Anker müssen Roots bleiben, damit eine Root-Erneuerung trägt
  (`keeps_the_gateway_through_a_root_renewal`). Empfehlung: CN-Prüfung.
- R-1109: Prüfung in `get_client_identity` statt kürzerer `ssl_session_timeout`: wirkt auf jede Wiederaufnahme und
  braucht keinen Gateway-Neustart. Empfehlung: `identity.py`.
- Zweiter Teil von R-1053: eigener Zug (R-1112), Varianten und Empfehlung in `tasks/private/`.

## Risiken & Rollback
Ein zu enger Desktop-Verifier sperrt registrierte Geräte aus: die Rotations-Tests bleiben grün und decken jede
Phase. Ein zu strenger Server-Check lehnt gültige Zertifikate bei Uhrabweichung ab: Vergleich gegen die
Zertifikatsgrenzen ohne Toleranz, wie `notifications/stream.py:71`. Jede Task einzeln per `git revert`.

## Doku-Impact
`docs/developer/desktop.html` + EN: der Satz zum CA-Pin im registrierten Zustand nennt die Ausstellerregel. Sonst
nur das Changelog-Fragment.

## Offene Fragen
- Zweiter Teil von R-1053: eigener Zug (R-1112), Frage an Kevin in `tasks/private/`.
