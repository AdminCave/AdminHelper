<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-3 — Spec

Roadmap: R-0960, R-0959, R-0958, R-0990, R-0991, R-0957, R-0976 (Zug `tasks/kern-server-3.md`). R-0979 ist abgelehnt (Kevin
2026-10-30: der Handler existiert auf main nicht).

## Problem / Motivation
Nachzügler aus den Prüfungen von kern-server-1, kern-server-2 und api-contracts:
- **R-0960:** Ein Fehlerpfad der Namensauflösung (`_NameResolver`, `app/core/middleware.py`) hält sich nicht an das
  im Docstring zugesagte fail-closed-Verhalten (Details privat).
- **R-0958:** Ein Kommentar in `bootstrap` (`auth_router.py`) beschreibt die Antwort für einen schon eingerichteten
  Server falsch. Der Code antwortet mit dem dokumentierten `409`.
- **R-0990:** Ein Refresh, der unter `MTLS_ENFORCE` ohne Zertifikat abgewiesen wird, erscheint nicht im Audit-Log. Ein
  so abgewiesener Login erscheint dort als `auth.login_failed`.
- **R-0991:** Kleinigkeiten aus kern-server-2:
  - (a) Ein riesiger `WEB_SESSION_MAX_HOURS` lässt `timedelta` überlaufen: Der Browser-Login antwortet mit `500`.
  - (b) Der `403`-Text der Sign-in-Prüfung nennt einen „Scope“, den sie gar nicht prüft.
  - (c) Die API-Referenz sagt, beim Bootstrap komme `403` vor allen anderen Prüfungen. Das Rate-Limit (`429`) kommt
    aber davor.
  - (d) `web_session_start` prüft `exp` ein zweites Mal. Läuft der Token im Millisekunden-Fenster dazwischen ab,
    antwortet der Server mit `500` statt `401`.
  - (e) Kein Test belegt `web`/`auth_time` beim Browser-Bootstrap.
- **R-0957:** Mit einem `ADMIN_PASSWORD` über 128 Zeichen legt der Server-Start einen Admin an, der sich nie anmelden
  kann. Das Schema begrenzt das Passwort auf `PASSWORD_MAX_LEN` (128); `main.py` prüft nur die Mindestlänge.
- **R-0976:** `Connection.to_dict` gibt `tags` aus Altzeilen roh aus, wenn sie keine JSON-Liste sind. Ist der Wert gar
  kein JSON, scheitert die ganze Liste.

- **R-0959:** Die Gateway-Namen werden so selten neu aufgelöst wie die Proxy-Namen (Details privat). Kevin
  2026-10-30: eine kürzere TTL (5 s) nur für die Gateway-Namen.

## Ziel & Nicht-Ziele
Ziel: Jede Zeile ist behoben und durch einen Test belegt.

Nicht-Ziele:
- kein neuer API-Vertrag: `409` beim eingerichteten Server bleibt;
- keine Migration der Altzeilen (gelesen wird defensiv);
- keine Obergrenze in der Konfiguration (R-0991a wird an der Rechenstelle behoben, `0` = aus bleibt).

## Betroffene Komponenten & Dateien
Nur der Server und die API-Referenz (DE und EN):
- `apps/server/app/core/middleware.py`
- `apps/server/app/core/identity.py`
- `apps/server/app/core/auth.py`
- `apps/server/app/modules/users/auth_router.py`
- `apps/server/app/main.py`
- `apps/server/app/modules/connections/models.py`
- die Tests dazu
- `docs/developer/api-reference.html` und `docs/en/developer/api-reference.html`
- `changelog.d/kern-server-3.md`

## Datenmodell / API / Migrationen
Keine Migration, keine Schema- oder OpenAPI-Änderung. Sichtbar ändern sich:
- der `detail`-Text des `403` an Login, Refresh und Bootstrap ohne Zertifikat (die Scope-Prüfung behält ihren Text);
- eine neue Audit-Aktion `auth.refresh_failed`.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- **R-0991a:** Eine Obergrenze in `parse_web_session_max_hours` würde die Bedeutung der Konfiguration ändern. Der
  Vergleich in Sekunden vor dem Bau des `timedelta` behebt den Überlauf ohne neue Regel. Empfehlung: der Vergleich.
- **R-0991d:** Ohne zweite `exp`-Prüfung gilt: Der Token ist unmittelbar vorher vollständig geprüft
  (`get_user_from_refresh_token`). Ein Abfangen des Fehlers würde aus einer Web- eine Desktop-Sitzung machen.
  Empfehlung: `verify_exp` aus.

## Risiken & Rollback
Gering. Jede Task ist ein eigener Commit und einzeln per Revert rücknehmbar. R-0960 macht den Resolver im Fehlerfall so
streng, wie sein Docstring es schon zusagt.

## Doku-Impact
- API-Referenz DE und EN: Reihenfolge `429` vor `403` beim Bootstrap, Audit beim abgewiesenen Refresh.
- CHANGELOG-Fragment.
- Sonst keine.

## Offene Fragen
Keine (R-0959 und R-0979 hat Kevin am 2026-10-30 entschieden).
