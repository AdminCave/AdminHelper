<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-4 — Spec

## Problem
- **R-1025:** `enrollment/expiry.py` `agents()` (Z. 74) ruft `Query.distinct(IssuedCertificate.line_id)` auf, um die
  neueste Zertifikatszeile je Linie zu holen. SQLAlchemy 2.1 meldet dafür `SADeprecationWarning` („Passing expression to
  distinct to generate a DISTINCT ON clause is deprecated“) und verweist auf `postgresql.distinct_on`. SQLAlchemy ist
  auf 2.1.8 gepinnt (`apps/server/requirements.txt`), `distinct_on` ist dort verfügbar. Eine künftige Version darf den
  alten Weg entfernen.
- **R-1124:** Der Server-Testlauf warnt `StarletteDeprecationWarning: Using httpx with starlette.testclient is
  deprecated; install httpx2 instead` (starlette 1.10.0 gepinnt, `starlette/testclient.py` bevorzugt `httpx2`, fällt auf
  `httpx` mit Warnung zurück). `httpx2` 2.16.0 ist auf PyPI (`requires_python >=3.11`). Ein Release darf den Rückfall
  entfernen; dann liefe kein Test mit dem `TestClient` mehr.

## Ziel / Nicht-Ziele
`agents()` liefert dieselben Zeilen wie vorher, ohne Warnung; die Server-Suite läuft mit `httpx2` im `TestClient` ohne
`StarletteDeprecationWarning`. Nicht-Ziel: `httpx` der App selbst (Laufzeit, Hooks, Proxy) bleibt; `pytest-httpx`
mockt weiter `httpx`. Monitoring und ca-issuer nutzen ebenfalls den `TestClient`; sie sind nicht Teil dieser Zeilen.

## Dateien
`apps/server/app/modules/enrollment/expiry.py`, `apps/server/tests/test_certificate_expiry.py` (Gegenprobe),
`apps/server/requirements-dev.txt`, `DEVELOPMENT.md` (ein Satz).

## Datenmodell / API / Integrationen
Keine Migration, kein API-Vertrag. `distinct_on` stammt aus `sqlalchemy.dialects.postgresql`; die Form wird beim Bau
gegen die SQLAlchemy-2.1-Doku und das erzeugte SQL geprüft (nicht verifiziert bis dahin). `httpx2` kommt nur in
`requirements-dev.txt` (nicht in die gehashte Produktiv-Lockfile).

## Trade-offs
- R-1025: `postgresql.distinct_on(col)` als Spaltenausdruck in `select`/`Query.add_columns`-Form statt `.distinct(col)`.
  Empfehlung: kleinste Änderung, die dieselbe SQL erzeugt (`DISTINCT ON (line_id)` + gleiche `ORDER BY`).
- R-1124: `httpx2` zusätzlich installieren (Empfehlung, wie `starlette` selbst rät) statt die Warnung per
  `filterwarnings` zu unterdrücken, denn das verschiebt nur das Problem.

## Risiken & Rollback
Gering. `lock-pins.py` (CI-Job `python-lock-server`) meldet, falls `httpx2` einen gelockten Pin verschiebt (z. B.
`idna`, `anyio`); dann Pin im Lock nachziehen oder Version wählen. Ein Commit je Task zurücknehmbar.

## Doku-Impact
`DEVELOPMENT.md` nennt, welcher Dienst `httpx` bzw. `httpx2` nur für den `TestClient` braucht. Sonst keine.

## Offene Fragen
Keine. R-1176 (Servernamen CONIN$/CONOUT$) fährt nicht mit: `feature/arch-namen` ändert `servers/schemas.py`; die
Zeile wechselt in `tasks/klein-ref-server-5.md`.
