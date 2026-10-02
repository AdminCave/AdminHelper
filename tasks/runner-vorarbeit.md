<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Runner-Vorarbeit für Stufe 7 (R-0080, R-0077) — Task-Ledger
Status: aktiv · Branch: harness/runner-vorarbeit · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus, eine Runde) · Modell: Opus
Freigabe: Kevin, 2026-10-02 (Design-Gate, „Runner-Vorarbeit“ freigegeben), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/runner-vorarbeit.md (Roadmap R-0080, R-0077)
Heavy: none — nur Skripte (run.sh-Sperre, runner-setup.sh, Red Team) und ihre hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad. Den Beweis über zwei echte Nutzer liefern Kevins Setup- und Red-Team-Lauf nach dem Merge (Spec, „Kevins Handarbeit“).
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-02 von der Aufsicht (adminhelper-ac) auf Kevins Wort (Entscheidungen 2026-10-02: Sperrdatei
`0666` mit gereinigter Halter-Zeile, Klon über root-eigenes Temp-Verzeichnis und `mv -T`; Aufsicht: Red-Team-
Prüfung ja, Pfad `/var/lib/adminhelper-dev/py.lock`). Branch `harness/`, weil `run.sh`, `runner-setup.sh` und
`runner-redteam.sh` Harness-Pfade sind: Bau interaktiv, keine Lane. Kein sudo im Bau: alles, was root braucht,
wird über `--dry-run` und hermetische Tests geprüft; der echte Lauf ist Kevins Handarbeit nach dem Merge.

### T1 — runner-setup.sh klont nur in einen Pfad, den es noch nicht gibt  [x]
Komponente: scripts · Dateien: scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d0c532b9 2026-10-02T16:17:43+02:00
Review: approve (opus), nits miterledigt
Änderung: Schritt 2 (`runner-setup.sh:224–246`): Ein vorhandenes `$SRV/repo` ohne `.git` (Verzeichnis, Datei
oder Link) bricht mit Satz und Abhilfe ab, auch unter `--dry-run`. Fehlt `$SRV/repo`, klont root in ein frisches
`mktemp -d -p "$(dirname "$SRV")" .ah-clone.XXXXXX` und verschiebt mit `mv -T` an seinen Platz; das
Temp-Verzeichnis wird danach und bei einem Fehler entfernt. Vorher prüft der echte Lauf, dass das
Elternverzeichnis von `$SRV` root gehört und für andere nicht schreibbar ist. `$SRV/repo` mit `.git` bleibt wie
heute (kein Klon). Tests über `AH_RUNNER_DRY_SRV` (nur unter `--dry-run`, `runner-setup.sh:77–80`): Verzeichnis
ohne `.git` ⇒ Exit ≠ 0 mit dem Satz; mit `.git` ⇒ „would be skipped“; ohne `$SRV/repo` ⇒ der Plan zeigt
`mktemp`, `git clone … <temp>/repo` und `mv -T … $SRV/repo` in dieser Reihenfolge; die bestehende Prüfung „root
runs no git inside the runner's clone“ (`runner_setup_test.sh:99–100`) bleibt grün.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T4)

### T2 — runner-setup.sh legt die geteilte Python-Sperre an  [x]
Komponente: scripts · Dateien: scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7a89a840 2026-10-02T16:31:30+02:00
Review: request_changes (opus) → behoben: Inode statt mtime im Dry-Run-Fingerabdruck; nits miterledigt
Änderung: Neuer Schritt nach Schritt 2: `/var/lib/adminhelper-dev` als `root:root 0755` (`no_symlink_in`, dann
`install -d`), darin `py.lock` als `root:root 0666` — anlegen nur, wenn die Datei fehlt; eine vorhandene nur auf
Besitzer und Modus ziehen (`chown`/`chmod`), nie neu anlegen, weil ein neues Inode eine gehaltene Sperre teilte.
`--remove` (`runner-setup.sh:165–187`) entfernt Datei und Verzeichnis, wiederholbar. Pfad unter `--dry-run`
überschreibbar wie `AH_RUNNER_DRY_SRV` (etwa `AH_RUNNER_DRY_LOCKDIR`), im echten Lauf ignoriert. Tests: der Plan
enthält beide `install`-Zeilen mit Besitzer und Modus; mit vorhandener Datei kein `install` der Datei, sondern
`chown`/`chmod`; der `--remove`-Plan nimmt beides weg; der Dry-Run ändert nichts (`system_state` um den
Lock-Pfad erweitert).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T4)

