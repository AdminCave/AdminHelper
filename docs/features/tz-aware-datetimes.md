<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Zeitstempel der Server-API mit UTC-Offset (R-0064)

## Problem / Motivation

Der Server liefert `datetime`-Felder ohne Offset, etwa `"2026-10-05T12:00:00"`. Sein OpenAPI deklariert dieselben
Felder als `format: date-time`, und RFC 3339 verlangt dort einen Offset. Ein Client, der dem Schema folgt, kann den
Wert nicht richtig lesen: JavaScript parst einen String ohne Offset als Ortszeit. Gemessen mit Node 22 unter
`TZ=Europe/Berlin` wird `"2026-10-05T12:00:00"` zu 10:00Z, `"…Z"` und `"…+00:00"` dagegen zu 12:00Z. Web und Desktop
zeigen damit heute jede Server-Zeit um die Differenz zu UTC verschoben, im Sommer 2 Stunden. Kurz vor Mitternacht
kann auch das Datum um einen Tag falsch sein.

Die Lücke ist bekannt und bewusst offen: `docs/features/input-boundary-validation.md`, „Entschieden am Design-Gate“
Punkt 2, stellt sie als eigene Zeile zurück. `apps/server/tests/schemathesis_exclude.toml:142-154` und `:170-175`
schließen deshalb die Prüfung `response_schema_conformance` für drei Operationen aus. Zwei Schemas tragen den
Zeitstempel absichtlich als `str`, um `format: date-time` nicht zu versprechen (`users/schemas.py:77-79`,
`frp/schemas.py:199-202`, `:218-219`).

## Ziel & Nicht-Ziele

**Ziel:** Jeder Zeitstempel, den die Server-API ausgibt, ist RFC 3339 in UTC mit `Z`. Das gilt für die typisierten
`response_model`s und für die untypisierten `to_dict`-Antworten. Die drei Schemathesis-Ausschlüsse entfallen.
(Nachtrag aus dem Bau: zwei fallen; `create_hook` bleibt mit einem zweiten Grund, der darunter lag, R-0207.)

**Nicht-Ziele:**
- Kein neuer Client-Code. Web und Desktop lesen `Z` schon heute richtig (unten); sie werden nur korrekt, nicht
  geändert.
- Der Monitoring-Dienst (`apps/monitoring`) bleibt, wie er ist. Er hat eine eigene DB mit der Konvention „naiv,
  aber UTC“ (`apps/monitoring/app/core/time.py:7-24`), und der Server-Proxy reicht seine Antworten unverändert durch
  (`apps/server/app/modules/monitoring_proxy/router.py:76-80`, `:140-145`). Die Desktop-Stellen, die seine Zeiten
  zeigen, gehören in eine eigene Zeile (offene Frage 6).
- Keine Eingabe-Änderung. Kein Request-Schema und kein Query-Parameter des Servers hat einen `datetime`-Typ.
- Ob die Speicherung auf `TIMESTAMPTZ` umzieht, entscheidet offene Frage 1. Dieses Ledger plant den empfohlenen Weg
  ohne Migration.

## Betroffene Komponenten & Dateien

### Speicherung heute (`apps/server`)

- **28 Datetime-Spalten:** 21 naive `DateTime`, 7 `DateTime(timezone=True)`. Die 7 sind `audit_log.timestamp`
  (`audit/models.py:24-26`) und sechs in `notifications/models.py` (`:65`, `:91-93`, `:101`, `:138`, `:140`, `:141`).
- **Konvention der naiven Spalten:** „naiv, aber UTC“ (`app/core/time.py:5-18`). Den Default schreibt
  `utc_now_sql()` = `timezone('UTC', now())` (`app/core/time.py:31`, seit Migration `c4d8e2f1a6b9`), in Python
  `utcnow_naive()` (`:25`). Daneben schreiben Python-Pfade aware UTC-Werte (`datetime.now(timezone.utc)`, 18
  Aufrufe).
