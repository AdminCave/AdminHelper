<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-smtp-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-ref-smtp-1 · Review: am Ende
Spec: docs/features/klein-ref-smtp-1.md (Roadmap R-0831)
Heavy: none — Unit-Tests in Server und Monitoring, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — test_alert_secrets: entfernter Port und leerer Host (R-0831)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_alert_secrets.py
Änderung: `test_alert_put_with_the_mask_for_another_relay_is_refused` bekommt die Parameter `port-removed` (`smtp_port: None`) und `host-blank` (`smtp_host: "  "`); beide sind ein anderes Relay als das gespeicherte und werden mit 422 abgelehnt. Gegenprobe: `_smtp_relay` ohne Port bzw. ohne Host im Vergleich macht den jeweiligen Fall rot (danach zurückgenommen).
Beweis: R-0831 Code-Lesung apps/monitoring/tests/test_alert_secrets.py:321
Dedup-Key: ref:tests:smtp-hardening:nits
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alert_secrets.py
Doku: keine (Test)

### T2 — test_email_sender: ohne CA-Datei auch auf 465, Kontext aus create_default_context (R-0831)  [ ]
Komponente: server · Dateien: apps/server/tests/test_email_sender.py
Änderung: `test_without_smtp_ca_file_the_context_has_no_extra_ca` läuft auf 587 und 465. Ein Spion um `ssl.create_default_context` hält fest, dass der an `starttls()`/`SMTP_SSL` gereichte Kontext genau der von `create_default_context` ist (nicht allein aus der CA-Datei gebaut), unabhängig davon, ob das System-Bundle eager geladen wird. Gegenprobe: `ssl.SSLContext(PROTOCOL_TLS_CLIENT)` statt `create_default_context()` in `sender.py` macht den Test rot (danach zurückgenommen).
Beweis: R-0831 Code-Lesung apps/server/tests/test_email_sender.py:194
Dedup-Key: ref:tests:smtp-hardening:nits
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_email_sender.py
Doku: keine (Test)

## Entscheidungen
- R-0830 fährt nicht mit: neuer Meldungstext ist sichtbares Verhalten (Kevins Bereich); Frage im Abschlussbericht.