### T3 — run.sh nimmt die geteilte Sperre, wenn es sie gibt  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/lane_test.sh
Änderung: Wahl der Sperrdatei (`run.sh:248`): `AH_PY_LOCK_FILE` aus der Umgebung, sonst die geteilte Datei
(`AH_PY_LOCK_SHARED`, Default `/var/lib/adminhelper-dev/py.lock`), wenn sie existiert, sonst wie heute
`$HOME/.cache/adminhelper-py.lock`. `py_lock` (`run.sh:255–272`) öffnet erst mit `exec 9>>`, sonst mit `exec 9<`
(Sperre ohne Halter-Zeile), sonst Selbst-SKIP 75 mit Pfad und Abhilfe — kein stiller Rückfall auf die Datei je
Nutzer, wenn die geteilte existiert. Die Halter-Zeile wird vor der Ausgabe gereinigt (`LC_ALL=C tr -cd
'[:print:]'`, 200 Zeichen). Kommentar `run.sh:235–247` nachziehen. `lane_test.sh` (`:339`, `:342`, `:381`):
alle Läufe mit eigenem `AH_PY_LOCK_SHARED`/`AH_PY_LOCK_FILE` unter `$WORK`, nie Kevins echte Sperre oder
`/var/lib/adminhelper-dev`. Neue Fälle: geteilte Datei vorhanden ⇒ zwei Läufe serialisieren auf ihr; geteilte
Datei fehlt ⇒ Rückfall je Nutzer (mit Temp-`HOME`); geteilte Datei nur lesbar (`0444`) ⇒ Sperre wirkt, kein
Abbruch; nicht öffnbar (`0000`, nur wenn nicht root) ⇒ SKIP mit Grund, unter `--strict` rot; Halter-Zeile mit
Escape-Sequenz ⇒ Ausgabe ohne Steuerzeichen. Die bestehenden Fälle (`lane_test.sh:358–403`) bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T4)

### T4 — Doku: geteilte Sperre und Setup  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, CHANGELOG.md
Änderung: DEVELOPMENT.md, Absatz „Die schweren Python-Schritte laufen je Nutzer nacheinander“
(`DEVELOPMENT.md:216–226`): die geteilte Datei, die Reihenfolge der Wahl, der Rückfall, `AH_PY_LOCK_FILE`/
`AH_PY_LOCK_SHARED`. Runner-Abschnitt (`DEVELOPMENT.md:704ff`): das Setup legt die Sperre an und klont nur in
einen Pfad, den es noch nicht gibt; ein bestehender Runner bekommt die Sperre mit einem erneuten
`sudo bash scripts/dev/runner-setup.sh`. CHANGELOG-Eintrag (Harness).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, CHANGELOG.md
Abhängt von: T1, T2, T3

### T5 — Red Team prüft die geteilte Sperre  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh, DEVELOPMENT.md
Änderung: Eigener Schritt wie `--verdict`: `runner-redteam.sh --py-lock <pfad>` gibt `ok`/`FAIL`/`info`-Zeilen
aus; der normale Lauf ruft ihn mit `/var/lib/adminhelper-dev/py.lock` auf (neuer Abschnitt nach „0. the
environment“, `runner-redteam.sh:147`). Geprüft: Datei existiert (sonst `FAIL`, Abhilfe `runner-setup.sh`),
Verzeichnis für diesen Nutzer nicht schreibbar, Datei und Verzeichnis gehören der erwarteten UID (Default 0,
für den hermetischen Test überschreibbar), `flock -n` gelingt (belegt ⇒ `info`, kein `FAIL`).
`redteam_test.sh`: je Zweig ein Fall mit Temp-Dateien (fehlt, Verzeichnis schreibbar, falscher Besitzer,
belegt, alles in Ordnung). DEVELOPMENT.md: ein Satz im Runner-Abschnitt, was das Red Team zusätzlich prüft.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Runner-Abschnitt, ein Satz)
Abhängt von: T2
