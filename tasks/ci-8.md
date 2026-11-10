# CI: Archiv-Cache aufräumen, tauri-cli-Pins vollständig prüfen — Task-Ledger
Status: aktiv · Branch: feature/ci-8 · Review: am Ende
Spec: docs/features/ci-8.md (Roadmap R-1276, R-1277)
Heavy: none — nur CI-Skripte und ein Prüfschritt; kein Stack-, Gateway-, PKI- oder Install-Pfad, die PR-CI fährt beides
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1276: apt_archives_verify.sh verwirft alles außer geprüften .deb und leert partial/  [x]
Komponente: scripts · Dateien: .github/scripts/apt_archives_verify.sh, .github/scripts/apt_archives_verify_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-8.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c5d4afaa8 2026-11-10T16:38:18+01:00
Review: am Ende (Branch-Review)
Änderung: Vor der Hash-Prüfung löscht das Skript jeden Eintrag des Archiv-Verzeichnisses, der kein reguläres `*.deb` ist (Symlinks, Verzeichnisse, fremde Dateien), leert `partial/` und legt es als Verzeichnis neu an, wenn es fehlt oder ein Symlink war. Der hermetische Test bekommt diese Fälle (erst rot); die Zeile „partial/ untouched“ wird „partial/ geleert, bleibt Verzeichnis“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-8.md

### T2 — R-1277: der Lockstep-Schritt prüft jeden tauri-cli-Pin in ci.yml und release.yml  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-8.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @aea7a0e10 2026-11-10T17:01:39+01:00
Review: am Ende (Branch-Review)
Änderung: Statt `grep -m1` je Datei liest der Schritt alle `run: cargo install tauri-cli`-Zeilen beider Dateien (das eigene grep-Muster zählt nicht mit); jede muss eine Version nennen, und alle müssen gleich sein, sonst `::error::` mit den gefundenen Pins. Gegenprobe lokal mit einem abweichenden Pin in einer Kopie.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html

### T3 — Branch-Review: Pin-Prüfung als getestetes Skript, Slash am Archiv-Pfad  [x]
Komponente: scripts · Dateien: .github/scripts/tauri_cli_pins.sh, .github/scripts/tauri_cli_pins_test.sh, .github/workflows/ci.yml, .github/scripts/apt_archives_verify.sh, .github/scripts/apt_archives_verify_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @94f2a4e57 2026-11-10T17:31:29+01:00
Review: am Ende (Branch-Review)
Änderung: Die Pin-Prüfung aus T2 zieht nach `.github/scripts/tauri_cli_pins.sh` (SPDX) und zählt jede Nicht-Kommentarzeile mit `cargo install … tauri-cli`, auch in `run: |`-Blöcken und über Zeilenfortsetzungen; der hermetische Test `tauri_cli_pins_test.sh` läuft im Job ops-scripts. `apt_archives_verify.sh` streicht abschließende Schrägstriche vom Pfad, damit ein Link an Stelle von `<dir>` auch als `<link>/` erkannt wird; der Test bekommt den Fall.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (cicd.html beschreibt schon „jede dieser Zeilen“; das Skript macht den Satz wahr)

### T4 — PR-CI: der Server-Test des Lockstep-Schritts kopiert das neue Pin-Skript mit  [ ]
Komponente: server · Dateien: apps/server/tests/test_release_images.py
Review: am Ende (Branch-Review)
Änderung: `test_the_lockstep_job_reads_the_frp_version_of_the_frps_image` fährt den Schritt `Compare the four FRP_VERSION pins` auf einer Kopie der Dateien aus `_PINNED`; seit T3 ruft der Schritt `.github/scripts/tauri_cli_pins.sh` auf, das in der Kopie fehlt (PR #453, Lauf 42859714863: `No such file or directory`, rc 127). `_PINNED` nimmt das Skript auf.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (Testgerüst)

## Entscheidungen
- T3: `verify.sh scripts` fährt `.github/scripts/*_test.sh` nicht (nur der CI-Schritt im Job ops-scripts); die Tests von T1 und T3 fährt die Session zusätzlich direkt mit bash, die Summary steht im Commit-Body. Die Aufnahme in run.sh wäre eine Harness-Änderung und bleibt außen vor.
