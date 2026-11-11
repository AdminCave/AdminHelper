<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-server-1 — Task-Ledger
Status: bereit · Branch: feature/klein-kommentare-server-1 · Review: am Ende
Spec: docs/features/klein-kommentare-server-1.md (Roadmap R-1181)
Heavy: none — nur ein Kommentar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1181: Kommentar zu `NotificationOutbox.title` passt zur Matrix je Person  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/models.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9156361c2 2026-11-11T12:55:06+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer kern-notify-2 2026-11-07 · feature/kern-notify-2@121c95dd8 apps/server/app/modules/notifications/models.py:175-177 · Dedup-Key: REF:server:notifications/models.py:NotificationOutbox.title
Änderung: Der Kommentar vor `title` sagt nicht mehr, ein Bündel-Kanal nenne nur die Server der Abonnements, die ihn verlangt haben (seit R-1080 wählt die Matrix der Person die Kanäle; "bell" und "out" nennen dieselben Server, `service.resolve_recipients`). Kein Verhalten ändert sich.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notification_channels.py
Doku: keine (interner Kommentar)
