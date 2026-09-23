<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Randvalidierung für Zahlen und Text — Spec

## Problem / Motivation

Die Generator-Suiten aus Stufe 8b haben eine zusammenhängende Klasse belegt: **Eingaben, die
erst in der Datenbankschicht scheitern, werden nicht am Rand abgefangen.** Der Fehler kommt
als HTTP 500 zurück, nicht als 422. Belegt auf allen drei Eingangswegen:

| Weg | Beispiel | Ursache |
|---|---|---|
| Pfad | `DELETE`/`PUT /api/users/{user_id}` ab `user_id ≥ 2**31` | `user_id: int` unbegrenzt, Postgres-`INTEGER` läuft in `NumericValueOutOfRange` |
| Query | `GET /alerts?offset=2**63`, `GET /status?offset=…`, `GET /checks?offset=…` | `Query(0, ge=0)` ohne obere Schranke |
| Body | `POST /api/notifications/read` mit Id jenseits von BIGINT | `data.ids` geht ungeprüft in `id.in_()` |
| Text | `POST /api/enrollment/token/for` mit NUL-Byte im Benutzernamen | Postgres erlaubt kein `0x00` in Textwerten |

Dazu zwei Nachbarn derselben Wurzel: `_validate_tags` läuft als
`field_validator(mode="before")` und sieht rohe Werte **vor** der Typprüfung — ein dict, int,
None oder bool erzeugt `AttributeError`/`TypeError` statt einer Validierungsmeldung, auf sechs
Routen, weil derselbe Validator in drei Schemas registriert ist. Und `POST /api/connections`
mit einer nicht existierenden `server_id` läuft in eine ungefangene `ForeignKeyViolation`.

**Warum jetzt:** Der Fuzz-Gate aus 8b ist ein Pflicht-Check, und seine Fundmenge hängt an der
Maschine (Hypothesis speist Quell-Literale in die Generierung ein). Solange die Klasse offen
ist, liefert CI Ausschlüsse in Raten nach und bricht dabei auf PRs, die damit nichts zu tun
haben. 27 Server- und 4 Monitoring-Ausschlüsse sind heute nur Deckel; ein Großteil fällt mit
diesem Vorhaben weg.

## Ziel & Nicht-Ziele

**Ziel:** Jede Zahl und jeder Text, der von außen in eine Datenbankspalte fließt, wird am Rand
gegen die Grenze **dieser Spalte** geprüft. Wer sie überschreitet, bekommt 422 mit Feldbezug.
Die dadurch obsoleten Schemathesis-Ausschlüsse verschwinden im selben Vorhaben.

**Nicht-Ziele:**
- Kein neues Fehlerformat, keine Änderung an bestehenden 4xx-Antworten.
- Keine Umstellung von `created_at` auf tz-aware Zeitstempel (eigener Befund, eigene Zeile:
  betrifft jedes `datetime`-Feld und damit jeden Client).
- Kein Umbau der Paginierung selbst (kein Cursor, keine Obergrenze für `limit` jenseits der
  bestehenden).
- Keine Migration. Die Spaltentypen bleiben, nur die Eingangsprüfung kommt dazu.

## Betroffene Komponenten & Dateien

**Server** (`apps/server/`):
- neu: `app/core/bounds.py` — die begrenzten Typen an einer Stelle.
- Paginierung ohne obere Schranke: `app/modules/hooks/router.py`,
  `app/modules/connections/router.py`, `app/modules/audit/router.py`,
  `app/modules/servers/router.py`, `app/modules/notifications/router.py`.
- int-Pfadparameter: `app/modules/users/router.py`, `app/modules/api_keys/router.py`,
  `app/modules/frp/generate_router.py`.
- Id-Listen im Body: `app/modules/notifications/router.py` (`data.ids`),
  `app/modules/users/router.py` (`server_ids`, zwei Stellen),
  `app/modules/frp/generate_router.py` (`server_ids`).
- Validator: `app/modules/frp/schemas.py` (`_validate_tags`, Zeile 65) — die sechs
  Registrierungen in `frp/schemas.py`, `ansible/schemas.py`, `servers/schemas.py` bleiben, wie
  sie sind.
- FK: `app/modules/connections/router.py` (Anlegen mit `server_id`).
- Text: das Schema hinter `POST /api/enrollment/token/for`.

**Monitoring** (`apps/monitoring/`):
- `app/routers/alerts.py`, `app/routers/checks.py` (zwei Stellen) — Paginierung.
- `app/routers/templates.py` — Id-Listen (`template_ids`).

**Tests:** die neuen Grenzfall-Tests je Modul; `apps/server/tests/schemathesis_exclude.toml`
und `apps/monitoring/tests/schemathesis_exclude.toml` verlieren die Einträge, die dieses
Vorhaben erledigt.

## Datenmodell / API / Migrationen

Keine Migration, kein neues Feld, kein neuer Endpunkt. Die Änderung ist eine **Verengung der
Eingabemenge**: Werte, die heute 500 erzeugen, erzeugen künftig 422. Für Clients, die
gültige Werte schicken, ändert sich nichts. Das OpenAPI-Schema bekommt die Schranken als
`maximum`/`minimum` — dadurch prüft Schemathesis sie selbst und generiert sie nicht mehr als
gültige Eingabe.