- **Session-Zeitzone:** Der Engine setzt keine (`app/core/database.py:14-20`), Alembic ebenso (`alembic/env.py:88-92`).
  Der db-Dienst bekommt `TZ=${TZ:-Europe/Berlin}` (`docker-compose.yml:18`). Welche `TimeZone` eine Session im
  laufenden Stack hat, hängt an der initdb-Einstellung des Volumes und ist **nicht verifiziert**.
- **Treiber:** psycopg 3.3 (`apps/server/requirements.txt`) liest `timestamptz` in der Zeitzone der Verbindung. Darum
  tragen die `isoformat()`-Werte von Audit und Notifications heute den Offset der Session.
- **Alembic:** lineare Kette, Kopf `8bdf9641a51f` (`alembic/versions/8bdf9641a51f_fill_empty_stcp_secrets.py`).
  `tests/test_alembic_builtin.py:34-38` prüft `test_model_definitions_match_ddl`: Ein geänderter Spaltentyp ohne
  Migration fällt dort durch.

### Wo die API Zeitstempel ausgibt

- **Typisiert, mit `format: date-time`** (11 Stellen im Snapshot `apps/server/tests/openapi.snapshot.json`):
  - `ApiKeyResponse.created_at` (`api_keys/schemas.py:22`, geerbt von `ApiKeyCreatedResponse`)
  - `HookResponse.created_at/last_run/next_run` (`hooks/schemas.py:63`, `:66`, `:67`, geerbt von
    `HookDetailResponse` und `HookCreatedResponse`)
- **Typisiert als `str`:**
  - `users/schemas.py:77-79`, befüllt aus `users/router.py:33`
  - `frp/schemas.py:199-202`, `:218-219`
- **Untypisiert über `to_dict` mit `isoformat()`:**
  - naiv, also ohne Offset: `frp/models.py:60-61`, `:130`; `servers/models.py:49`; `ansible/models.py:32-33`;
    `provisioning/models.py:53-56` und `provisioning/router.py:82`; `enrollment/models.py:60-63` (Nachtrag aus dem
    Bau: dieses `to_dict` hat im Server keinen Aufrufer, die Mint-Antworten tragen keinen Zeitstempel)
  - mit dem Offset der Session: `audit/models.py:41`; `notifications/models.py:106`, `:115`
- **Hook-Skript-Kontext:** `last_run` naiv (`hooks/router.py:340`, `hooks/scheduler.py:72`), `triggered_at` aware mit
  `+00:00` (`hooks/router.py:329`).
- **Schon mit Offset:** `connections.last_used` ist eine String-Spalte mit `+00:00` (`connections/router.py:183`); der
  Client schreibt `Z`. Beides funktioniert.

### Wer die Felder liest

- **Web (`apps/web`):** `src/lib/utils/datetime.ts:15-28` (`new Date(iso)`, ohne Korrektur), aufgerufen in Audit,
  Hooks, Users und ApiKeys. Mit `Z` richtig, ohne Offset verschoben. Die E2E-Mocks tragen schon `Z`
  (`tests/e2e/mocks.ts`).
- **Desktop-UI (`apps/desktop/ui`):**
  - `lib/utils/timeAgo.ts:12` für Notifications, `components/infra/tabs/ProvisioningTab.svelte:107-114`: `new Date`
    ohne Korrektur. Mit `Z` richtig.
  - Drei Stellen hängen `Z` selbst an (`lib/models/maintenance.ts:46-47`,
    `components/monitoring/MaintenanceModal.svelte:53`, `components/infra/tabs/MonitoringTab.svelte:155`). Sie lesen
    nur Monitoring-Daten und brächen an `+00:00` (`…+00:00Z` ist Invalid Date), nicht an `Z`.
- **Desktop-Rust (`apps/desktop/src-tauri`):** reicht Antworten als `serde_json::Value` durch (`proxy.rs:44`, `:89`);
  keine Struct mit Datumstyp. Nicht betroffen.
