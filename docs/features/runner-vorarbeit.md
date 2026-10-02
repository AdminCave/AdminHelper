<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Runner-Vorarbeit für Stufe 7: geteilte Python-Sperre, robuster Klon im Setup

Roadmap: R-0080, R-0077 · Stand: main@9fa298ed · Geplant 2026-10-02 von der Aufsicht, Entscheidungen Kevin 2026-10-02

## Problem / Motivation

**Die Python-Sperre gilt je Unix-Nutzer (R-0080).** `scripts/tests/run.sh` lässt die beiden schweren
Python-Schritte (`server-pytest`, `schemathesis`) über `flock` nacheinander laufen, damit zwei Server-Suiten
einander nicht die Tabellen und den Speicher nehmen (OOM-Killer am 2026-09-21). Die Sperrdatei steht fest unter
`$HOME/.cache/adminhelper-py.lock` (`run.sh:248`); der Kommentar dazu sagt selbst, dass eine Sperre über
Nutzergrenzen „still to come“ ist (`run.sh:242–243`). Ab Stufe 7 fährt `adminhelper-runner` Suiten auf derselben
Box wie Kevins Sessions. Kevins Home ist `0700`, der Runner erreicht seine Sperrdatei also nie: zwei
Schemathesis-Läufe wären wieder gleichzeitig möglich.

**Das Setup klont in jedes Verzeichnis ohne `.git` (R-0077).** `scripts/dev/runner-setup.sh` prüft vor dem
Klon nur `[ -d "$SRV/repo/.git" ]` (`runner-setup.sh:240`) und klont sonst als root direkt nach `$SRV/repo`
(`:244`). `/srv/ah` gehört nach dem ersten Lauf dem Runner (`chown -R`, `:246`). Robuster ist ein Setup, das
nur in einen Pfad klont, den es noch nicht gibt, und bei einem vorhandenen Verzeichnis ohne `.git` abbricht,
statt hineinzuklonen.

Beides sind Voraussetzungen für Stufe 7 (Worker unter `adminhelper-runner`).

## Ziel & Nicht-Ziele

**Ziel**
- Eine Sperrdatei, die Kevin und der Runner teilen: `/var/lib/adminhelper-dev/py.lock`, angelegt von
  `runner-setup.sh`. `run.sh` nimmt sie, sobald sie existiert; ohne sie bleibt alles wie heute (je Nutzer).
- Der Halter der Sperre bleibt sichtbar („held by: …“), auch über Nutzergrenzen; die Zeile wird vor der Ausgabe
  gereinigt.
- `runner-setup.sh` klont nur in einen Pfad, den es noch nicht gibt; ein vorhandenes `$SRV/repo` ohne `.git`
  bricht mit einem Satz ab.
- Das Red Team (`runner-redteam.sh`) prüft, dass der Runner die geteilte Sperre nehmen kann und sie nicht
  ersetzen kann.

**Nicht-Ziele**
- Keine Sperre für andere Schritte (Lint, Go, Rust, Node bleiben parallel).
- `/srv/ah` bleibt Runner-eigen: `lane.sh` legt Lanes unter `../AdminHelper-<slug>` an (`lane.sh:131`), der
  Runner braucht dort Schreibrecht. Wo Runner-Lanes liegen, ist eine Frage von Stufe 7.
- Kein Umbau von `chown -R` in Schritt 2 und keine Gruppen-Änderung an Kevins Konto.
- `pytest` von Hand läuft weiter an der Sperre vorbei (DEVELOPMENT.md, wie heute).

## Betroffene Komponenten & Dateien

| Datei | Änderung |
|---|---|
| `scripts/dev/runner-setup.sh` | Schritt 2: Klon über ein root-eigenes Temp-Verzeichnis und `mv -T`, Abbruch bei `$SRV/repo` ohne `.git` (T1); neuer Schritt: Verzeichnis und Sperrdatei anlegen, `--remove` nimmt sie weg (T2) |
| `scripts/tests/runner_setup_test.sh` | Plan-Prüfungen für T1/T2 (Dry-Run) |
| `scripts/tests/run.sh` | Wahl der Sperrdatei, Öffnen mit Rückfall, gereinigte Halter-Zeile (T3) |
| `scripts/tests/lane_test.sh` | Tests auf eigene Temp-Pfade, neue Fälle (T3) |
| `scripts/dev/runner-redteam.sh` | Prüfung der geteilten Sperre als eigener Schritt (T5) |
| `scripts/tests/redteam_test.sh` | hermetischer Test dieses Schritts (T5) |
| `DEVELOPMENT.md`, `CHANGELOG.md` | Doku (T4, T5) |

Alle Skripte außer `lane_test.sh` und `redteam_test.sh` stehen in `scripts/dev/harness-paths.txt`: Bau
interaktiv, Review mit Opus, eine Runde (Review-Disziplin 2026-10-02).

