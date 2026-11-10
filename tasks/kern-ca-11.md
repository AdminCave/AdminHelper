# CA-Issuer: Register der kompromittierten Zwischenzertifikate, Gleichstand im finish — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-11 · Review: pro Task
Spec: docs/features/kern-ca-11.md (Roadmap R-1113, R-1116)
Heavy: linux-full — `apps/ca-issuer` im Diff: der Sammellauf über `main` fährt den Stack mit Enrollment und Rotation. Kein `scenario`, kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1113: Register `<scope>-compromised.pem` für mit --compromised verworfene Zwischenzertifikate  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/rotation.py, apps/ca-issuer/app/storage.py, apps/ca-issuer/app/cli.py, apps/ca-issuer/tests/test_rotation.py, apps/ca-issuer/tests/test_cli.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @496551f4c 2026-11-10T06:07:29+01:00
Review: approve (.ah-out/review/kern-ca-11/T1.verdict.json)
Änderung: Rotation (auch der Switch) mit `--compromised` schreibt das ersetzte Zwischenzertifikat und die Einträge
des Retired-Files vor dem Retired-File in `<scope>-compromised.pem` (Abgleich über den öffentlichen Schlüssel,
abgelaufene fallen heraus); Rotation und finish behalten keinen Eintrag daraus, der Start überspringt ihn im
Retired-File mit WARNING und stoppt bei einem `<scope>.crt` daraus, `status` markiert beides. Tests je Stelle.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_rotation.py tests/test_storage.py tests/test_cli.py
Doku: → T3

### T2 — R-1116: Gleichstand von not_before im Register über created_at  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/cli.py, apps/ca-issuer/tests/test_cli.py
Änderung: `_query_register` wählt je Linie das Zertifikat mit dem größten `(not_before, created_at)`; Test mit zwei
Zertifikaten gleicher `not_before`-Sekunde in beiden Einfügereihenfolgen.
Beweis: reviewer branch kern-ca-7 2026-11-03 · feature/kern-ca-7@578da0db apps/ca-issuer/app/cli.py:494
Dedup-Key: bug:ca-issuer:cli.py:_query_register-newest-tie
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_cli.py
Doku: keine (kein dokumentiertes Verhalten; CHANGELOG → T3)
Abhängt von: T1

### T3 — Doku und CHANGELOG  [ ]
Komponente: ca-issuer · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-ca-11.md
Änderung: DE+EN im Abschnitt Zwischenzertifikate rotieren: `<scope>-compromised.pem`, Verhalten von Start, Rotation
und `status`; CHANGELOG-Eintrag neutral.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_cli.py
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- T1: Register und Leser (`compromised_path`, `read_compromised`, `public_key_der`) in `rotation.py`, `storage` importiert `rotation` (kein Zyklus); Abgleich über SubjectPublicKeyInfo. Im Retired-File greift das Register nach der Signer-Prüfung: ein Eintrag unter der alten Root behält seinen Grund aus `Switch.compromised` (test_storage unverändert). Rotation und finish verwerfen Register-Einträge im Retired-File ohne Abbruch; abgelaufene Einträge verlassen das Register beim nächsten Schreiben mit `--compromised`.
