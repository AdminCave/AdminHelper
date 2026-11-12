### Added

- **CI: naechtliche Tiefenpruefung auf GitHub:** der Workflow `nightly.yml` faehrt jede Nacht (02:23 UTC), von Hand
  und auf einem Pull Request, der ihn aendert, das Schema-Fuzzing aller drei Dienste mit 100 Beispielen je Operation
  und den Backup-Restore-Rundlauf des Stacks (`backup_restore_test.sh`, ein SKIP ist rot); Rechte nur lesend, kein
  Secret.

### Changed

- **CI: Stack-Test auf jedem Pull Request:** der From-outside-Test `integration-stack` laeuft auch auf Pull Requests,
  ein manueller Lauf vor dem Merge entfaellt.
- **CI: Suiten nach geaenderten Pfaden:** auf einem Pull Request entscheidet der Job `changes`
  (`.github/scripts/ci_changes.py`), welche Suiten von Server, Monitoring, CA-Issuer, Schema-Fuzzing, Lock und
  Windows laufen; der Server faehrt dort nur Python 3.14. Jedes andere Ereignis, ein Pfad ausserhalb der engen Bereiche
  und ein Ausfall des Jobs fahren alles; uebersprungene Pflicht-Checks melden Erfolg. Fehler nur unter Python 3.15 oder
  nur gegen den Lock fallen erst auf `main` auf.
- **CI: Merge Queue vorbereitet:** `ci.yml` reagiert auf `merge_group`, jede Gruppe bekommt ihre eigene
  Concurrency-Gruppe; eingeschaltet wird die Queue im Ruleset.
- **CI: Server-Shards nach Laufzeit:** `pytest --shard` verteilt die Testdateien nach ihren Sekunden je Test aus
  `apps/server/tests/shard_weights.toml` (erzeugt von `python -m tests.shard_weights` aus den JUnit-Artefakten eines
  CI-Laufs) statt nach der Zahl der Tests.
