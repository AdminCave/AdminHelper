# CI: Archiv-Cache aufräumen, tauri-cli-Pins vollständig prüfen — Task-Ledger
Status: geplant · Branch: feature/ci-8 · Review: am Ende
Spec: docs/features/ci-8.md (Roadmap R-1276, R-1277)
Heavy: none — nur CI-Skripte und ein Prüfschritt; kein Stack-, Gateway-, PKI- oder Install-Pfad, die PR-CI fährt beides
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1276: apt_archives_verify.sh verwirft alles außer geprüften .deb und leert partial/  [ ]
Komponente: scripts · Dateien: .github/scripts/apt_archives_verify.sh, .github/scripts/apt_archives_verify_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-8.md
Änderung: Vor der Hash-Prüfung löscht das Skript jeden Eintrag des Archiv-Verzeichnisses, der kein reguläres `*.deb` ist (Symlinks, Verzeichnisse, fremde Dateien), leert `partial/` und legt es als Verzeichnis neu an, wenn es fehlt oder ein Symlink war. Der hermetische Test bekommt diese Fälle (erst rot); die Zeile „partial/ untouched“ wird „partial/ geleert, bleibt Verzeichnis“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-8.md

### T2 — R-1277: der Lockstep-Schritt prüft jeden tauri-cli-Pin in ci.yml und release.yml  [ ]
Komponente: scripts · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Statt `grep -m1` je Datei liest der Schritt alle `run: cargo install tauri-cli`-Zeilen beider Dateien (das eigene grep-Muster zählt nicht mit); jede muss eine Version nennen, und alle müssen gleich sein, sonst `::error::` mit den gefundenen Pins. Gegenprobe lokal mit einem abweichenden Pin in einer Kopie.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html