## Design

### Die geteilte Sperre (T2, T3)

- **Ort:** `/var/lib/adminhelper-dev/py.lock`. Nicht unter `/etc/adminhelper` oder `/var/lib/adminhelper`: das
  Agent-Paket nutzt `/etc/adminhelper` und löscht es in `postrm` (`apps/agent/deb/DEBIAN/postrm`); der
  Dev-Pfad soll mit dem Produkt nie kollidieren. Nicht unter `/srv/ah`, das dem Runner gehört.
- **Besitz und Rechte:** Verzeichnis `root:root 0755` (nur root kann die Datei anlegen, löschen oder ersetzen),
  Datei `root:root 0666` (Kevin und der Runner können sie zum Anhängen öffnen und die Halter-Zeile schreiben).
  Kein Sticky-Verzeichnis, `fs.protected_regular` greift also nicht (es betrifft `O_CREAT`-Opens in
  allen- bzw. gruppen-schreibbaren Sticky-Verzeichnissen, proc_sys_fs(5)).
- **Wer sie anlegt:** `runner-setup.sh` als root, nur wenn sie fehlt. Eine vorhandene Datei wird nur auf
  Besitzer und Modus gezogen (`chown`/`chmod`), nie neu angelegt: ein neues Inode, während ein Lauf die Sperre
  auf dem alten hält, teilte die Sperre in zwei. `--remove` entfernt Datei und Verzeichnis.
- **Welche Datei `run.sh` nimmt**, in dieser Reihenfolge:
  1. `AH_PY_LOCK_FILE` aus der Umgebung (neu, damit die Tests eigene Pfade haben),
  2. die geteilte Datei, wenn sie existiert (`AH_PY_LOCK_SHARED`, Default `/var/lib/adminhelper-dev/py.lock`),
  3. sonst wie heute `$HOME/.cache/adminhelper-py.lock` — Kevins Box ohne Runner-Setup, VMs, CI.
- **Öffnen:** erst `exec 9>>` (mit Halter-Zeile), sonst `exec 9<` (die Sperre wirkt trotzdem: flock(2) „A
  shared or exclusive lock can be placed on a file regardless of the mode in which the file was opened“, auf
  dieser Box nachgemessen), sonst Selbst-SKIP 75 mit Pfad und Abhilfe (`runner-setup.sh` erneut, oder
  `AH_PY_LOCK=0`). Existiert die geteilte Datei, fällt `run.sh` **nie still** auf die Datei je Nutzer zurück:
  das teilte die Sperre wieder.
- **Halter-Zeile:** Die Datei ist eine Grenze zwischen zwei Nutzern. Vor der Ausgabe wird die Zeile auf
  druckbares ASCII reduziert und gekürzt (`LC_ALL=C tr -cd '[:print:]'`, 200 Zeichen), damit kein Steuerzeichen
  ein Terminal erreicht.
- **Bekannte Grenze:** Legt das Setup die Datei an, während Läufe mit der alten Datei je Nutzer laufen, gibt es
  für diese Läufe einmalig zwei Sperren. Neue Läufe treffen sich an der geteilten.

### Der Klon im Setup (T1)

- `$SRV/repo` mit `.git`: wie heute, kein Klon.
- `$SRV/repo` existiert in irgendeiner Form ohne `.git` (Verzeichnis, Datei, Link): Abbruch mit Satz und
  Abhilfe, auch unter `--dry-run` (damit testbar).
- `$SRV/repo` existiert nicht: root klont in ein frisches Verzeichnis
  `mktemp -d -p "$(dirname "$SRV")" .ah-clone.XXXXXX` und verschiebt den Klon mit `mv -T` an seinen Platz; das
  Temp-Verzeichnis wird danach (und bei einem Fehler) entfernt. Vorher prüft das Skript, dass das
  Elternverzeichnis von `$SRV` root gehört und nicht für andere schreibbar ist (`/srv`: `root 0755`, gemessen
  2026-10-02), sonst Abbruch. `mv -T` ersetzt höchstens ein leeres Verzeichnis und scheitert an einem
  nicht-leeren; dann bricht das Setup ab.
- `/srv` und `/srv/ah` liegen auf einem Dateisystem (gemessen), `mv -T` ist also ein `rename(2)`.

### Die Prüfung im Red Team (T5)

Ein eigener Schritt wie `--verdict`: `runner-redteam.sh --py-lock <pfad>` gibt `ok`/`FAIL`-Zeilen aus und ist
hermetisch testbar; der normale Lauf ruft ihn mit dem echten Pfad auf. Geprüft wird: die Datei existiert, ihr
Verzeichnis ist für den Runner nicht schreibbar (er kann sie weder löschen noch ersetzen), Datei und
Verzeichnis gehören root, und `flock -n` auf der Datei gelingt (ist sie gerade belegt, ein `info`, kein
`FAIL`). Die erwartete Eigentümer-UID ist für den hermetischen Test überschreibbar; Kevin fährt das Red Team
mit `sudo -u`, das die Umgebung nicht durchreicht.

