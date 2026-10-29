<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Nacharbeiten an HTTP-Check, Alert-Regeln und Template-Variablen

Zug `kern-monitoring-1` (Roadmap R-0921, R-0826, R-0828, R-0917). Stand des Codes: `origin/main@33295e76`. Pfade
ohne Präfix liegen unter `apps/monitoring/app/`.

## Problem / Motivation

1. **Content-Encoding-Schichten (R-0921).** `_decoded` (`checkers/http.py:167`) legt je `gzip`/`deflate` im
   Header `Content-Encoding` eine Schicht an, ohne Obergrenze. urllib3 2.x begrenzt auf fünf Schichten.
   Einzelheiten privat.
2. **Redirect ohne `Location` (R-0826, BUG).** Ein 3xx ohne `Location` meldet nach der ersten Anfrage
   „Too many redirects (>5)“ (`checkers/http.py:93-94`); der Test
   `test_http_checker_ends_at_a_redirect_without_location` lässt die Meldung bewusst offen.
3. **Maske beim Anlegen (R-0828, BUG).** `POST /alerts` (`routers/alerts.py:42`) speichert ein gesendetes
   `smtp_password` `"***"` wörtlich: die Maske, die `GET` zurückgibt (`models.py:63`). `PUT` behält in dem Fall das
   alte Passwort (`keep_smtp_password`, `models.py:77`); beim Anlegen gibt es keins.
4. **Steuerzeichen über Template-Variablen (R-0917, BUG).** `_build_variables` (`template_sync.py:80`) setzt
   `hostname` und `server_name` der Zuweisung ungeprüft in Check-Namen, Konfiguration und Alert-Definitionen ein;
   so erreichen Steuerzeichen `MonitorCheck.name` am Validator `_no_control_characters` (`schemas.py:24`) vorbei.
   Die Werte kommen aus `POST /templates/{id}/assign` (`TemplateAssign`, `schemas.py:190`) und aus dem
   Inventar-Abgleich (`tag_sync.py:152`).

## Ziel & Nicht-Ziele

Ziel: je Zeile das beschriebene Verhalten, mit Test. Nicht-Ziele: Änderungen am Server, an der Web-Oberfläche oder
an anderen Check-Typen; eine Migration bestehender Check-Namen.

## Betroffene Komponenten & Dateien

`monitoring`: `checkers/http.py`, `routers/alerts.py`, `template_sync.py` und ihre Tests
(`apps/monitoring/tests/test_http_checker.py`, `test_alert_secrets.py`, `test_template_sync.py`).

## Datenmodell / API / Migrationen

Keine Migration. API: `POST /alerts` (intern, nur der Server ruft es) antwortet auf `smtp_password: "***"` mit 422,
wie die Zeile R-0828 es vorgibt. Die Meldung eines HTTP-Checks ändert sich in zwei Fällen (Redirect ohne
`Location`; zu viele Content-Encoding-Schichten).

## Externe Integrationen

httpx 0.28.1 (`httpx/_decoders.py`, `MultiDecoder`) begrenzt die Schichten nicht; urllib3 2.x
(`response.py`, `MultiDecoder._max_decode_links = 5`) weist mehr als fünf ab. Kein neuer Aufruf.

## Trade-offs & Alternativen

- R-0921: höchstens fünf Schichten wie urllib3; mehr → `httpx.DecodingError`, der Check meldet `unknown` wie bei
  einem kaputten gzip-Körper heute. Alternative: Schichten über fünf ignorieren — verworfen, der Körper wäre falsch
  dekodiert.
- R-0826: eigene Meldung „Redirect without Location header“, `critical`.
- R-0828: 422 beim Anlegen (Abhilfe der Zeile). Alternative: Feld still verwerfen — verworfen, der Aufrufer merkte
  nicht, dass kein Passwort gespeichert ist.
- R-0917: `_build_variables` ersetzt C0-Steuerzeichen und DEL in `hostname` und `server_name` durch Leerzeichen. Eine
  Stelle deckt beide Quellen (Zuweisung, Inventar-Abgleich) und alle Einsetzungen ab. Alternative: Validator an
  `TemplateAssign` — verworfen, er deckt den Inventar-Abgleich nicht ab und ließe eine Zuweisung scheitern, statt den
  Namen zu bereinigen.

## Risiken & Rollback

Jede Task ein Commit, einzeln zurücknehmbar. T1 berührt den HTTP-Check, `security` dazu. Ein bestehender Check-Name
mit Steuerzeichen wird erst beim nächsten Abgleich der Zuweisung bereinigt.

## Doku-Impact

`changelog.d/kern-monitoring-1.md`. `docs/developer/monitoring.html:180` + EN (HTTP-Check) nennt die Grenze der
Schichten neben der Redirect-Grenze. Die Alert-Kanäle in `docs/admin/monitoring.html` beschreiben die Maske nicht;
keine weitere Seite.

## Offene Fragen

Keine.
