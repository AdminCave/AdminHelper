<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-12 — Gesamt-Timeout für die Zertifikatserneuerung des Desktops

Roadmap: R-1216 (REF).

## Problem
`enrollment::maybe_renew` hält `RENEWING`, fragt `/ca/trust` und erneuert gegebenenfalls. Die HTTP-Clients haben nur
Connect- (10 s) und Read-Timeouts (45 s, je Lesevorgang). Ein gepinnter Server, der langsam tröpfelt, hält den
Aufruf beliebig lange. Die Anmeldung wartet auf `renewal::renew_if_due` (`auth.rs`) und damit auch auf den Lock,
den der stündliche Task gerade hält.

## Ziel & Nicht-Ziele
Ziel: `maybe_renew` endet spätestens nach einem festen Budget (30 s), Lock-Wartezeit eingeschlossen, mit einem Fehler,
den `renew_if_due` wie jeden anderen protokolliert (best effort, nächster Versuch innerhalb der Stunde).
Nicht-Ziel: `Policy::none` für `/ca/trust` (die Zeile nennt es optional; der Client folgt Umleitungen nur innerhalb
der gepinnten Vertrauenskette, kein eigener Fund), andere Timeouts des Desktops.

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/enrollment.rs` (`maybe_renew`, `maybe_renew_with`, Tests), Doku `docs/admin/betrieb.html`
und `docs/en/admin/operations.html` (Abschnitt Vertrauensgeneration), `changelog.d/kern-ca-12.md`.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs
Budget um den ganzen Ablauf statt je Request: ein Wert begrenzt die Anmeldung. Abbruch mitten in `renew`: der Server
hat dann evtl. ein Zertifikat ausgestellt, das der Desktop nicht speichert; das alte bleibt gültig, das Register führt
es beim selben Gerät. `store_identity` ist synchron und wird nicht mittendrin abgebrochen.

## Risiken & Rollback
Ein sehr langsamer, aber funktionierender Server erneuert erst später. Rollback: Revert.

## Doku-Impact
Ein Satz zur Abbruchzeit im Abschnitt „Erneuerung nach einer Rotation“, DE+EN; CHANGELOG-Fragment.

## Offene Fragen
Keine.
