<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-7 — Desktop: SFTP-Upload über eine Teil-Datei, Feed nach dem Abmelden — Task-Ledger
Status: aktiv · Branch: feature/kern-desktop-7 · Review: am Ende
Spec: docs/features/kern-desktop-7.md (Roadmap R-1708, R-1830)
Heavy: linux-full — Desktop (SFTP-Datenpfad, Benachrichtigungen); kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-27: R-1708 und R-1830 angenommen (Notizen der Zeilen).
- Plan: T1 baut auf dem Stand aus kern-desktop-6 T8 (Prüfrunde 3) auf. Neu ist dabei: `remove_file(part)`, danach `WRITE|CREATE|EXCLUDE`.

### T1 — R-1708: SFTP-Upload über `.<name>.ah-part`  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @e3a187a4c 2026-11-27T15:38:32+01:00
Review: am Ende (Branch-Review)
Änderung: Der Upload entfernt einen alten Eintrag unter dem Teil-Namen und legt die Teil-Datei mit `WRITE|CREATE|EXCLUDE` an.
  - Die Rechte gelten ab dem ersten Byte.
  - Danach benennt er um: beim Überschreiben mit `posix-rename@openssh.com`, sonst entfernt er das Ziel und benennt um.
  - Ohne `overwrite` scheitert er an einem vorhandenen Ziel.
  - Bei jedem Fehler entfernt er die Teil-Datei.
  - Tests gegen den OpenSSH-sftp-server:
    - Ein abgebrochener Upload lässt die alte Datei unverändert und hinterlässt keine Teil-Datei.
    - Ein Symlink unter dem Teil-Namen wird nicht verfolgt.
    - Ein Symlink am Ziel wird ersetzt, nicht beschrieben.
    - Überschreiben geschieht nur auf Wunsch.
Beweis: main@6895f8eaf apps/desktop/src-tauri/src/sftp.rs:432-458 (Code-Lesung) · Dedup-Key: bug:desktop-rs:sftp.rs:upload-not-atomic
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp::
Doku: → T3

### T2 — R-1830: Feed-Antwort nach dem Abmelden verwerfen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/notifications.test.ts
Änderung: `fetchFeedOnce` merkt sich `logoutGen` vor dem Abruf. Hat sich der Wert danach geändert, verwirft die Funktion die Antwort: keine Liste, kein `primed`, keine OS-Meldung. Test (zuerst rot): Das Abmelden kommt während eines offenen Abrufs. Danach bleibt die Liste leer, und der erste Abruf der neuen Sitzung löst keine OS-Meldung für den Rückstand aus.
Beweis: reviewer kern-desktop-6 T11 2026-11-27 (vorbestehend), apps/desktop/ui/src/lib/stores/notifications.ts:94
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/notifications.test.ts
Doku: keine (Fehlerverhalten ohne dokumentierte Beschreibung; CHANGELOG in T3)

### T3 — Doku DE+EN und Changelog  [ ]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-desktop-7.md
Änderung: Der SFTP-Absatz beschreibt den Upload über die Teil-Datei, das Umbenennen und das Aufräumen. Der Changelog-Eintrag nennt beide Fixes.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
