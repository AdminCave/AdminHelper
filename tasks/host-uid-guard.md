<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Install: Installationsverzeichnis nur für den Installierenden, Warnung bei Container-UIDs auf dem Host — Task-Ledger
Status: bereit · Branch: feature/host-uid-guard · Review: am Ende
Spec: docs/features/host-uid-guard.md
Heavy: linux-full — `scripts/install.sh` und `scripts/update.sh` (Upgrade-Pfad `upgrade_path_test.sh` im Sammellauf). Kein `scenario`: kein Cross-Host-, Agent- oder PKI-Pfad. Kein `windows`. Hängt ab von: #275 (ops-install-hardening, gleiche Skripte); PR merged Kevin
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — install/update: Verzeichnis 0750, Warnung bei Host-Konten mit UID 10001 oder 70  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/update.sh, scripts/tests/install_test.sh, scripts/tests/update_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0b4cd0af 2026-10-29T07:45:39+01:00
Review: am Ende (Branch-Review)
Änderung: `install.sh` setzt das Installationsverzeichnis nach dem Anlegen (`mkdir -p "$TARGET_DIR/scripts"`, auf dem Stand von #275 `install.sh:181`) auf `0750`, Eigentümer unverändert; `update.sh` setzt das Verzeichnis, in dem es läuft, bei jedem Lauf auf `0750`. Beide rufen vorab eine Prüfung, die für UID 10001 (`app` der Dienste) und 70 (Postgres) per `getent passwd` ein Host-Konto sucht und je Treffer auf stderr warnt (UID, Kontoname, Hinweis auf die Doku), ohne abzubrechen; ohne `getent` keine Warnung und kein Fehler. Zeilen-Angaben vor dem Bau auf dem gemergten #275 neu greppen. Tests: `install_test.sh` und `update_test.sh` (hermetisch, `getent` per PATH-Stub): (a) Verzeichnis nach install bzw. update `0750`, auch wenn es vorher `0755` war; (b) Stub meldet UID 10001 → Warnung mit `10001` und Kontoname, Exit unverändert 0; (c) Stub meldet nichts → keine Warnung; (d) ohne `getent` → keine Warnung, Exit 0. Zuerst rot: (a), (b).
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: docs/admin/installation.html + docs/en/admin/installation.html (Installationsverzeichnis `0750`, Warnung bei UID 10001/70) · docs/admin/betrieb.html:85 + docs/en/admin/operations.html:52 (UID 70 neben 10001; install und update warnen) · CHANGELOG.md (Changed, umlautfrei)

### T2 — Branch-Prüfung: Modus nur verschärfen, Fehlerpfad chmod, Doku zu fremden Werkzeugen  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/update.sh, scripts/tests/install_test.sh, scripts/tests/update_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4af31909 2026-10-29T08:01:48+01:00
Review: am Ende (Branch-Review)
Änderung: `chmod g-w,o-rwx .` statt `chmod 0750 .` (aus 0755/0775 wird 0750, ein strengeres 0700 bleibt); `update.sh` schließt das Verzeichnis erst nach den Prüfungen, die mit „nichts veraendert“ abbrechen, und warnt auch unter `--check` (ohne den Modus zu ändern). Tests: 0700 bleibt 0700, ein scheiterndes `chmod` (PATH-Stub) ist eine Warnung mit Exit 0, `--check` nennt das Konto. Doku: Werkzeuge unter anderen Konten brauchen Gruppe oder root, bestehende Installationen bekommen den Modus beim Update, `--dir` nennt ein eigenes Verzeichnis, ein vorher erreichbares Konto entfernen oder umnummerieren.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: die Dateien dieser Task
Abhängt von: T1

## Entscheidungen
- 2026-10-29 T2 (Prüfung): „0750“ (Kevin) als Obergrenze gelesen: `g-w,o-rwx` erreicht 0750 aus 0755/0775 und lockert ein strengeres 0700 nicht (Security-Fund); `--check` zeigt die Warnung, weil sie nur liest.
- 2026-10-29 Kevin: Installationsverzeichnis 0750, Warnung (kein Abbruch) bei Host-Konto mit UID 10001 oder 70, Doku; abgeleitetes Postgres-Image nein. Eigentümer bleibt der Installierende statt root:root (Nicht-root-Installation).
