<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-4 — Ablaufübersicht der Zertifikate (R-1022)

## Problem / Motivation
Wann ein Zertifikat abläuft, sieht ein Admin heute nur im Log des `ca-issuer` (Warnung ab 180 Tagen vor dem Ablauf
von Root und Zwischenzertifikaten, `apps/ca-issuer/app/storage.py:328` `_warn_if_ending`) oder mit
`python -m app.cli status` im Container. Gateway- und frps-Zertifikat (365 Tage, beim Start bei Bedarf neu
ausgestellt) und die Agent-Zertifikate (90 Tage, Erneuerung bei halber Laufzeit,
`apps/agent/internal/enroll/renew.go:19`) zeigt keine Oberfläche. Scheitert die Erneuerung eines Agenten still, fällt
das erst auf, wenn sein Zertifikat abgelaufen ist.

## Ziel & Nicht-Ziele
Ziel (Kevin 2026-10-30):
- **Umfang:** Infrastruktur (Root, die Zwischenzertifikate `tunnel`, `access`, `internal`, Gateway- und
  frps-Zertifikat) und die Agent-Zertifikate.
- **Anzeige:** eine Web-Seite „Zertifikate“ (nur Admins) mit Restlaufzeit und Ampel, dazu ein Alarm.
- **Schwelle:** gelb unter 30 Tagen, rot unter 7 Tagen (auch abgelaufen).
- **Datenpfad:** eine neue DB-Tabelle, die der `ca-issuer` schreibt und der Server liest.
- **Alarmweg:** Server-Benachrichtigung (Glocke und, je nach Abo, E-Mail) an die Admins.

Nicht-Ziele: Desktop- und Browser-Zertifikate der Benutzer (stehen schon unter Benutzer → Geräte), ein Check im
Monitoring-Dienst (die Roadmap-Zeile nannte ihn, Kevin wählte die Server-Benachrichtigung), die Rotation aus der
Oberfläche anstoßen, abgelöste Zwischenzertifikate (`<scope>-retired.pem`) anzeigen.

## Betroffene Komponenten & Dateien
- **Server, Schema:** neue Migration unter `apps/server/alembic/versions/` (Kopf heute `a7c9e1b3d5f2`), Tabelle
  `infra_certificates`; Model in `apps/server/app/modules/enrollment/models.py`; Rechte des `ca-issuer` in
  `apps/server/app/db_roles.py` (`CA_TABLE_PRIVILEGES`, Zeile 40).
- **ca-issuer:** Core-Table in `apps/ca-issuer/app/db.py` (neben `issued_certificates`, Zeile 91); eine neue Datei
  `apps/ca-issuer/app/inventory.py`, die die Infrastruktur-Zertifikate aus dem PKI-Verzeichnis und den
  Gateway-/frps-Pfaden liest und die Tabelle schreibt; Aufruf in `lifespan` (`apps/ca-issuer/app/main.py:89`) nach
  `provision_boot_material`.
- **Server, API:** `GET /api/enrollment/certificates` (nur Admins) in `apps/server/app/modules/enrollment/router.py`,
  Schema in `schemas.py`, Logik in einer neuen Datei `apps/server/app/modules/enrollment/expiry.py`; OpenAPI-Snapshot
  `apps/server/tests/openapi.snapshot.json`.
- **Server, Scheduler:** täglicher System-Job in `apps/server/app/modules/hooks/scheduler.py` (Muster
  `_register_system_job`, Zeile 297; Vorbild `apps/server/app/modules/frp/supervisor_watch.py`), Registrierung in
  `apps/server/app/scheduler_main.py:94`.
- **Web:** `apps/web/src/pages/Certificates.svelte`, `apps/web/src/lib/api/certificates.ts`, Typen in `types.ts` und
  der Vertragstest `types.contract.test.ts`, Route in `routes.ts`, Eintrag in
  `apps/web/src/lib/components/layout/Sidebar.svelte`, Texte in `apps/web/src/lib/i18n/dictionaries.ts`.

