<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-7 — ca-issuer: Root-Wechsel nachschärfen, Erneuerung im Test festhalten

Roadmap R-1094, R-1095, R-1111. Stand `origin/main@03c4068a`. R-1054 fährt nicht mit: es ändert auch
`apps/desktop/src-tauri/src/enrollment.rs`, das der offene Branch `feature/kern-ca-6` ändert (nächster Zug `kern-ca-8`).

## Problem / Motivation
- **R-1094:** `rotate-root finish` wartet, solange ein aktives Gerät ein Zertifikat von vor dem ersten Start unter der
  neuen Root hält (`apps/ca-issuer/app/cli.py:419`). Verglichen wird `not_before` des Leafs (ganze Sekunden, der
  Aussteller schneidet die Mikrosekunden ab) mit `started_at` (`recorded_at` der Root im Inventar, Mikrosekunden). Ein
  Gerät, das in derselben Sekunde wie dieser Start erneuert, gilt als alt und hält `finish` fest, bis `--force`. Die
  Zählung in `status` (`cli.py:198`) hat denselben Vergleich.
- **R-1095:** `rotate-intermediates --compromised` in Phase `switched` setzt `drop_retired_root`
  (`apps/ca-issuer/app/rotation.py:109`), trägt den Scope aber nicht in `root-switch.json` `compromised` ein.
  `ensure_hierarchy` (`storage.py:229`) und `cli._signers` (`cli.py:139`) lesen genau diese Liste: nach einem
  Teil-Restore der retired-Dateien nähmen sie abgelöste Zwischenzertifikate unter der alten Root wieder an.
- **R-1111:** Die Laufzeitprüfung des vorgelegten Zertifikats bei `/renew` (`issuer.py:69-71`, `_verify_ca_signed`)
  hat keinen Test, der sie über die Route festhält.

## Ziel & Nicht-Ziele
Ziel: `finish` und `status` vergleichen in voller Auflösung; ein `--compromised`-Lauf nach dem Switch steht in der
Switch-Datei wie ein `switch --compromised`; Tests halten die Laufzeitprüfung bei `/renew` fest.
Nicht-Ziele: keine Änderung an Bündeln, Phasen oder der Ausgabe außer der Zählung; kein neues Feld im Register, keine
Migration.

## Betroffene Komponenten & Dateien
- `apps/ca-issuer/app/cli.py` (`_finish_lock`, `_query_register`, Zählung in `status`), `tests/test_cli.py`.
- `apps/ca-issuer/app/rotation.py` (`_rotate`), `tests/test_rotation.py`.
- `apps/ca-issuer/tests/test_enroll_renew.py`.

## Datenmodell / API / Migrationen
Keine Migration, kein API-Vertrag. R-1094 liest einen vorhandenen Zeitpunkt in voller Auflösung aus dem Register
(`issued_certificates.created_at`, gesetzt mit derselben Uhr wie `recorded_at`), statt `not_before`. `root-switch.json`
behält ihr Format; `compromised` nimmt die Scopes eines späteren Laufs dazu.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- R-1094: `started_at` auf die Sekunde abrunden wäre kürzer, nähme aber ein Zertifikat, das der alte Prozess in derselben
  Sekunde vor dem Neustart ausstellte, als neu: die unsichere Seite. Der Vergleich in voller Auflösung hält beide
  Seiten richtig. Empfehlung: voller Vergleich.
- R-1095: nur `compromised` ergänzen, `drop_retired_root` bleibt wie heute gesetzt.

## Risiken & Rollback
`finish` kann einen Lauf früher freigeben, wenn der Vergleich falsch herum ist: Tests für dieselbe Sekunde vor und
nach dem Start. Rollback: Revert der Task.

## Doku-Impact
Keiner in `docs/` (Verhalten wie beschrieben, nur richtig gerechnet); CHANGELOG über `changelog.d/kern-ca-7.md`.

## Offene Fragen
Keine.