- **Go-Agent (`apps/agent`):** dekodiert keine Zeitstempel des Servers. Nicht betroffen.
- **Monitoring:** liest keine Zeitstempel des Servers (`app/tag_sync.py:41-50`). Nicht betroffen.
- **CA-Issuer:** liest eine Tabelle des Servers direkt, mit eigenen naiven Spaltendefinitionen
  (`apps/ca-issuer/app/db.py:33-43`) und eigener naiver Zeitrechnung. Eine Änderung des JSON-Formats trifft ihn
  nicht. Eine Änderung des Spaltentyps (Weg b) müsste ihn im selben Schritt mitziehen.

## Datenmodell / API / Migrationen

Drei Wege. Die Wahl ist Kevins (offene Frage 1).

- **(a) Serialisierung mit UTC-Offset, ohne Migration:**
  - `app/core/time.py` bekommt einen Annotated-Typ `UtcDatetime` und eine Hilfsfunktion `iso_utc(dt)`. Ein naiver Wert
    gilt als UTC (die Konvention oben), ein aware Wert wird nach UTC umgerechnet; die Ausgabe ist `…Z`.
  - Die typisierten Schemas nutzen `UtcDatetime`, die `to_dict`-Stellen `iso_utc`. Das OpenAPI bleibt unverändert
    (`format: date-time` stand schon da), nur die Werte halten es jetzt ein.
  - Keine DB-Änderung, kein Eingriff in den CA-Issuer.
- **(b) Migration auf `TIMESTAMPTZ`:**
  - Eine Alembic-Revision stellt die 21 naiven Spalten um: `ALTER COLUMN … TYPE timestamptz USING … AT TIME ZONE
    'UTC'`.
  - Die Modelle bekommen `DateTime(timezone=True)`, `utc_now_sql()` und `utcnow_naive()` werden zu aware Werten.
  - Code, der heute naiv rechnet, wird angepasst; der CA-Issuer zieht seine Spaltendefinitionen im selben Schritt
    mit.
  - Ohne (a) lieferte die API danach den Offset der Session (`+02:00`), nicht `Z`.
  - **Vor einer Umstellung misst eine Task je Spalte, in welcher Zeitzone die Bestandswerte stehen.** Die Migration
    `c4d8e2f1a6b9` hat die Defaults erst nachträglich auf UTC gestellt.
- **(c) beides:** (a) jetzt, (b) danach als eigenes Vorhaben mit eigener Spec.

## Externe Integrationen

- **PostgreSQL** (Doku `datatype-datetime`, gelesen 2026-10-06):
  - „In a value that has been determined to be `timestamp without time zone`, PostgreSQL will silently ignore any
    time zone indication.“
  - `timestamp with time zone` wird „stored internally as UTC“ und bei der Ausgabe „converted from UTC to the
    current `timezone` zone“.
  - „Conversions between `timestamp without time zone` and `timestamp with time zone` normally assume that the
    `timestamp without time zone` value should be taken or given as `timezone` local time.“ Deshalb braucht (b) ein
    explizites `AT TIME ZONE 'UTC'`.
- **Pydantic 2.13** (gemessen, nicht aus der Doku): naiv wird zu `"2026-10-05T12:00:00"`, aware UTC zu `"…Z"`, aware
  `+02:00` zu `"…+02:00"`. Die Doku nennt nur `AwareDatetime`/`NaiveDatetime` als Typen, nicht das Format; die Form
  `Z` ist also gemessen.
- **JavaScript** (`new Date`, gemessen mit Node 22): ohne Offset Ortszeit; `Z` und `+00:00` richtig; `+00:00Z`
  Invalid Date.

## Trade-offs & Alternativen

**Empfehlung: (a), mit `Z`.** R-0064 ist ein Fehler des API-Vertrags, und (a) behebt ihn für jeden Client mit Code an
einer Stelle, ohne Datenbank und ohne Zweitdienst. (b) gibt der DB eine explizite Semantik, bringt für den Vertrag
aber nichts, was (a) nicht schon liefert, und kostet:
- eine Migration über 21 Spalten mit vorheriger Messung der Bestandswerte;
- einen Gleichschritt mit dem CA-Issuer;
- ohne (a) Offsets in Session-Zeit statt `Z`.

