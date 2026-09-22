<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Randvalidierung für Zahlen und Text — Task-Ledger
Status: aktiv · Branch: feature/input-boundary-validation · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/input-boundary-validation.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: path-gated — der Diff berührt `apps/server`-Routen; am Abschluss am realen Diff entscheiden (reine Eingangsprüfung ohne Datenfluss-Änderung ⇒ vermutlich nicht nötig, dann mit Begründung überspringen).
DoD je Task: CLAUDE.md (Tests grün, ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Entschieden am Gate (Kevin, 2026-09-22): Obergrenzen sind die **technischen** Grenzen der Spalte;
die tz-naiven Zeitstempel bleiben **draußen** (eigene Roadmap-Zeile); PR #29 ist gemergt, also
baubereit. Spec und Ledger sind der erste Commit dieses Branches, gesetzt am Gate — das Artefakt ist
also versioniert, bevor freigegeben wird, und eine Lane kann den Branch auschecken.

**Die Fundmenge kommt aus dem OpenAPI-Schema, nicht aus einem grep.** Worker2 hat am 2026-09-22
für PR #29 genau diese Suche gefahren — alle Integer-Parameter ohne `maximum`, also die Menge,
die ein Fuzzer bis `2**63` treiben kann: **neun** im Server, **drei** im Monitoring. Drei der
neun Server-Treffer standen bis dahin nur check-granular in der Ausschlussliste, `not_a_server_error`
lief dort also weiter. Diese Liste ist die Vorgabe für T2–T4; wer sie erweitert, nennt den Beleg.
**Bekannte Grenze der Suche:** sie deckt Query- und Pfadparameter ab, nicht Integer-Felder in
Request-Bodies — dafür ist T5 da, und dort ist bisher nur `mark_read` belegt. Eine Route wurde
ausdrücklich **nicht** gelistet, weil sie bei `2**63` mit 404 antwortet statt zu überlaufen; ein
Eintrag „vorsorglich" wäre eine Behauptung ohne Befund. Dieselbe Regel gilt hier.

Regel für dieses Vorhaben: **Jede Schranke wird aus dem Spaltentyp des Modells abgeleitet, nicht
geraten.** Wer eine Grenze setzt, ohne das Modell gelesen zu haben, macht gültige Ids ungültig.
Zweite Regel: Ein Test je Fundstelle prüft **beide** Ränder — der höchste erlaubte Wert wird
akzeptiert, der erste unerlaubte ergibt 422.

### T1 — Begrenzte Typen an einer Stelle  [x]
Komponente: server · Dateien: apps/server/app/core/bounds.py (neu, SPDX), apps/server/tests/test_bounds.py (neu, SPDX)
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @84db6e9e 2026-09-22T18:33:48+02:00
Review: approve (sonnet, 2 Runden)
Änderung: `Annotated[int, Field(...)]`-Typen für die drei Grenzen: `IntPk` (`ge=1, le=2147483647`), `BigIntPk` (`ge=1, le=9223372036854775807`), `Offset` (`ge=0, le=2147483647`). Jeder Typ mit einem Satz Kommentar, welche Spaltenart er abdeckt. Keine Verwendung in diesem Task, nur der Baustein plus Test, dass die Ränder halten.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bounds.py
Doku: keine (intern)

### T2 — Server: Paginierung begrenzen  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/app/modules/connections/router.py, apps/server/app/modules/audit/router.py
Änderung: die drei `Query(0, ge=0)` auf `Offset` aus T1 umstellen. Nur der Typ, keine Logik.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T3 — Server: Paginierung begrenzen, zweiter Teil  [ ]
Komponente: server · Dateien: apps/server/app/modules/servers/router.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_pagination.py
Änderung: dieselbe Umstellung für die restlichen zwei Router; im bestehenden `test_pagination.py` ein Grenzfall-Test je Richtung (höchster erlaubter Offset ⇒ 200, erster unerlaubter ⇒ 422).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_pagination.py
Doku: keine (intern)
Abhängt von: T1

### T4 — Server: int-Pfadparameter begrenzen  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/router.py, apps/server/app/modules/api_keys/router.py, apps/server/app/modules/frp/generate_router.py
Änderung: die Pfadparameter `*_id: int` auf `IntPk`/`BigIntPk` umstellen — je Route am Spaltentyp des adressierten Modells geprüft. Das ist die Route, auf der `user_id ≥ 2**31` heute 500 liefert.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T5 — Server: Integer-Felder und Id-Listen im Body begrenzen  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/router.py, apps/server/app/modules/users/router.py, apps/server/app/modules/frp/generate_router.py
Änderung: zuerst dieselbe Schema-Suche wie für die Parameter, aber über die **Request-Bodies** (Integer-Felder ohne `maximum`) — das ist die von Worker2 benannte Lücke. Dann `data.ids` (`notifications`) und `server_ids` (`users` zwei Stellen, `frp`) sowie die dabei gefundenen Felder im Schema auf `list[IntPk]` bzw. `list[BigIntPk]`; die Prüfung gehört ins Schema, nicht vor den `in_()`-Aufruf. Test für den belegten Fall (`ids` jenseits von BIGINT ⇒ 422).
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T6 — `_validate_tags` lehnt ab statt zu werfen  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_input_hardening.py
Änderung: `_validate_tags` (Zeile 65) prüft als Erstes den Typ — kein `list` bzw. ein Element ohne `str` ergibt `ValueError` mit Feldbezug statt `AttributeError`/`TypeError`. `mode="before"` bleibt (die Normalisierung soll rohe Werte sehen), die sechs Registrierungen in `frp/`, `ansible/`, `servers/schemas.py` bleiben unberührt. Test mit dict, int, None und bool als `tags`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py
Doku: keine (intern)

### T7 — Server: NUL-Byte in Textfeldern ablehnen  [ ]
Komponente: server · Dateien: apps/server/app/core/bounds.py, das Schema hinter `POST /api/enrollment/token/for`, der zugehörige Test
Änderung: ein `SafeText`-Typ in `bounds.py`, der `\x00` ablehnt (Postgres nimmt kein NUL in Textwerten), und sein Einsatz im Benutzernamen-Feld dieser Route. Bewusst nur dort, wo der Fuzz-Lauf es belegt hat — kein Flächen-Refactor aller Textfelder (YAGNI).
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T8 — Server: Fremdschlüssel-Verletzung am Rand fangen  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_isolation.py
Änderung: beim Anlegen einer Verbindung mit `server_id` die Existenz prüfen und mit 422 plus Feldbezug antworten, statt die `ForeignKeyViolation` durchlaufen zu lassen. Keine neue Fehlerform, dasselbe Format wie die übrigen 422.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_isolation.py
Doku: keine (intern)

### T9 — Monitoring: Paginierung und Id-Listen begrenzen  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/alerts.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/routers/templates.py
Änderung: dieselben Grenzen wie im Server, hier lokal deklariert (Monitoring ist ein eigener Dienst und teilt keinen Code mit dem Server): die drei `Query(0, ge=0)` in `alerts.py` und `checks.py` (zwei Stellen) und die `template_ids`-Liste. Das sind die zwei Routen, an denen der erste echte CI-Lauf des Fuzz-Jobs gefallen ist.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine (intern)

### T10 — Obsolete Ausschlüsse entfernen  [ ]
Komponente: server · Dateien: apps/server/tests/schemathesis_exclude.toml, apps/monitoring/tests/schemathesis_exclude.toml, CHANGELOG.md
Änderung: jeden Eintrag, den T2–T9 erledigt haben, entfernen — und den Fuzz-Lauf danach real fahren, um zu sehen, was übrig bleibt. Ein Eintrag, der weiter nötig ist, bekommt eine **neue** Begründung aus diesem Lauf; keiner bleibt mit der alten stehen. `CHANGELOG` unter Unreleased: 422 statt 500 an den Rändern.
Verify: bash scripts/tests/run.sh unit --strict --step schemathesis --only server monitoring ca-issuer
Doku: CHANGELOG
Abhängt von: T2, T3, T4, T5, T6, T7, T8, T9
