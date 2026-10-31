<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-4 — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-4 · Review: pro Task
Spec: docs/features/kern-ca-4.md (Roadmap R-1022)
Heavy: linux-full — `apps/ca-issuer` (Start mit DB-Store) und Server-API (Sammellauf: Stack mit Enrollment)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — Tabelle infra_certificates: Migration, Model, Rechte des ca-issuer (R-1022)  [x]
Komponente: server · Dateien: apps/server/alembic/versions/b4d6f8a0c2e1_add_infra_certificates.py, apps/server/app/modules/enrollment/models.py, apps/server/app/db_roles.py, apps/server/tests/test_db_roles.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c3904d31 2026-10-31T05:14:44+01:00
Review: approve (.ah-out/review/kern-ca-4/T1.verdict.json)
Änderung: Additive Migration (down_revision `a7c9e1b3d5f2`) für `infra_certificates` (Spalten laut Spec), Model `InfraCertificate`, `CA_TABLE_PRIVILEGES["infra_certificates"] = "SELECT, INSERT, DELETE"`. Test: Upgrade/Downgrade (`test_migrations_smoke.py` vergleicht Kette und Models) und die Rechte des ca-issuer an der Tabelle. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_db_roles.py tests/test_migrations_smoke.py
Doku: keine (internes Schema; die Übersicht dokumentiert T6)

### T2 — ca-issuer schreibt die Infrastruktur-Zertifikate beim Start (R-1022)  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/db.py, apps/ca-issuer/app/inventory.py, apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_inventory.py
Änderung: Core-Table `infra_certificates` in `db.py`; `inventory.py` liest Root, die Zwischenzertifikate je Scope, Gateway- und frps-Leaf (wo vorhanden) und ersetzt die Zeilen in einer Transaktion; `lifespan` ruft es nach `provision_boot_material` auf, nur mit DB-Store; ein Fehler wird geloggt und hält den Start nicht auf. Test gegen die Test-DB: Zeilen nach dem Lauf, fehlendes frps-Zertifikat ohne Zeile, DB-Fehler ohne Abbruch. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_inventory.py
Doku: → T6
Abhängt von: T1

### T3 — GET /api/enrollment/certificates: Infrastruktur und Agenten mit Ampel (R-1022)  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/expiry.py, apps/server/app/modules/enrollment/router.py, apps/server/app/modules/enrollment/schemas.py, apps/server/tests/test_certificate_expiry.py, apps/server/tests/openapi.snapshot.json
Änderung: `expiry.py` berechnet je Eintrag `days_left` und `status` (`warning` unter 30, `critical` unter 7 Tagen) aus `infra_certificates` und dem jüngsten Zertifikat jeder nicht widerrufenen Agent-Linie (mit Servername); Route nur für Admins, Schema und Snapshot. Test: Ampel an den Grenzen 30/7/0, widerrufene Linie fehlt, Nicht-Admin 403. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_expiry.py tests/test_openapi_snapshot.py
Doku: → T6
Abhängt von: T1

### T4 — Täglicher Ablauf-Alarm über die Benachrichtigungen (R-1022)  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/expiry.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/scheduler_main.py, apps/server/tests/test_certificate_expiry_watch.py
Änderung: `notify_expiring(db)` meldet den Admins je Zertifikat und Stufe einmal (`source_type="certificate_expiry"`, `source_id="<fingerprint>:<stufe>"`, warning/critical), höchstens eine feste Zahl je Lauf; System-Job `system:certificate-expiry-watch` täglich, in `scheduler_main` registriert. Test: Meldung beim Eintritt in gelb und in rot, keine Wiederholung am nächsten Lauf, erneuertes Zertifikat ohne Meldung, Höchstzahl. Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_expiry_watch.py tests/test_certificate_expiry.py
Doku: → T6
Abhängt von: T3

### T5 — Web: Seite „Zertifikate“ (R-1022)  [ ]
Komponente: web · Dateien: apps/web/src/pages/Certificates.svelte, apps/web/src/pages/Certificates.test.ts, apps/web/src/lib/api/certificates.ts, apps/web/src/lib/api/types.ts, apps/web/src/lib/api/types.contract.test.ts, apps/web/src/routes.ts, apps/web/src/lib/components/layout/Sidebar.svelte, apps/web/src/lib/i18n/dictionaries.ts
Änderung: Admin-Seite mit zwei Tabellen (Infrastruktur, Agenten), Restlaufzeit und Ampel, Route `/certificates`, Eintrag in der Sidebar, Texte DE+EN; Typ und Abbildung im Vertragstest gegen den Snapshot aus T3. Acht Dateien: Seite, API-Client, Typ, Route und Navigation gehören zu einer Funktion. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Certificates.test.ts src/lib/api/types.contract.test.ts
Doku: → T6
Abhängt von: T3

### T6 — Doku DE+EN und CHANGELOG-Fragment (R-1022)  [ ]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/webui.html, docs/en/developer/webui.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-ca-4.md
Änderung: „Zertifikate erneuern“ um Seite und Alarm (Schwellen, Dedup, Schreiben beim Start), Web-UI-Seite und Endpunkt in der Entwickler-Doku, Fragment unter `### Added` umlautfrei. Baut nach dem Merge von #348 (dieselben Betriebsseiten).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T2, T4, T5

## Entscheidungen
- 2026-10-31: Endpunkt im Modul `enrollment` (`/api/enrollment/certificates`) statt eines neuen Moduls — die Daten (`device_lines`, `issued_certificates`) liegen dort.
- 2026-10-31: Geschrieben wird nur beim Start des ca-issuer; die Rotation verlangt den Neustart, Gateway/frps werden nur beim Start neu ausgestellt (Spec).
- 2026-10-31: T1 ohne eigene Testdatei: `test_migrations_smoke.py` prüft Migration gegen Model und den Downgrade der Kette, `test_db_roles.py` die Rechte.
