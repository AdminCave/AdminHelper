# kern-pycommon-2 — ah_common: die letzten doppelten Helfer

Roadmap: R-1740.

## Problem / Motivation

kern-pycommon-1 hat den gemeinsamen Python-Code von Server und Monitoring nach `apps/pycommon/ah_common` gelegt. Zehn
Funktionen liegen noch doppelt vor. Der Wächter `apps/server/tests/test_no_python_copies.py` führt sie in `_KNOWN`
als Ausnahme:
- NUL-Prüfung: `_nul_rejected` und `NulByteMiddleware.dispatch` in `apps/server/app/core/middleware.py:283` und
  `apps/monitoring/app/core/middleware.py:17`.
- `apps/{server,monitoring}/app/core/query_params.py`: `_is_array`, `_scalar_query_params` und
  `reject_repeated_scalar_query`. Die Dateien unterscheiden sich nur im Docstring.
- Mail-Vorlage: `format_time`, `unknown`, `_fill`, `_html_values` und `compose` in
  `apps/server/app/modules/notifications/mail_template.py` und `apps/monitoring/app/mail_template.py`. Gleich halten
  sie heute zwei Kopien der Paritäts-Fixture `mail_template_parity.json`.

## Ziel & Nicht-Ziele

Ziel: Jeder dieser Helfer existiert genau einmal in `ah_common`, und `_KNOWN` im Wächter ist leer.

Nicht-Ziele:
- Keine Verhaltensänderung: gleiche 422-Antworten, gleiche Mails.
- Das Panel-Laden der Vorlage (`load`, `applied`, `using`, `current`) bleibt im Server-Modul, weil es die Server-DB
  liest.
- `IPFilterMiddleware` (Server) und `ReportBodyLimitMiddleware` (Monitoring) bleiben in ihren Diensten.

## Betroffene Komponenten & Dateien

- Neu `apps/pycommon/ah_common/middleware.py` (`NulByteMiddleware`), `query_params.py`, `mail_template.py`
  (Renderer: `Template`, `Mail`, `DEFAULT`, `PLACEHOLDERS`, `LOGO_CID`, `format_time`, `unknown`, `compose`).
- Server: `app/core/middleware.py`, `app/core/query_params.py` (entfällt), `app/main.py`,
  `app/modules/notifications/mail_template.py` (behält das Panel-Laden, re-exportiert den Renderer für seine Importeure).
- Monitoring: `app/core/middleware.py`, `app/core/query_params.py` (entfällt), `app/main.py`, `app/mail_template.py`
  (entfällt), `app/notify_config.py`, `app/alerter.py`.
- Tests: `apps/server/tests/test_no_python_copies.py` (Ausnahmen raus),
  `apps/monitoring/tests/test_mail_template_parity.py` und `apps/monitoring/tests/fixtures/mail_template_parity.json`
  (entfallen, s. Trade-offs), `apps/monitoring/tests/test_notify_config.py` (Import).

## Datenmodell / API / Migrationen

Keine. Die OpenAPI-Schemata bleiben unverändert, die 422-Form der NUL-Prüfung auch.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- **Direkte Imports statt Fassaden:** `query_params` und die NUL-Middleware haben nur je einen Importeur (`main.py`),
  deshalb entfallen die Dienst-Module bzw. -Teile. Die Server-`mail_template` hat sechs Importeure und eigene
  Funktionen. Sie bleibt das Modul, über das der Server die Vorlage anspricht, und re-exportiert den Renderer.
- **Monitoring-Paritätstest entfällt:** Bei einer Implementierung prüft er denselben Code ein zweites Mal. Die
  Fixture-Fälle und der `format_time`-Test bleiben im Server (`test_notify_mail_template.py`). Vorbild ist T2 aus
  kern-pycommon-1 (`test_ssrf_parity.py`).

## Risiken & Rollback

- `apps/server/app/modules/notifications/*` und `apps/monitoring/app/alerter.py` sind Risikopfade. `security` prüft
  die Mail-Task.
- Die Images kopieren `ah_common` seit kern-pycommon-1, der Lieferweg bleibt gleich. Beweis ist der Sammellauf
  (`Heavy: linux-full`).
- Rollback: `git revert` je Task.

## Doku-Impact

`docs/developer/index.html`, `docs/developer/monitoring.html` und `docs/developer/server.html` (DE+EN): die Liste des
gemeinsamen Codes um NUL-Prüfung, Query-Prüfung und Mail-Renderer ergänzen; der Satz über die zwei Kopien des
Renderers entfällt. Dazu `changelog.d/kern-pycommon-2.md`.

## Offene Fragen

Keine.
