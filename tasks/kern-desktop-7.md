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
- Aus kern-desktop-6 übernommen (dort entschieden): russh-sftp 3.0.1 kennt kein `posix-rename@openssh.com`, darum entfernt der Upload beim Überschreiben das Ziel unmittelbar vor dem Umbenennen. Ein Link am Ziel wird aufgelöst und durchgeschrieben, die Datei, auf die er zeigt, wird ersetzt; der Link bleibt. Die Angaben `posix-rename` und „Symlink am Ziel wird ersetzt“ in T1 beschreiben den Plan, nicht den Bau.
- Kevin 2026-11-27: Beim Überschreiben übernimmt der Upload Eigentümer und Gruppe der alten Datei best-effort (scheitert das `SETSTAT`, bleiben sie die des Hochladenden). Hardlinks, ACLs und eine beschreibbare Datei in einem schreibgeschützten Ordner sind hingenommen und dokumentiert.
- Kevin 2026-11-27: Branch-Prüfung Runde 2 request_changes (zwei kleine wichtig) → T7/T8 bauen, derselbe Prüfer prüft in einer dritten Runde nur das Delta.
- T7: der Rückfall (fremde Datei, nur die Gruppe) hat keinen Test: er braucht eine alte Datei eines anderen Nutzers, also root auf der Testmaschine. SFTP trägt uid und gid in einem Feld (russh-sftp schickt eine fehlende uid als 0), darum geht die Gruppe mit der eigenen uid der Teil-Datei.

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

### T2 — R-1830: Feed-Antwort nach dem Abmelden verwerfen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ef42976aa 2026-11-27T15:44:09+01:00
Review: am Ende (Branch-Review)
Änderung: `fetchFeedOnce` merkt sich `logoutGen` vor dem Abruf. Hat sich der Wert danach geändert, verwirft die Funktion die Antwort: keine Liste, kein `primed`, keine OS-Meldung. Test (zuerst rot): Das Abmelden kommt während eines offenen Abrufs. Danach bleibt die Liste leer, und der erste Abruf der neuen Sitzung löst keine OS-Meldung für den Rückstand aus.
Beweis: reviewer kern-desktop-6 T11 2026-11-27 (vorbestehend), apps/desktop/ui/src/lib/stores/notifications.ts:94
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/notifications.test.ts
Doku: keine (Fehlerverhalten ohne dokumentierte Beschreibung; CHANGELOG in T3)

### T3 — Doku DE+EN und Changelog  [x]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-desktop-7.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @764052404 2026-11-27T15:46:48+01:00
Review: am Ende (Branch-Review)
Änderung: Der SFTP-Absatz beschreibt den Upload über die Teil-Datei, das Umbenennen und das Aufräumen. Der Changelog-Eintrag nennt beide Fixes.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

### T4 — R-1708: Eigentümer best-effort, Abbruch-Test, der fällt  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @345ec7e02 2026-11-27T16:37:17+01:00
Review: am Ende (Branch-Review)
Änderung: Beim Überschreiben setzt der Upload uid/gid der alten Datei auf die Teil-Datei, vor dem Modus, Fehler ignoriert. Der Abbruch-Test tötet den sftp-server nach dem ersten Fortschritt (vorher scheiterte er schon am INIT und fiel ohne den Fix nicht). Ein Test zeigt, dass eine Gruppe des Hochladenden erhalten bleibt. Ein Testname beschreibt nicht mehr das alte Abschneiden.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp::
Doku: → T6

### T5 — R-1830: Test für Abmelden während `fetchUnreadCount`  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ba71335f4 2026-11-27T16:42:22+01:00
Review: am Ende (Branch-Review)
Änderung: Ein Test hält `fetchUnreadCount` an, meldet ab und zeigt, dass die späte Antwort weder Liste noch Badge füllt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/notifications.test.ts
Doku: keine (nur Test)

### T6 — Doku und Spec an den Bau angleichen  [x]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/features/kern-desktop-7.md, changelog.d/kern-desktop-7.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @655f8ab7c 2026-11-27T16:47:26+01:00
Review: am Ende (Branch-Review)
Änderung: Der SFTP-Absatz sagt, dass eine abgebrochene Verbindung die Teil-Datei bis zum nächsten Upload liegen lässt, nennt die Übernahme des Eigentümers und die hingenommenen Folgen (Hardlinks, ACLs, schreibgeschützter Ordner). Die Spec beschreibt den Umbenenn-Weg ohne `posix-rename` und die Risiken.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

### T7 — R-1708: Gruppe auch bei fremdem Eigentümer übernehmen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f1bf1f497 2026-11-27T20:16:01+01:00
Review: am Ende (Branch-Review)
Änderung: Scheitert das Setzen von uid und gid der alten Datei (sie gehört einem anderen Nutzer), versucht der Upload die Gruppe allein, mit der eigenen uid der Teil-Datei; best-effort wie vorher.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp::
Doku: keine (desktop.html sagt schon: Gruppe, wo der Server es erlaubt)

### T8 — R-1830: waitFor im Badge-Test mit 30 s Obergrenze  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/notifications.test.ts
Änderung: `vi.waitFor` im Test „a badge count that arrives after deactivate fills nothing“ wartet bis 30 s statt der Vorgabe von 1 s (testing.md).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/notifications.test.ts
Doku: keine (nur Test)
