# kern-harness-5 — `vm.py sync` lässt `./repo` der Box stehen

Roadmap: R-0736 (BUG).

## Problem
`docker-compose.yml` bindet `./repo` für die Repo-Ebene :8445 (`- ./repo:/usr/share/nginx/repo:ro`). Startet ein
Lauf auf der Box den Stack, legt Docker das fehlende Verzeichnis als root an. Der nächste `vm.py sync`
(`rsync --delete`) will es löschen, wird abgewiesen und endet mit Code 23, der Lauf ist UNVERIFIED (weekly
2026-10-21, zweiter Fall R-1287). `/data/` hat dafür seit R-0086 einen Eintrag in `scripts/vm/rsync-exclude.txt`,
`/repo/` fehlt.

## Ziel & Nicht-Ziele
Ziel: `/repo/` steht verankert in `scripts/vm/rsync-exclude.txt`; ein Test mit echtem rsync zeigt, dass ein
`repo/` der Box einen Sync mit `--delete` übersteht und tiefere `repo`-Verzeichnisse weiter synchronisiert werden.
Nicht-Ziel: die Rechte auf der Box ändern oder compose umbauen.

## Betroffene Komponenten & Dateien
`scripts/vm/rsync-exclude.txt`, `scripts/vm/tests/test_vm.py` (Harness, Änderung auf Kevins Wort 2026-11-10).

## Datenmodell / API / Migrationen
Keine.

## Trade-offs
Verankert (`/repo/`) statt `repo`: ein nackter Name träfe jedes Pfadsegment dieses Namens. Unter `repo/` ist nichts
getrackt (`.gitignore`: `/repo/`).

## Risiken & Rollback
Gering; Rollback durch Revert der Task.

## Doku-Impact
Keine (Kommentar in der Exclude-Datei trägt das Warum).

## Offene Fragen
Keine.
