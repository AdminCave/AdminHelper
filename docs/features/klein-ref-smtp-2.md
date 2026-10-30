<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-smtp-2 — SMTP_CA_FILE-Fehlertext und Fingerprint-Hinweis beim Erstkontakt

Roadmap R-0830 (Kevin 2026-10-30: Pfad und Variable in Log und Hub-Fehlermeldung nennen, nicht in die
Alert-Nachricht) und R-0992 (von Kevin 2026-10-30 angenommen). `overlap.sh` auf die vier Quelldateien ohne Treffer.

## Problem / Motivation
- **R-0830:** Ist `SMTP_CA_FILE` gesetzt, aber die Datei fehlt oder ist kein PEM, scheitert
  `ctx.load_verify_locations` vor dem Verbindungsaufbau. Der Hub (`apps/server/app/modules/notifications/sender.py`)
  reicht die rohe Ausnahme weiter; `outbox.py` speichert `str(exc)` als `last_error`. Bei „not-pem“ steht dort nur
  `[X509] no certificate or crl found`, weder Variable noch Pfad. Das Monitoring
  (`apps/monitoring/app/alerter.py`, `_send_email`) loggt `Email failed: <check>: <exc>` mit derselben rohen Ausnahme.
  Wer den Fehler im Log oder in der Outbox sieht, erfährt nicht, welche Einstellung falsch ist.
- **R-0992:** `pinIfBlindInsecure` (`apps/agent/internal/provision/provision.go`) druckt beim `--insecure`-Erstkontakt
  den SHA-256 des vorgelegten Server-Zertifikats und sagt „gegen den im AdminHelper-Server angezeigten Fingerprint
  pruefen“. Weder Server noch Web noch Desktop zeigen diesen Wert; der Desktop zeigt im Provisionierungs-Tab nur den
  CA-Fingerprint (`pinnedCaFingerprint`, Wurzel der CA), der nie dem Leaf-Wert entspricht, und der Vertrauens-Dialog
  im Login nennt keinen Fingerprint. Der Hinweis verweist ins Leere, obwohl er den Erstkontakt gegen einen aktiven
  MITM absichern soll.

## Ziel & Nicht-Ziele
- Hub: eine unlesbare `SMTP_CA_FILE` führt zu einer Ausnahme, deren Text `SMTP_CA_FILE`, den Pfad und die Art des
  Fehlers nennt. Monitoring: die Logzeile nennt dasselbe, die gespeicherte Alert-Meldung bleibt `SMTP TLS failed`.
- Agent: der Hinweis nennt, womit zu vergleichen ist (`openssl x509 -noout -fingerprint -sha256` am Server- oder
  Gateway-Zertifikat), und verweist auf `--ca-fp` als verifizierten Erstkontakt.
- Nicht-Ziel: ein Fingerprint im Server, Web oder Desktop (neues Verhalten); Änderung der Pin-Logik; Änderung der
  Alert-Nachricht.

## Betroffene Komponenten & Dateien
`apps/server/app/modules/notifications/sender.py` (+ `tests/test_email_sender.py`), `apps/monitoring/app/alerter.py`
(+ `tests/test_alerter_dispatch.py`), `apps/agent/internal/provision/provision.go` (+ `provision_test.go`),
`changelog.d/klein-ref-smtp-2.md`.

## Datenmodell / API / Migrationen
Keine. Der Hub-Test erwartet danach `RuntimeError` statt `FileNotFoundError`/`ssl.SSLError`; der Outbox-Pfad fängt
`Exception`, die Wiederholung bleibt gleich.

## Trade-offs
- Hub: eine neue Ausnahme mit Kontext (`raise RuntimeError(...) from exc`) statt `exc.add_note`, weil `str(exc)`
  die Notiz nicht trägt und `last_error` genau `str(exc)` ist. Der Ausnahmetext des Betriebssystems bleibt über
  `__cause__` im Log.
- Monitoring: nur die Logzeile wird angereichert (eine Zeile bleibt eine Zeile, der bestehende Test zählt sie); die
  Alert-Meldung ändert sich nicht.
- Agent: die Hinweiszeilen werden englisch geschrieben (neue Strings), die Nachbarzeilen bleiben unberührt.

## Risiken & Rollback
Gering; `git revert`. `last_error` der Outbox nennt künftig den Pfad der CA-Datei; er steht dort nur für Admins und
ist ohnehin Teil der rohen Ausnahme bei fehlender Datei.
`apps/agent/internal/provision/*` ist Risikopfad: die Abschlussprüfung bekommt `security`.

## Doku-Impact
`changelog.d/klein-ref-smtp-2.md`; die Admin-Seiten beschreiben weder den SMTP-Fehlertext noch die Hinweiszeilen.

## Offene Fragen
Keine.
