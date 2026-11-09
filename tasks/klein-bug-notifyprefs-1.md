<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-bug-notifyprefs-1 — Desktop: Speichern der Benachrichtigungs-Einstellungen, Ton, Incident-Typ (R-1184, R-1183, R-1150) — Task-Ledger
Status: aktiv · Branch: feature/klein-bug-notifyprefs-1 · Review: am Ende
Spec: docs/features/klein-bug-notifyprefs-1.md (Roadmap R-1184, R-1183, R-1150)
Heavy: none — reine Desktop-UI ohne Stack-, Gateway- oder Install-Pfad; die Journey „Einstellungen speichern“ deckt der Komponententest mit gemocktem Server
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@281371546`. R-1185 fährt nicht mit (Überlappung `dictionaries.ts` mit `feature/kern-ansible-1`) und steht in `tasks/klein-ui-desktop-1.md`.

### T1 — Speichern übersteht Etc/Unknown und geleertes Zeitfeld (R-1184)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/NotificationPrefs.svelte, apps/desktop/ui/src/components/NotificationPrefs.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @3e8480cb9 2026-11-09T13:51:30+01:00
Review: am Ende (Branch-Review)
Beweis: review kern-notify-3 2026-11-07, feature/kern-notify-3@b80c1e947, `NotificationPrefs.svelte` (`save`: `timezone` aus `Intl…resolvedOptions().timeZone`, `quiet` unverändert); der Server weist `Etc/Unknown` und ein Feld ohne `HH:MM` mit 422 ab (`apps/server/app/modules/notifications/schemas.py`: `_check_timezone`, `ClockTime`)
Dedup-Key: bug:desktop-ui:NotificationPrefs.svelte:save-timezone
Änderung: Erst zwei Tests rot (Zone `Etc/Unknown` → die Anfrage trägt kein `timezone`; geleertes Start-/Endfeld → die Anfrage trägt den zuletzt gespeicherten Wert). Dann `save()`: `timezone` nur mitsenden, wenn die Zone nicht leer und nicht `Etc/Unknown` ist; `quiet.start`/`quiet.end` fallen bei keinem `HH:MM` auf den Stand aus `apply()` zurück (neuer `storedQuiet`).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/NotificationPrefs.test.ts
Doku: keine (Fehlerbehebung ohne dokumentiertes Verhalten)

### T2 — Kritisch-Ton: AudioContext fortsetzen (R-1183)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/sound.ts, apps/desktop/ui/src/lib/sound.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @a004cdb66 2026-11-09T13:56:28+01:00
Review: am Ende (Branch-Review)
Beweis: review kern-notify-3 2026-11-07, feature/kern-notify-3@b80c1e947, `apps/desktop/ui/src/lib/sound.ts` (`playCriticalTone` ohne `resume`)
Dedup-Key: bug:desktop-ui:sound.ts:playCriticalTone
Änderung: Neue Testdatei `sound.test.ts` (SPDX-Header) mit einem `AudioContext`-Stub, der `suspended` startet: rot, solange `resume()` nicht aufgerufen wird. Dann `playCriticalTone`: bei `ctx.state === 'suspended'` `void ctx.resume()` (Fehler verschluckt wie bisher), der Ton wird trotzdem eingeplant.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/sound.test.ts
Doku: keine (Fehlerbehebung ohne dokumentiertes Verhalten)

### T3 — IncidentEntry.severity kennt ok (R-1150)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.ts
Beweis: reviewer branch arch-notify-incidents 2026-11-05, feature/arch-notify-incidents@67126bba, `apps/desktop/ui/src/lib/api/types.ts:685` (der Hub schreibt bei Erholungen `ok`)
Dedup-Key: ref:desktop-ui:api/types.ts:IncidentEntry
Änderung: `severity: NotificationSeverity | 'ok' | null` mit einem Satz Kommentar, wer `ok` schreibt. Refactor: `npm run check` und die Vertragstests vorher und nachher grün.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts
Doku: keine (interner Typ)
