# kern-harness-16 — Nachlese der Harness-Prüfungen

Roadmap: R-1785, R-1819, R-1822 (Kevin 2026-11-27: angenommen, Harness-Pfade auf Kevins Wort).

## Problem
- **R-1785** (Nits aus harness-hygiene-1):
  - `scripts/dev/worktree-teardown.sh:144` prüft `merge-base --is-ancestor "$BRANCH"`. Gibt es einen Tag mit
    demselben Namen, nimmt git den Tag.
  - `worktree-teardown.sh:120`: `find -xdev` steigt nicht in einen fremden Mount ab, nennt den Mountpunkt selbst
    aber doch. `:125` löscht ihn dann samt Inhalt als root, mit ungepinntem `alpine`.
  - `scripts/dev/review-risk.txt` fehlen die Agent-Pakete mit Host-Wirkung (`selfupdate`, `allowlist`, `execx`)
    und `scripts/backup.sh`, `restore.sh`, `diagnostics.sh`.
  - `scripts/tests/run.sh:826`: Der Schritt ca-issuer fällt ohne Pins auf `pip install pytest cryptography`
    zurück, und `2>/dev/null` verschluckt den Grund.
- **R-1822**: Der Kommentar `run.sh:823` behauptet „NOT covered by CI today“. Es gibt aber den CI-Job ca-issuer.
- **R-1819** (Nits aus kern-harness-11):
  - `scripts/dev/verify.sh:136` verwirft geerbte Laufschalter, aber nicht `AH_REQUIRED` und `AH_SCRIPT_TESTS*`.
  - `run.sh:651` `filtered` legt seine Datei im geteilten Temp-Verzeichnis an.
  - `scripts/dev/task-close.sh:280` löscht `last-verify.json` nicht vor dem Lauf.
  - `scripts/dev/review.sh:221` schaltet die Sperrliste still ab, wenn das Verzeichnis `tasks/private` nicht
    durchsuchbar ist.
  - `tasks/kern-harness-11.md:15`: eine Entscheidungszeile neutraler fassen.

## Ziel und Nicht-Ziele
Ziel: jeden Nit an seiner Stelle beheben, mit einem Test, der ohne den Fix rot ist.
Nicht-Ziel: das Verhalten der Gates sonst ändern.

## Entwurf
- **Teardown:**
  - `refs/heads/$BRANCH` statt des nackten Namens.
  - Ein fremder Pfad auf einem anderen Gerät als `WT` (`stat -c %d`) ist ein Mountpunkt. Der Teardown bricht dann
    mit einer Meldung ab, statt ihn zu löschen.
  - `alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f` (Index-Digest,
    `docker buildx imagetools inspect`, 2026-11-28).
- **verify.sh:** `AH_REQUIRED`, `AH_SCRIPT_TESTS`, `AH_SCRIPT_TESTS_DIR` und `AH_SCRIPT_TESTS_ROOT` werden *vor*
  dem Sourcen des Devenv verworfen. Der Wert aus `.devenv.sh` gilt so weiter, ein geerbter aus der Shell nicht.
  Die übrigen vier bleiben, wo sie sind.
- **filtered:** `mktemp -p "$AH_OUT_DIR"` (Repo-eigen, kein geteiltes `/tmp`).
- **task-close:** `rm -f` des Artefakts vor dem Lauf.
- **review.sh:** Ist `tasks/private` ein Verzeichnis, das nicht durchsuchbar ist, gilt das als Fehler (`die`).

## Doku-Impact
Keine: Harness-Interna, ihre Doku stehen in den Skriptkommentaren.

## Risiken
- `verify.sh`: Eine Session, die `AH_REQUIRED` bewusst in der Shell setzt, verliert das. Der Weg dafür ist
  `.devenv.sh`.
- Der Pin von alpine muss bei Bedarf von Hand nachgezogen werden.

Heavy: none.
