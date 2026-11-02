<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-3 — Spec

## Problem
- **R-1011:** `without_refused_extra_config` in `apps/server/app/modules/frp/config_generator.py` merkt sich
  Warnungen je `(Name, Grund)` (`_first_warning`, Z. 150). Der Kommentar davor (Z. 142–146) behauptet, die Gründe der
  anderen Filter („no secret“, „visitor port“, „local port“, „server name“, `allowUsers`) hätten ein Leerzeichen und die
  refused Keys seien bare TOML-Keys ohne Leerzeichen, beide träfen sich nie. Das stimmt nicht: ein abgelehnter Key
  heißt gerade deshalb abgelehnt, weil er kein bare Key ist, und kann `no secret` oder `allowUsers` heißen. Dann teilt er
  den Schlüssel mit einem Filtergrund, und eine der beiden Warnungen wird verschluckt. Zusätzlich beschreibt der
  Sync-Absatz in `docs/developer/server.html` Z. 101 (DE und EN) nicht, dass ein Tunnel mit abgelehntem Servernamen
  ausgelassen wird, und nicht die frpc-toml-Gleichheit (Hash und `config` stammen aus derselben gefilterten Liste). Das
  genaue Verhalten wird beim Bau am Code (`without_*`-Filter, `active_tunnels`) gelesen, nicht aus dem Ticket geraten.
- **R-1025:** `apps/server/app/modules/enrollment/expiry.py:68` (`agents`) nutzt `Query.distinct(col)` für ein
  DISTINCT ON; SQLAlchemy warnt dafür mit `SADeprecationWarning`. Der Ersatz ist `postgresql.distinct_on`.

## Ziel / Nicht-Ziele
Beide Funde beheben, ohne sichtbares Verhalten zu ändern (Warnungen erscheinen jetzt auch bei Kollision; dieselbe
Zeilenmenge bei `agents`). Nicht: Filter umbauen, Reihenfolge oder Texte der Warnungen ändern.

## Dateien
`apps/server/app/modules/frp/config_generator.py`, `apps/server/tests/test_config_generator.py`,
`docs/developer/server.html`, `docs/en/developer/server.html`, `apps/server/app/modules/enrollment/expiry.py`,
`apps/server/tests/test_certificate_expiry.py` (falls Test nötig).

## Datenmodell / API / Integrationen
Keine Migration, keine API-Änderung. SQLAlchemy: `sqlalchemy.dialects.postgresql.distinct_on` laut Doku der
installierten Version vor dem Bau lesen.

## Trade-offs
Kollision: den Grund der `extra_config`-Keys präfixen (`("extra_config", *refused)`, wie `("refused fields", *refused)` in
Z. 246) statt die Filtergründe zu ändern. Empfehlung: Präfix, weil es ein Ort ist und das Muster schon besteht.

## Risiken & Rollback
Gering. Je Task ein Commit.

## Doku-Impact
`docs/developer/server.html` und EN-Pendant (Sync-Absatz). Kein Changelog-Fragment: nur interne Warnung und
Deprecation.

## Offene Fragen
Keine.
