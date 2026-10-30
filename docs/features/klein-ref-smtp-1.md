<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-smtp-1 — SMTP-Tests: fehlende Fälle

Roadmap R-0831. Nur Testcode, kein Produktivcode. `overlap.sh` ohne Treffer. R-0830 (Meldungstext bei fehlender
`SMTP_CA_FILE`) fährt nicht mit: sie ändert sichtbaren Text und wartet auf Kevins Entscheidung.

## Problem / Motivation
Der Branch-Review von smtp-hardening ließ drei Test-Lücken offen:
- `apps/monitoring/tests/test_alert_secrets.py` (`test_alert_put_with_the_mask_for_another_relay_is_refused`):
  `_smtp_relay` (`apps/monitoring/app/models.py`) vergleicht Host und Port, die Parameter decken aber nur geänderten
  Host, geänderten Port und entfernten Host ab. Es fehlen der entfernte Port und ein leerer Host.
- `apps/server/tests/test_email_sender.py` (`test_without_smtp_ca_file_the_context_has_no_extra_ca`) prüft den Fall
  ohne CA-Datei nur auf Port 587, der Zweig für 465 (`SMTP_SSL`) bleibt ungeprüft.
- Die CA-Assertions (`x509_ca == system_cas + 1`) erkennen eine Mutante, die den Kontext allein aus der Datei baut,
  nur wenn das System-CA-Bundle eager geladen wird; auf einer Box mit Hash-Verzeichnis zählt es 0 + 1 auf beiden Seiten.

## Ziel & Nicht-Ziele
Die drei Lücken schließen, mit Gegenprobe je Fall. Nicht-Ziel: Produktivcode oder Meldungstexte ändern.

## Betroffene Komponenten & Dateien
`apps/monitoring/tests/test_alert_secrets.py`, `apps/server/tests/test_email_sender.py`.

## Risiken & Rollback
Test-only; Revert genügt.

## Doku-Impact
Keine (interne Tests).

## Offene Fragen
Keine für R-0831. R-0830 (neuer Meldungstext, Monitoring liefert bisher bewusst fest „SMTP TLS failed“) ist Kevins
Entscheidung.
