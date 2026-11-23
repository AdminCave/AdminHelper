### Changed

- **CI: Merge Queue fuer `main`:** Jeder Pull Request geht jetzt ueber die Merge Queue (Merge-Methode Merge, eine
  Gruppe je Pull Request, Check-Timeout 60 min); `ci.yml` prueft auf `merge_group` den Stand `main` plus Pull Request
  vor dem Merge. Das neue `scripts/dev/queue-wait.sh <pr>` wartet, bis ein eingereihter Pull Request gemergt ist oder
  die Queue verlaesst.
