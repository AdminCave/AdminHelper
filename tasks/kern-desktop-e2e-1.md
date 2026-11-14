# desktop_e2e_monitoring: Fund ohne Instanz — Task-Ledger
Status: erledigt · Branch: feature/kern-desktop-e2e-1 · Review: am Ende
Spec: Roadmap R-1456
Heavy: linux-full — Desktop-Journey; der Fix des roten Schritts beweist sich vor dem Merge mit `run.sh all --step desktop_e2e_monitoring` auf einer Pool-VM
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1456: findingItem überspringt Funde ohne Instanz  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-server-page.live.js, tasks/kern-desktop-e2e-1.md
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @55e97cd4a 2026-11-14T18:38:58+01:00
Review: am Ende (Branch-Review)
Änderung: `findingItem` fragt `.inbox-instance` je `.inbox-item` ab und wirft beim ersten Eintrag ohne Instanz. Seit
dem Katalogmodul `mdadm` (003e440cb, #519) steht auf der Testbox der Fund „Software RAID (md)“ vor den Port-Funden; er
heißt nach dem Modul, die Inbox zeigt darum keine Instanz (`FindingsInbox.svelte:82`). Die Suche liest die Instanzen
in einem `browser.execute` (wie `domTexts`) und nimmt den Eintrag mit dem passenden Index; Einträge ohne Instanz
zählen nicht.
Beweis: main@0e8c605a3 `run.sh all --step desktop_e2e_monitoring` auf einer Pool-VM, `.ah-out/step-mon-0714/log:2712-2720`
(„The element with selector ".inbox-instance" … wasn't found“ in findingItem, Spec-Zeile 146); im Seiten-Dump Z. 2708
steht `data-kind="new"> New Software RAID (md)` ohne `inbox-instance` vor `Listening port tcp-…`.
Dedup-Key: bug:desktop:monitoring-server-page.live.js:findingItem
HEAD: 0e8c605a3
Semantik: docs/en/admin/monitoring.html:402 — „or by the systemd unit of its package (the instance is then named after
the module …)“; ein Fund ohne eigene Instanz ist gewollt, die Spec muss ihn aushalten.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (nur ein E2E-Spec)

## Entscheidungen