## Datenmodell / API / Migrationen

Keine. Kein Server-, Client- oder Wire-Format-Vertrag ist berührt.

## Externe Integrationen

Keine. Linux-Grundlagen: flock(2) (Lock unabhängig vom Öffnungsmodus), proc_sys_fs(5) (`protected_regular`),
rename(2) (ein Verzeichnis ersetzt nur ein leeres). `fs.protected_regular=2` auf Kevins Box gemessen.

## Trade-offs & Alternativen

- **Sperrdatei `0666` mit Halter-Zeile (gewählt, Kevin)** gegen `0644` nur lesend (kein Schreibkanal, aber
  keine Halter-Angabe mehr, auch nicht für Kevins eigene Checkouts) und gegen eine Gruppe aus Kevin und Runner
  (`0660`, aber `usermod -aG` an Kevins Konto und neu anmelden). Der einzige zusätzliche Kanal bei `0666` ist
  eine Textzeile, die gereinigt ausgegeben wird.
- **Halter über `/proc/locks`** statt in der Datei: verworfen. Dort steht die PID des schon beendeten
  `flock(1)`-Prozesses, nicht die des Halters (auf dieser Box nachgemessen).
- **Klon über Temp-Verzeichnis und `mv -T` (gewählt, Kevin)** gegen nur den Abbruch: Der Abbruch allein lässt
  das Zeitfenster zwischen Prüfung und `git clone` offen (`git clone` akzeptiert ein leeres vorhandenes
  Verzeichnis). Gegen `/srv/ah` root-eigen: bräche `lane.sh` für den Runner (siehe Nicht-Ziele).
- **Pfad `/var/lib/adminhelper-dev` (gewählt, Aufsicht)** gegen `/run/lock` (tmpfs, nach dem Neustart weg,
  bräuchte `tmpfiles.d`; Sticky-Verzeichnis, in dem jeder Nutzer den Namen vorab belegen kann).

## Risiken & Rollback

- **Ein Lauf hängt an der geteilten Sperre:** wie heute bis `AH_PY_LOCK_WAIT`, dann SKIP mit Grund. Der Runner
  kann Kevins Python-Suiten so verzögern; das ist gewollt (sonst OOM).
- **Geteilte Datei mit falschem Modus:** der Rückfall auf `exec 9<` hält die Sperre trotzdem, nur die
  Halter-Zeile fehlt. Nicht öffnbar ⇒ SKIP mit Abhilfe, unter `--strict` rot.
- **Tests:** dürfen weder Kevins echte Sperre noch `/var/lib/adminhelper-dev` berühren (T3 stellt das um; heute
  hält `lane_test.sh:381` bis zu 60 s Kevins echte Sperre).
- **Rollback:** Revert der Commits; `sudo bash scripts/dev/runner-setup.sh --remove --yes` nimmt die Sperrdatei
  mit. Ohne die Datei fällt `run.sh` auf die Sperre je Nutzer zurück.

## Kevins Handarbeit nach dem Merge

1. `sudo bash scripts/dev/runner-setup.sh` erneut fahren: legt `/var/lib/adminhelper-dev/py.lock` an; am
   bestehenden Klon ändert sich nichts (`.git` ist da).
2. `sudo -u adminhelper-runner git -C /srv/ah/repo pull --ff-only`.
3. `sudo -u adminhelper-runner bash /srv/ah/repo/scripts/dev/runner-redteam.sh` — die neue Prüfung (T5) muss
   `ok` zeigen.
4. Optional, als Gegenprobe: in Kevins Shell `flock /var/lib/adminhelper-dev/py.lock sleep 30 &`, dann
   `sudo -u adminhelper-runner flock -n /var/lib/adminhelper-dev/py.lock true` — muss scheitern (Exit 1).

## Doku-Impact

DEVELOPMENT.md: der Absatz zur Python-Sperre (`DEVELOPMENT.md:216–226`) und der Runner-Abschnitt
(`DEVELOPMENT.md:704ff`: „Setup erneut fahren“, die neue Red-Team-Prüfung); CHANGELOG. Keine Seite unter
`docs/` nennt die Sperre.

## Offene Fragen

Keine. Entschieden 2026-10-02: Modus `0666` mit gereinigter Halter-Zeile (Kevin), Klon über Temp-Verzeichnis
und `mv -T` mit Abbruch bei `$SRV/repo` ohne `.git` (Kevin), Red-Team-Prüfung ja (Aufsicht), Pfad
`/var/lib/adminhelper-dev/py.lock` (Aufsicht).