## Datenmodell / API / Migrationen
**Tabelle `infra_certificates`** (additiv, Rollback = `drop_table`):
`name` (String, PK: `root`, `intermediate:tunnel`, `intermediate:access`, `intermediate:internal`, `gateway`,
`frps`), `subject` (String), `fingerprint` (String(64), SHA-256 über DER, hex), `not_before`, `not_after` (naive
UTC wie `issued_certificates`), `recorded_at`. Der `ca-issuer` ersetzt beim Start alle Zeilen in einer Transaktion
(DELETE + INSERT): ein Zertifikat, das es nicht mehr gibt (etwa kein frps), verschwindet. Rechte: `ah_ca`
`SELECT, INSERT, DELETE`; der Server besitzt die Tabelle, der Scheduler bekommt seine üblichen Rechte über `setup`.

Neu geschrieben wird nur beim Start des `ca-issuer`: die Rotation verlangt ihn ohnehin (`apps/ca-issuer/app/cli.py`
`_RESTART`), und Gateway- und frps-Zertifikat stellt er nur beim Start neu aus. Ein Fehler beim Schreiben hält den
Start nicht auf (Warnung im Log): die Übersicht darf das Enrollment nicht kosten. Mit In-Memory-Store (nur
dev/tests) schreibt er nichts.

**API** `GET /api/enrollment/certificates` → `{ "infrastructure": [...], "agents": [...] }`, je Eintrag `name` bzw.
`server_id` und `server_name`, `subject`, `fingerprint`, `not_after`, `days_left` (ganze Tage, negativ wenn
abgelaufen), `status` (`ok` | `warning` | `critical`). Agenten: je nicht widerrufener `device_lines`-Zeile mit
`kind = "agent"` das Zertifikat mit dem spätesten `not_after`, `subject_id` ist die Server-ID. Vertrags-Drift: Web
(neu), Desktop und Agent unberührt.

**Alarm:** täglich, an die Admins (`notify_users`), je Zertifikat und Stufe einmal: `source_type =
"certificate_expiry"`, `source_id = "<fingerprint>:<stufe>"`. Ein erneuertes Zertifikat hat einen neuen Fingerprint
und meldet sich erst wieder, wenn auch es in die Schwelle läuft. Löscht die Aufbewahrung der Benachrichtigungen eine
Meldung, kommt sie einmal neu, solange das Zertifikat in der Stufe bleibt.

## Externe Integrationen
Keine neuen. X.509 nur über `cryptography` wie im `ca-issuer` (`pki.cert_from_pem`).

## Trade-offs & Alternativen
- Server liest die PEM-Dateien selbst: geht nicht, der Server ist nicht im Netz `pki` und hat das Volume `ca-pki`
  nicht (Absicht: nur der `ca-issuer` liest die PKI). Ein Endpunkt am `ca-issuer`: verworfen, Kevin wählte die
  Tabelle.
- Monitoring-Check: verworfen (Kevin), braucht Zugriff auf Server-Daten im Monitoring-Dienst.
- Je Agent eine Meldung statt einer Sammelmeldung: einfacher und am Fingerprint dedupliziert; viele gleichzeitig
  auslaufende Agenten werden auf eine Höchstzahl je Lauf begrenzt (wie `supervisor_watch.LIMIT`), der Rest folgt am
  nächsten Tag.

## Risiken & Rollback
- Migration additiv; Rollback per Downgrade. Die Grant-Liste läuft bei jedem Server-Start (`grant-ca`).
- Ein falsch gelesenes Zertifikat zeigt eine falsche Ampel, ändert aber nichts an der PKI: der Schreibweg ist nur
  lesend gegenüber den PEM-Dateien.
- Meldungsflut: Dedup über `source_id`, Höchstzahl je Lauf.

## Doku-Impact
`docs/admin/betrieb.html` + `docs/en/admin/operations.html` („Zertifikate erneuern“: Seite und Alarm),
`docs/developer/webui.html` + EN (neue Seite), `docs/developer/api-reference.html` + EN (neuer Endpunkt),
`changelog.d/kern-ca-4.md`. Die Betriebsseiten ändert auch #348 (kern-ca-2): die Doku-Task baut nach dessen Merge.

## Offene Fragen
Keine; Kevins Antworten vom 2026-10-30 decken Umfang, Anzeige, Schwelle, Datenpfad und Alarmweg.