**Grenzen, an den tatsächlichen Spaltentyp gekoppelt:**
- `INTEGER`-PK ⇒ `ge=1, le=2147483647`
- `BIGINT`-PK ⇒ `ge=1, le=9223372036854775807`
- Paginierung (`offset`, `skip`) ⇒ `ge=0, le=2147483647`

Welche Tabelle welchen PK-Typ hat, wird je Modell nachgesehen, nicht geraten. Das ist der
einzige Punkt, an dem dieses Vorhaben sorgfältig sein muss: eine zu enge Schranke macht
gültige Ids ungültig.

## Externe Integrationen

Keine. Kein FRP, kein Tauri, kein VictoriaMetrics, keine Proxmox-API.

## Trade-offs & Alternativen

1. **Zentrale Typen in `core/bounds.py`** (Empfehlung). Ein `Annotated[int, Field(...)]` je
   Grenze, überall importiert. Vorteil: eine Stelle, ein Name, im Schema sichtbar. Nachteil:
   ein Modul mehr.
2. Schranken an jeder Fundstelle einzeln hinschreiben. Weniger Struktur, aber jede Zeile
   lokal lesbar. Verworfen: acht Paginierungs-Stellen mit derselben Zahl laden zur Drift ein.
3. Ein Exception-Handler, der `DataError`/`OverflowError` global in 422 übersetzt. Verworfen:
   er verschiebt das Problem in die Fehlerbehandlung, statt die Eingabe zu prüfen, und
   verdeckt echte Datenbankfehler (Root-Cause vor Symptom).

Für `_validate_tags`: der Validator bleibt `mode="before"` (er soll rohe Werte normalisieren),
prüft aber zuerst den Typ und wirft `ValueError` statt durch einen Attributzugriff zu laufen.
Alternative wäre `mode="after"`; verworfen, weil dann die Normalisierung (strippen,
Leereinträge) nicht mehr greift.

Für die FK-Verletzung: **422 mit Feldbezug** auf `server_id`, nicht 404. Der Server ist ein
Feld im Body, kein adressierter Ressourcenpfad.

## Risiken & Rollback

- **Zu enge Schranke** macht gültige Ids ungültig. Gegenmittel: Grenze je Modell aus dem
  Spaltentyp ableiten, plus ein Test, der die höchste erlaubte Id akzeptiert.
- **Schema-Änderung ist nach außen sichtbar** (`maximum` im OpenAPI). Der CI-Job
  „OpenAPI breaking changes" prüft das; eine engere Eingabemenge ist kein Bruch für Clients,
  die gültige Werte senden, aber der Lauf muss grün bleiben oder die Abweichung begründet sein.
- **Entfernte Ausschlüsse** könnten mehr aufdecken, als dieses Vorhaben fixt. Dann bleibt der
  Eintrag mit neuer Begründung stehen, statt den Fix zu verbiegen.
- Rollback: jeder Task ist ein eigener Commit, `git revert` je Modul.

## Doku-Impact

`CHANGELOG.md` (nach außen sichtbares Verhalten: 422 statt 500). Keine Änderung an
`DEVELOPMENT.md` oder `docs/` — es entsteht kein neuer Betriebs- oder Installationsschritt,
kein neues Flag, keine neue Env-Variable.

## Entschieden am Design-Gate (Kevin, 2026-09-22)

1. **Paginierungs-Obergrenze:** die **technische** Grenze der jeweiligen Spalte
   (`le=2147483647` bei `INTEGER`). Ein Offset jenseits der Zeilenzahl liefert ohnehin eine
   leere Seite; eine fachliche Zahl wäre willkürlich und müsste gepflegt werden.
2. **`created_at` tz-naiv:** **nicht hier.** Eigene Roadmap-Zeile, weil es jedes `datetime`-Feld
   in jedem typisierten `response_model` betrifft und damit jeden Client, der dem Schema folgt.
   Dieses Vorhaben bleibt reine Eingangsprüfung ohne Wirkung auf Antworten.
3. **Reihenfolge:** erledigt — PR #29 ist am 2026-09-22 gemergt (66548aea), der Weg ist frei.
4. **Plan-Dateien:** Spec und Ledger sind der **erste Commit dieses Branches**, gesetzt **am
   Gate** — nicht erst mit dem Bau. Damit ist das Artefakt versioniert, *bevor* Kevin freigibt,
   die Reihenfolge des Design-Gates bleibt erhalten, `main` bekommt nie einen Direkt-Commit, und
   eine Lane kann diesen Branch auscheckchen. Die Freigabe selbst ist der Commit, der den
   Ledger-Kopf auf `Status: aktiv` setzt. Die Anpassung der Harness dazu läuft als eigenes
   Vorhaben (`tasks/plan-artifact-flow.md`), weil Harness-Dateien nicht in einem Feature-Branch
   mitgeändert werden.
