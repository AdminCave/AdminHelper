# Audit für das Nachziehen der verknüpften Verbindung — Task-Ledger
Status: bereit · Branch: feature/kern-frp-9 · Review: am Ende
Spec: docs/features/kern-frp-9.md (Roadmap R-1617)
Heavy: linux-full — Server-Route `/api/frp/tunnels` (Audit-Nebenwirkung); kein Cross-Host-, PKI-, FRP-Konfigurations- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Tunnel-Update auditiert die nachgezogene Verbindung (R-1617)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_frp_auto_connection.py, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-frp-9.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b4c3c73fc 2026-11-19T18:32:49+01:00
Review: am Ende (Branch-Review)
Änderung: `update_tunnel` merkt sich, ob `follow_tunnel` lief, und schreibt nach dem Commit zusätzlich `audit.record(db, "connection.updated", object_type="connection", object_id=<id>, object_label=<name>, detail=<auslösender Tunnel>, actor=<Anfrage>)`. Test: Protokollwechsel mit verknüpfter Verbindung erzeugt den Eintrag (Actor, Objekt, detail); ein Update ohne Formwechsel erzeugt keinen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_auto_connection.py
Doku: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-frp-9.md

### T2 — Audit-Eintrag trägt den Anzeigenamen der Verbindung (Fund Abschlussprüfung)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_frp_auto_connection.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @043283dde 2026-11-19T18:48:53+01:00
Review: am Ende (Branch-Review)
Änderung: `object_label` des `connection.updated`-Eintrags ist `display_name()` nach dem Nachziehen statt der rohen Spalte `name` (Auto-Verbindungen speichern `""`); der Test prüft gegen den Anzeigenamen.
Beweis: reviewer branch kern-frp-9 2026-11-19 @502f23d77
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_auto_connection.py
Doku: keine (Doku nennt das Label nicht)
