<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-smtp-1 — Task-Ledger
Status: bereit · Branch: feature/klein-ref-smtp-1 · Review: am Ende
Spec: docs/features/klein-ref-smtp-1.md (Roadmap R-0831)
Heavy: none — Unit-Tests in Server und Monitoring, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — test_alert_secrets: entfernter Port und leerer Host (R-0831)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_alert_secrets.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f1c8cdac 2026-10-30T00:45:29+01:00
Review: am Ende (Branch-Review)
Änderung: `test_alert_put_with_the_mask_for_another_relay_is_refused` bekommt die Parameter `port-removed` (`smtp_port: None`) und `host-blank` (`smtp_host: "  "`); beide sind ein anderes Relay als das gespeicherte und werden mit 422 abgelehnt. Gegenprobe: `_smtp_relay` ohne Port bzw. ohne Host im Vergleich macht den jeweiligen Fall rot (danach zurückgenommen).
Beweis: R-0831 Code-Lesung apps/monitoring/tests/test_alert_secrets.py:321
Dedup-Key: ref:tests:smtp-hardening:nits
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alert_secrets.py
Doku: keine (Test)

### T2 — test_email_sender: ohne CA-Datei auch auf 465, Kontext aus create_default_context (R-0831)  [x]
Komponente: server · Dateien: apps/server/tests/test_email_sender.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e2c26c8f 2026-10-30T00:46:16+01:00
Review: am Ende (Branch-Review)
Änderung: `test_without_smtp_ca_file_the_context_has_no_extra_ca` läuft auf 587 und 465. Ein Spion um `ssl.create_default_context` hält fest, dass der an `starttls()`/`SMTP_SSL` gereichte Kontext genau der von `create_default_context` ist (nicht allein aus der CA-Datei gebaut), unabhängig davon, ob das System-Bundle eager geladen wird. Gegenprobe: `ssl.SSLContext(PROTOCOL_TLS_CLIENT)` statt `create_default_context()` in `sender.py` macht den Test rot (danach zurückgenommen).
Beweis: R-0831 Code-Lesung apps/server/tests/test_email_sender.py:194
Dedup-Key: ref:tests:smtp-hardening:nits
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_email_sender.py
Doku: keine (Test)

### T3 — test_email_sender: Spion auch im Test mit CA-Datei (R-0831, Abschlussprüfung Runde 1)  [x]
Komponente: server · Dateien: apps/server/tests/test_email_sender.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @58db9539 2026-10-30T00:52:38+01:00
Review: am Ende (Branch-Review)
Änderung: Der Spion um `ssl.create_default_context` mit `assert created == [ctx]` steht zusätzlich in `test_smtp_ca_file_adds_the_relay_ca_to_the_verifying_context` (dort läuft der Datei-Zweig; eine Datei-only-Mutante bestand die Zählung auf einer Box mit lazy CA-Verzeichnis). Gemeinsamer Helfer für den Spion; der Kommentar im Test ohne CA-Datei verweist auf den Test darüber statt auf „CA counts above“. Gegenprobe: `ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` nur bei gesetzter CA-Datei vor `load_verify_locations` macht den Test rot (danach zurückgenommen).
Beweis: Abschlussprüfung klein-ref-smtp-1, Urteil Runde 1
Dedup-Key: ref:tests:smtp-hardening:nits
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_email_sender.py
Doku: keine (Test)

## Entscheidungen
- R-0830 fährt nicht mit: neuer Meldungstext ist sichtbares Verhalten (Kevins Bereich); Frage im Abschlussbericht.
