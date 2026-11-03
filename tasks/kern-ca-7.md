<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-7 — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-7 · Review: pro Task
Spec: docs/features/kern-ca-7.md (Roadmap R-1094, R-1095, R-1111)
Heavy: linux-full — `apps/ca-issuer` im Diff: der Sammellauf über `main` fährt Stack und Enrollment.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@03c4068a`.

### T1 — rotate-root finish und status vergleichen in voller Auflösung (R-1094)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/cli.py, apps/ca-issuer/tests/test_cli.py, changelog.d/kern-ca-7.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @e00b210e 2026-11-03T16:50:50+01:00
Review: approve (.ah-out/review/kern-ca-7/T1.verdict.json)
Änderung: `_query_register` liefert je Gerät den Registerzeitpunkt seines neuesten Zertifikats (`created_at`, volle Auflösung); `_finish_lock` (`cli.py:419`) und die Zählung „since the restart“ (`cli.py:198`) vergleichen ihn mit `started_at`. Tests: Erneuerung in derselben Sekunde nach dem Start gibt `finish` frei, eine davor hält es fest; rot ohne Fix.
Beweis: feature/arch-ca-root-renewal@8f50d71a apps/ca-issuer/app/cli.py:419 · Dedup-Key: bug:ca-issuer:apps/ca-issuer/app/cli.py:_finish_lock
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_cli.py
Doku: changelog.d/kern-ca-7.md

### T2 — rotate-intermediates --compromised nach dem Switch trägt den Scope ein (R-1095)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/rotation.py, apps/ca-issuer/tests/test_rotation.py, changelog.d/kern-ca-7.md, apps/ca-issuer/app/root_rollover.py, apps/ca-issuer/app/storage.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @2957b8cf 2026-11-03T16:54:22+01:00
Review: approve (.ah-out/review/kern-ca-7/T2.verdict.json)
Änderung: In Phase `switched` nimmt `_rotate` (`rotation.py:109`) die Scopes aus `--compromised` in `Switch.compromised` auf (Vereinigung, sortiert) und setzt `drop_retired_root`, vor den retired-Dateien wie heute; auch ein zweiter Lauf mit weiterem Scope ergänzt. Test: nach dem Lauf steht der Scope in `root-switch.json`, und `ensure_hierarchy` nimmt ein wieder eingespieltes Zwischenzertifikat unter der alten Root für diesen Scope nicht an; rot ohne Fix.
Beweis: feature/arch-ca-root-renewal@8f50d71a apps/ca-issuer/app/rotation.py:103 · Dedup-Key: bug:ca-issuer:apps/ca-issuer/app/rotation.py:_rotate
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_rotation.py
Doku: changelog.d/kern-ca-7.md

### T3 — /renew: Laufzeit des vorgelegten Zertifikats im Test (R-1111)  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/tests/test_enroll_renew.py
Änderung: Tests über die Route `/renew` mit einem vom Zwischenzertifikat des Scopes signierten Leaf: abgelaufen, noch nicht gültig, letzte gültige Sekunde; die ersten beiden 403, die letzte 200. Gegenprobe gegen eine Variante ohne die Prüfung in `_verify_ca_signed`.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_enroll_renew.py
Doku: keine (Testcode)

## Entscheidungen
- T1 (2026-11-03): `created_at` entscheidet nur, wenn `not_before` in die Sekunde des Starts faellt; sonst bleibt `not_before` der Vergleich. Ein reiner `created_at`-Vergleich zaehlte uebernommene Altzertifikate (aufgezeichnet bei der Uebernahme, lange nach der Signatur) als neu. Getragen wird der Vergleich davon, dass der ausstellende Prozess den Start vor dem ersten Request aufzeichnet und beide Zeiten von derselben Uhr nimmt.
