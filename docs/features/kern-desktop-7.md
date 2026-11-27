<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-7 — Desktop: SFTP-Upload über eine Teil-Datei, Feed nach dem Abmelden

Roadmap: R-1708 (BUG), R-1830 (BUG). Beide von Kevin am 2026-11-27 angenommen.

## Problem
- **R-1708:** Der SFTP-Upload (`apps/desktop/src-tauri/src/sftp.rs`) öffnet das Ziel direkt mit `WRITE|CREATE` und
  `TRUNCATE` bzw. `EXCLUDE`. Er räumt bei einem Fehler nicht auf.
  - Bricht die Verbindung während eines bestätigten Überschreibens ab, ist die Datei auf dem Host abgeschnitten.
  - Ohne Überschreiben bleibt eine Teil-Datei unter dem endgültigen Namen.
  - Der Download macht es schon richtig: Teil-Datei, `sync_all`, Umbenennen.
  - Ein erster Bau (kern-desktop-6 T8) kam bis zur dritten Prüfrunde. Offen blieb dort, dass die Teil-Datei ohne
    `EXCLUDE` geöffnet wurde: Ein vorhandener Eintrag oder Symlink unter `.<name>.ah-part` wurde übernommen.
- **R-1830:** `fetchFeedOnce` (`apps/desktop/ui/src/lib/stores/notifications.ts`) prüft `logoutGen` nicht.
  - Kommt eine Antwort nach `deactivateNotifications` an, füllt sie die Liste und setzt `primed` der alten Sitzung.
  - Der Rückstand der neuen Sitzung kann dann OS-Meldungen auslösen.

## Ziel und Nicht-Ziele
- Ein Upload schreibt nach `.<name>.ah-part` im Zielordner und benennt erst danach um. Bei jedem Fehler entfernt er
  die Teil-Datei.
  - Vor dem Schreiben entfernt er einen alten Eintrag unter dem Teil-Namen und legt die Teil-Datei dann mit
    `WRITE|CREATE|EXCLUDE` neu an. Ein Symlink unter diesem Namen wird damit nie verfolgt.
  - Überschreiben bleibt eine Wahl des Nutzers. Ohne `overwrite` schlägt der Upload fehl, wenn das Ziel existiert,
    wie heute.
- Eine Feed-Antwort, die nach dem Abmelden ankommt, ändert nichts mehr: der Wächter `logoutGen`, wie in `loadCenter`.
- Nicht-Ziel: Fortsetzen abgebrochener Uploads, ein anderes Dialogverhalten.

## Betroffene Dateien
`apps/desktop/src-tauri/src/sftp.rs`, `apps/desktop/ui/src/lib/stores/notifications.ts` samt `notifications.test.ts`,
`docs/developer/desktop.html` und `docs/en/developer/desktop.html` (der SFTP-Absatz), `changelog.d/kern-desktop-7.md`.

## Risiken und Rollback
- **Upload:** `posix-rename@openssh.com` gibt es nicht auf jedem Server. Ohne diese Erweiterung entfernt der Upload
  beim Überschreiben zuerst das Ziel und benennt dann um. Dazwischen liegt ein kurzes Fenster ohne Datei, aber nie
  eine abgeschnittene Datei.
  - Die Rechte werden ab dem ersten Byte gesetzt, wie im ersten Bau.
  - Rollback: je ein Revert der Task-Commits.
- **Feed:** nur ein zusätzlicher Wächter.

## Doku-Impact
Der SFTP-Absatz in `docs/developer/desktop.html` (DE und EN) beschreibt heute, dass ein Upload das Ziel direkt
öffnet. Er bekommt die Teil-Datei. Dazu kommt der CHANGELOG.
