<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-smtp-2 — Task-Ledger
Status: aktiv · Branch: feature/klein-ref-smtp-2 · Review: am Ende
Spec: docs/features/klein-ref-smtp-2.md (Roadmap R-0830, R-0992)
Heavy: none — Fehlertexte und Unit-Tests, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Hub: unlesbare SMTP_CA_FILE nennt Variable und Pfad (R-0830)  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/sender.py, apps/server/tests/test_email_sender.py
Änderung: `send_email` fängt `OSError` und `ssl.SSLError` aus `load_verify_locations` und wirft `RuntimeError("SMTP_CA_FILE <pfad> cannot be loaded: <Ausnahmeklasse>") from exc`; es bleibt vor jeder Verbindung. `test_unloadable_smtp_ca_file_raises_before_connecting` erwartet `RuntimeError` und prüft Variable, Pfad und Klasse im Text (Ausnahmetyp ändert sich gewollt, die Prüfung „keine Verbindung“ bleibt).
Beweis: R-0830 Code-Lesung apps/server/app/modules/notifications/sender.py:40, outbox.py:77 (`last_error = str(exc)`)
Dedup-Key: ref:smtp:sender.py:ca-file-error-text
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_email_sender.py tests/test_outbox.py
Doku: → T3

### T2 — Monitoring: Logzeile nennt SMTP_CA_FILE und Pfad (R-0830)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/tests/test_alerter_dispatch.py
Änderung: scheitert das Laden der CA-Datei (`loading_ca`), nennt die eine Logzeile `Email failed: <check>: ...` zusätzlich `SMTP_CA_FILE` und den Pfad; die gespeicherte Meldung bleibt `SMTP TLS failed`. Der bestehende Test `test_unloadable_smtp_ca_file_stores_tls_failed_without_connecting` prüft die Zeile auf Variable und Pfad.
Beweis: R-0830 Code-Lesung apps/monitoring/app/alerter.py (`logger.error("Email failed: ...")` im `except`)
Dedup-Key: ref:smtp:alerter.py:ca-file-error-text
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter_dispatch.py
Doku: → T3

### T3 — Agent: Fingerprint-Hinweis beim --insecure-Erstkontakt, Changelog (R-0992, R-0830)  [ ]
Komponente: agent · Dateien: apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, changelog.d/klein-ref-smtp-2.md
Änderung: die Hinweiszeilen in `pinIfBlindInsecure` nennen den Vergleich (`openssl x509 -noout -fingerprint -sha256` am Server- oder Gateway-Zertifikat, Ziffern ohne Doppelpunkte und Groß-/Kleinschreibung) und `--ca-fp` als verifizierten Erstkontakt, ohne den nicht vorhandenen „im Server angezeigten Fingerprint“. Ein Test fängt die Ausgabe von `pinIfBlindInsecure` mit gültigem PEM ab und prüft den neuen Text und das Fehlen der alten Aussage. Das Fragment `changelog.d/klein-ref-smtp-2.md` (Fixed) nennt beide Änderungen (Hub/Monitoring und Agent).
Beweis: R-0992 Code-Lesung apps/agent/internal/provision/provision.go:277-279, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte (zeigt den CA-Fingerprint)
Dedup-Key: bug:agent:provision.go:insecure-fingerprint-hint
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/provision/...
Doku: changelog.d/klein-ref-smtp-2.md (T1 bis T3)