(c) ist (a) plus die Option auf (b) später. Das ist nur sinnvoll, wenn jemand die DB-Semantik wirklich braucht.

`Z` statt `+00:00`: Das ist Pydantics Form für UTC. Die drei Desktop-Stellen, die `Z` anhängen, bleiben damit
korrekt, auch wenn der Monitoring-Dienst später nachzieht.

Grenze von (a): Es setzt voraus, dass die naiven Werte UTC sind. Ein Bestandswert, der davon abweicht, erscheint mit
(a) weiterhin verschoben, nur jetzt mit Offset. Das zu prüfen, ist Sache von (b).

## Risiken & Rollback

- **Risiko (a):** Ein Client, der heute selbst `Z` anhängt, würde `…ZZ` bilden. Gesucht in Web, Desktop-UI, Rust,
  Agent, Monitoring und den Skripten: Die einzigen drei Stellen prüfen vorher `endsWith('Z')` und lesen nur
  Monitoring-Daten.
- **Risiko (a):** Hook-Skripte lesen `last_run` heute ohne Offset (offene Frage 4). Ein Skript, das den Wert als
  naiven String parst, bekäme einen anderen String.
- **Rollback (a):** Die Commits zurücknehmen. Daten bleiben unberührt, und die Clients lesen beide Formen.
- **Risiko (b):** eine falsche Umrechnung von Bestandswerten, eine Sperre der Tabellen während `ALTER TYPE` und ein
  Versatz zwischen Server und CA-Issuer, wenn nur einer umgestellt ist.
- **Rollback (b):** ein Downgrade `ALTER COLUMN … TYPE timestamp USING … AT TIME ZONE 'UTC'`. Der CA-Issuer geht im
  selben Zug zurück.

## Doku-Impact

- `docs/developer/api-reference.html` (DE + EN): ein Satz „Zeitstempel sind RFC 3339 in UTC mit `Z`“.
- `CHANGELOG.md` unter Fixed, mit einem Hinweis auf `last_run` im Hook-Skript-Kontext, falls Frage 4 Ja ergibt.

## Offene Fragen

1. **Weg (a), (b) oder (c)?** Empfehlung (a). Es behebt den Vertrag ohne Migration und ohne CA-Issuer. (b) nur als
   eigenes Vorhaben, wenn die DB-Semantik gebraucht wird. Dieses Ledger plant (a); bei (b) oder (c) kommt ein zweites
   Ledger dazu.
2. **Auch die untypisierten `to_dict`-Antworten?** Sie versprechen kein `format: date-time`, haben aber denselben
   Client-Fehler (Server-, FRP-, Provisioning- und Ansible-Listen, Audit, Notifications; zu Enrollment siehe oben). Empfehlung ja:
   Sonst zeigt dieselbe Oberfläche manche Zeiten richtig und manche verschoben.
3. **`Z` oder `+00:00`?** Empfehlung `Z` (oben).
4. **`last_run` im Hook-Skript-Kontext mit `Z`?** Es ändert, was Nutzer-Skripte lesen; `triggered_at` trägt schon
   einen Offset. Empfehlung ja, mit Hinweis im CHANGELOG.
5. **Die `str`-Felder (`users`, `frp`) als `UtcDatetime` deklarieren?** Das OpenAPI bekäme dort `format: date-time`,
   und der Job `openapi-compat` würde das als Vertragsänderung zeigen. Empfehlung: `str` lassen und nur den Wert mit
   `Z` liefern. Ein engerer Vertrag gehört in ein eigenes Vorhaben.
6. **Monitoring als eigene Zeile?** Seine Zeiten (Checks, Wartung, Alarme) zeigt der Desktop heute verschoben
   (`lib/models/monitoring.ts:125-135` ohne Korrektur). Empfehlung ja, eine eigene Roadmap-Zeile: anderer Dienst, eigene
   DB, eigene Client-Stellen.
