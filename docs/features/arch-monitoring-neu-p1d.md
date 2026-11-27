<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Neuordnung, Phase 1d: Regel-Schicht für eingebaute Checks

Roadmap R-1638, Grundlage `docs/adr/0004-monitoring-neuordnung.md` (§6 Regelmodell, §10 Migrationsplan), Vorgänger
P1a (R-1559) und P1b (R-1636, `docs/features/arch-monitoring-neu-p1b.md`). Stand `origin/main@12b9034e9`.

## Problem / Motivation

- **Wer eine Schwelle ändert, verliert jedes Katalog-Update.** Ändert der Admin eine Regel eines Probe-Checks, markiert
  `mark_module_overrides` (`apps/monitoring/app/module_sync.py:147`) das ganze Feld `config`. Danach überspringt
  `_update` (`module_sync.py:517`, Grund `:531` „the admin changed the check's rules; they stay“) jede neue
  Definition des Katalogs: neue Regeln, korrigierte Grenzen und neue Felder kommen nie mehr an (R-1567, als Notbehelf
  gebaut). Das ADR (§6.2) will stattdessen eine eigene Schicht je Regel und einen Drei-Wege-Merge.
- **Eine Regel hat keinen Namen.** `Rule` (`apps/monitoring/app/catalog/model.py:142`) ist `field`, `op`, `value`,
  `level`, dazu `if_absent` und `unless`. Ohne Schlüssel kann weder ein Override noch ein Merge sagen, welche Regel
  gemeint ist; das Feld allein kollidiert in 43 Katalog-Checks (Warnung und kritisch auf demselben Feld, ADR §6.1).
- **Grenzen flattern.** Eine Regel feuert, sobald der Wert die Grenze überschreitet, und endet beim nächsten Wert
  darunter (`_rate`, `apps/monitoring/app/checkers/probe.py:168`). Ein Wert, der um die Grenze pendelt, meldet jedes
  Mal neu. Das ADR (§6.1) sieht `clear` als Entwarnungsgrenze vor.
- **Eine Regel kann kein Feld eines anderen Checks lesen.** `unless` liest nur das eigene Ergebnis
  (`model.py:137`). Deshalb lässt das Modul `nextcloud-aio` den Check auf `status.php` weg, der im Backup-Fenster
  ausfällt (`apps/monitoring/app/catalog/modules/nextcloud_aio.py:23`). Kevin hat am 2026-11-18 entschieden, dass
  solche Abhängigkeiten im Katalog als `when` stehen (ADR §6.4, §14 Frage 11).

## Ziel & Nicht-Ziele

Kevin hat P1 am 2026-11-19 in fünf Schritte geteilt; dies ist **P1d „Regel-Schicht“**. Seine Entscheidungen vom
2026-11-27 (Fragenblock der Planung, alle nach Empfehlung):

1. **Regel-API:** neue Route `GET/PUT /checks/{id}/rules` mit Katalog-Regeln, Overrides je Schlüssel, wirksamen Regeln
   und Konflikten. `PUT /checks/{id}` übersetzt geänderte `config.rules` in Overrides; was sich nicht als Override
   ausdrücken lässt (neue Regel, anderes Feld oder anderer Operator, geändertes `when`/`unless`/`if_absent`), lehnt
   es mit 422 und einem Verweis auf `/rules` ab. Additiv, `MonitorCheckOut` bleibt.
2. **Altbestand:** Beim Start werden markierte Checks idempotent umgewandelt, genau dort, wo es geht: Die Zeile
   steht auf der heutigen Katalog-Version, und der Unterschied lässt sich als Overrides ausdrücken. Die Bewertung
   bleibt dieselbe. Alles andere bleibt eingefroren wie heute, die Anzahl steht im Log.
3. **`status.php` (Folge von R-1515):** eine eigene FEAT-Zeile nach P1d (R-1825). Sie braucht zwei weitere Dinge: eine
   Bedingung, die auch einen Probe-Fehler ruhen lässt, und ein Ziel in einem anderen AIO-Container (Agent-Änderung).
   P1d baut `when` und belegt es mit Test-Modulen.
4. **Konflikte:** API und Log, die Oberfläche kommt in P2. `GET /checks/{id}/rules` trägt die Konflikte des letzten
   Merges, das Log nennt sie. Ruhende Regeln stehen additiv in `_details` der Probe. Meldung und Status des Checks
   bleiben wie heute.

Ziel:
1. **Regelform:** `Rule` bekommt optional `key`, `clear` und `when`. Ohne `key` gilt `<field>.<level>`. Fehlen die
   neuen Felder, entfallen sie im Dump, also bleibt jeder Definitions-Hash gleich (`definition_hash`,
   `module_sync.py:79`, `test_every_catalog_rule_dumps_as_the_catalog_hashes_it` in
   `tests/test_rule_model_prototype.py:55`). `rule_problems` prüft einen Regelsatz.
2. **Bewertung:** `clear` hält eine feuernde Regel, bis der Wert die Entwarnungsgrenze passiert (Zustand `firing` in
   `_details`). `when` lässt eine Regel ruhen, solange die Bedingung bekannt falsch ist (Liste `resting` in
   `_details`). Ohne `clear` und `when` ist das Ergebnis Bit für Bit das heutige.
3. **Regel-Schicht:** Neue Spalte `monitor_checks.rule_layer` mit dem gebundenen Katalog-Regelsatz, den Overrides des
   Admins je Schlüssel (`value`, `clear`, `level`, `enabled`) und den Konflikten des letzten Merges. `config.rules`
   ist weiter, was der Checker liest, und immer `effective(katalog, overrides)`.
4. **Merge statt Überspringen:** Übernimmt der Admin ein Katalog-Update, führt `_update` alten Katalog, neuen Katalog
   und Overrides nach ADR §6.2 zusammen (`both_changed`, `removed`, `redefined`, `clear_dropped`). Nur eingefrorene
   Altzeilen überspringt es weiter.
5. **Regel-API** nach Entscheidung 1, hinter dem Präfix `checks` des Admin-Proxys, das schon freigegeben ist.

Nicht-Ziele (Roadmap-Titel R-1638, ADR §13):
- **`rises`, `not in`, eine `unless`-Liste und die Umstellung der Checker auf Sensor plus Regelsatz:** P2 (R-1560).
  Vorlagen-Checks (CPU, Platte, Dienste) tragen ihre Schwellen weiter in eigenen Config-Feldern. Die Regel-Schicht
  gilt in P1d nur für Probe-Checks; nur sie haben einen Regelsatz.
- **`object` in einer Bedingung** (ADR §6.4) und die Bedingung an einer Ausnahme: kein Katalog-Check braucht sie
  heute; die Bedingung an einer Ausnahme gehört zu P2.
- **Ausnahme mit Geltung „Regel“:** P1b (`arch-monitoring-neu-p1b.md`, Nicht-Ziele) hatte sie P1d zugeordnet. Sie
  nimmt eine Regel aus der Bewertung (ADR §7), braucht also die Wirkung „prüfen, nicht bewerten“, die erst P1c
  (R-1637) baut. P1d liefert den Regelschlüssel, an dem sie hängt; den Schalter je Regel gibt es als Override
  `enabled`. Dafür steht R-1826 (`neu`).
- **Keine Oberfläche:** Desktop und Web bleiben unverändert. Die Schublade mit ruhenden Regeln und Konflikten ist P2.
- **Kein `status.php`-Check** (Entscheidung 3).
- **Kein Zurücksetzen eingefrorener Altzeilen:** Sie bleiben, wie der Admin sie gebaut hat. Den Weg zurück zum
  Katalog bietet P2 an.

## Betroffene Komponenten & Dateien

Nur `apps/monitoring`, kein Server-, Gateway-, PKI-, Agent- oder Client-Pfad.

| Datei | Änderung |
|---|---|
| `app/catalog/model.py` | `Rule` (`:142`) mit `key`, `clear`, `when`; neues `Condition`; Serializer (`:158`) lässt sie ungesetzt weg; Prüfungen in `Rule`, `Check` (`:203`) und `Module` (`:371`, `when.check` gegen die Geschwister); `rule_problems` |
| `app/checkers/probe.py` | `_rate` (`:168`) mit Hysterese und Bedingung über Schlüsselwort-Argumente; `evaluate` (`:215`) trägt `firing` weiter und schreibt `resting` |
| `app/routers/agent.py` | `_evaluate_push_check` (`:437`) gibt einer Probe, deren Regeln einen anderen Check lesen, die Ergebnisse ihrer Geschwister mit (`config["_siblings"]`, wie `_check_id` `:458`) |
| `app/rule_layer.py` (neu) | `rule_key`, `effective`, `overrides_from` (Übersetzung eines Regelsatzes in Overrides), `merge` (Drei-Wege), Lesen/Schreiben der Spalte, `record_rule_layers` (Umwandlung beim Start) |
| `app/models.py` | `MonitorCheck` (`:118`) bekommt `rule_layer` (Text, NULL) |
| `alembic/versions/b6d8f0a2c4e6_rule_layer.py` (neu) | Spalte anlegen und entfernen, `down_revision = "f4b6d8a0c2e4"` |
| `app/main.py` | `record_rule_layers` nach `reconcile_builtin_templates` (`:85`), vor `sync_catalog` (`:90`), eigener try/except wie die Nachbarn |
| `app/module_sync.py` | `_create` (`:482`) schreibt die Schicht; `_update` (`:517`) führt zusammen statt zu überspringen; `mark_module_overrides` (`:147`) spiegelt bei Zeilen mit Schicht die Marke `config` aus den Overrides |
| `app/routers/checks.py` | `GET/PUT /checks/{id}/rules`; `update_check` (`:418`) übersetzt `config.rules` |
| `app/schemas.py` | `RuleOverride`, `RuleConflict`, `CheckRulesOut`, `CheckRulesInput` |
| `tests/…` | neue Tests je Task, `tests/openapi.snapshot.json` |

Unverändert: `MonitorCheckOut` (`app/schemas.py:461`), `check_configs.ProbeConfig` (`:201`, prüft die neuen Felder
über `Check.model_validate`, `:222`), `tests/rule_model_prototype.py` mit seinen Tests (P2 ersetzt sie), der
Server-Proxy (Präfix `checks` deckt `/checks/{id}/rules`, `apps/server/tests/test_monitoring_proxy_allowlist.py`), der
Agent (`fetchExpecting` in `apps/agent/internal/probe/sensor_http.go` liefert bei einem Fehler keine Werte, deshalb
Entscheidung 3).

## Datenmodell / API / Migrationen

### Regelform (`model.py`)

```python
class Condition(_Model):
    field: str
    op: Literal["eq", "ne", "in", "lt", "le", "gt", "ge"]
    value: _Scalar | list[_Scalar]
    check: str | None = Field(None, pattern=_KEY)   # anderer Check desselben Moduls; leer = eigenes Ergebnis
    max_age: int | None = Field(None, ge=1)         # Sekunden; nur mit check

class Rule(_Model):
    ...                                             # wie heute
    key: str | None = Field(None, pattern=_KEY)
    clear: float | int | None = None                # nur bei lt, le, gt, ge
    when: Condition | None = None
```

- **Schlüssel:** `rule_key(rule) = rule.key or f"{rule.field}.{rule.level}"`. Ein gesetzter Schlüssel passt auf
  `_KEY` (ohne Punkt) oder ist `<eigenes Feld>.<Stufe>`: der eingefrorene Schlüssel, den `effective` nach einer
  Stufen-Änderung ausdrücklich setzt (T4). Er kann also einem abgeleiteten gleichen; die Eindeutigkeit tragen
  `rule_problems` (in `Module`, in der Regel-API) und `effective`, das nur Katalog-Schlüssel ausgibt.
- **`clear`** liegt auf der sicheren Seite der Grenze: bei `gt`/`ge` echt darunter, bei `lt`/`le` echt darüber.
  Eine feuernde Regel hält, solange `op(wert, clear)` gilt.
- **`when`** bewertet wie heute mit `_same` und den Vergleichen von `probe.py`. `max_age` gibt es nur zusammen mit
  `check`.
- **`rule_problems(rules) -> list[str]`:** Schlüssel doppelt. `clear` bei einem anderen Operator oder auf der falschen
  Seite, ein Wert der Bedingung, der nicht zum Operator passt, und `max_age` ohne `check` scheitern schon in `Rule`
  und `Condition`. `Module` meldet den ersten Fund von `rule_problems` als Fehler, die Regel-API als 422; `Check`
  nicht, weil der Agent-Plan jede gespeicherte Probe-Config als `Check` neu prüft und eine Altzeile von vor den
  Schlüsseln zwei gleiche tragen darf (sie bleibt im Plan und wird eingefroren). `Module` prüft zusätzlich, dass
  `when.check` einen anderen Probe-Check desselben Moduls nennt, dessen `fields` `when.field` enthalten. Ohne
  `check` muss `when.field` zu den eigenen `fields` gehören (wie `unless`, `Check._consistent`, `model.py:304`).
- **Hash:** Die Serializer-Schleife (`:158`) lässt auch `key`, `clear` und `when` weg, solange sie `None` sind.

### Bewertung (`probe.py`)

- Neu ist `_rating(rules, values, baseline, ts, *, firing, siblings, report_ts) -> Rating` mit `status`, `problems`,
  `firing` und `resting`; `evaluate` ruft es auf. `_rate(rules, values, baseline, ts) -> (status, problems)` bleibt mit
  der heutigen Signatur als dünne Hülle, weil der Gleichlauf-Test des Prototyps es so aufruft.
- **Hysterese:** `_details.firing` ist die Liste der Schlüssel, die im letzten bewerteten Lauf hielten. Eine Regel
  mit `clear`, deren Schlüssel darin steht und deren Wert die Grenze nicht mehr, aber `op(wert, clear)` noch erfüllt,
  hält weiter; die Meldung nennt die Entwarnung (`…, clears at <clear>`). Läufe ohne Bewertung (nicht ausgeführt,
  Fehler, veraltet) und eine Regel ohne Wert übernehmen den Schlüssel aus dem Lauf davor, damit eine Lücke die
  Hysterese nicht beendet (Richtung Melden).
- **Bedingung:** Die Regel ruht nur, wenn der Wert der Bedingung vorliegt, frisch ist und die Bedingung nicht erfüllt.
  Das eigene Ergebnis ist immer frisch. Beim Geschwister-Check gilt `max_age`, ohne `max_age` dieselbe Grenze wie für
  die eigene Probe (zweimal das Intervall des Geschwisters mal Bremsfaktor plus Laufzeit, `probe.py` in `evaluate`).
  Eine ruhende Regel steht als `{"key": …, "when": {…}}` in `_details.resting` und zählt nicht zur Bewertung. Ein
  Probe-Fehler kehrt vor `_rate` zurück; ihn lässt `when` nicht ruhen (Entscheidung 3).
- **Geschwister** (`agent.py`): Nur wenn eine Regel des Checks `when.check` trägt, liest `_evaluate_push_check` die
  gespeicherten `_details` (`values`, `measured_ts`) und das Intervall der Probe-Checks derselben Instanz
  (`server_id`, `module_id`, `module_instance`), ohne Sperre, und legt sie als `config["_siblings"]` nach
  `module_check_key` ab. Die Reihenfolge der Auswertung bleibt nach ID (Deadlock-Schutz, `_push_checks`
  `agent.py:418`). Ein Geschwister, das im selben Report später drankommt, liefert also den Stand des Reports davor;
  das Alter entscheidet über die Frische.

### Regel-Schicht (`monitor_checks.rule_layer`)

Text mit JSON, `NULL` für Checks ohne Regelsatz (alle außer Probe-Checks) und für eingefrorene Altzeilen:

```json
{"catalog": [<Regeln des gebundenen Katalog-Checks, wie probe_config sie dumpt>],
 "overrides": {"<schlüssel>": {"value": 90, "clear": 80, "level": "critical", "enabled": false}},
 "conflicts": [{"key": "<schlüssel>", "kind": "both_changed", "part": "value", "at": "<iso>"}]}
```

- **`effective(catalog, overrides)`:** Katalog-Reihenfolge, je Regel die Teile des Overrides darüber, Regeln mit
  `enabled: false` fallen heraus. Weicht der Schlüssel durch eine Stufen-Änderung vom abgeleiteten ab, trägt die
  wirksame Regel ihn ausdrücklich (`key`), damit er eingefroren bleibt. Ein Override mit `clear: null` nimmt die
  Entwarnung des Katalogs weg. **Invariante:** Ohne Overrides ist `config.rules` genau das, was `probe_config`
  (`module_sync.py:353`, `:416`) heute schreibt.
- **Normalisierung:** Ein Override-Teil, der dem Katalog gleicht, entfällt; ein leerer Override entfällt ganz. So
  greift „Katalog zog auf den Wert des Admins nach“ ohne Sonderfall.
- **`overrides_from(catalog, rules)`:** übersetzt einen gesendeten Regelsatz. Jede gesendete Regel findet ihre
  Katalog-Regel über ihren Schlüssel. Passt keiner, gilt die einzige noch freie Katalog-Regel mit gleichem `field` und
  `op`; das ist eine Stufen-Änderung eines alten Clients. Feld, Operator, `when`, `unless` und `if_absent` müssen
  gleich sein. Katalog-Regeln ohne gesendete Regel werden `enabled: false`. Alles andere ist nicht ausdrückbar
  (`None` mit Grund): eine Regel ohne Gegenstück, zwei Regeln für eine Katalog-Regel oder ein geänderter fester Teil.
- **`merge(old, new, overrides) -> (overrides, conflicts)`** nach der Tabelle in ADR §6.2: Ein Teil, den der Katalog
  nicht änderte, behält den Wert des Admins. Ein Teil, den der Katalog auf den Wert des Admins nachzog, verliert den
  Override. Haben beide denselben Teil geändert, bleibt der Admin-Wert (`both_changed`). Eine entfernte Regel nimmt
  ihren Override mit (`removed`). Bewertet die Regel ein anderes Feld oder mit anderem Operator, entfallen `value`
  und `clear`, Stufe und Schalter bleiben (`redefined`). Liegt die Entwarnung nach dem Merge auf der falschen Seite,
  entfällt sie (`clear_dropped`). Ändert der Katalog die Stufe einer Regel ohne `key`, ändert sich ihr Schlüssel:
  Der alte endet als `removed`.
- **Marke `config`:** Bei Zeilen mit Schicht ist `config` in `overridden_fields` genau dann gesetzt, wenn Overrides
  bestehen. Clients sehen also weiter „Regeln geändert“. `_update` liest die Marke nur noch bei Zeilen ohne Schicht.

### Migration und Altbestand

- **Alembic `b6d8f0a2c4e6_rule_layer`** (nach `f4b6d8a0c2e4`): `add_column monitor_checks.rule_layer Text NULL`,
  der Downgrade entfernt sie. Daten schreibt die Revision nicht, weil die Umwandlung den Katalog im Code braucht.
- **`record_rule_layers(db)`** beim Start, idempotent, für jeden Probe-Check eines Moduls mit `rule_layer IS NULL`:
  - **ohne Marke `config`:** `catalog` = die gespeicherten `config.rules`. Sie sind der Katalog-Stand, an den die
    Zeile gebunden ist, auch wenn ein Update noch aussteht. `overrides` ist leer.
  - **mit Marke `config`:** Die Zeile wird nur umgewandelt, wenn `module_check_hash` dem heutigen
    `definition_hash` gleicht und `overrides_from(heutiger Katalog, config.rules)` gelingt. Außerdem muss
    `effective(...)` in Reihenfolge und Inhalt `config.rules` entsprechen; die einzige erlaubte Abweichung ist ein
    ausdrücklicher `key`, wo der abgeleitete gilt. Dann sind Status und Meldung dieselben. Sonst bleibt die Zeile
    eingefroren (`NULL`).
  - Das Log nennt die Zählung, etwa `Rule layers: 12 recorded, 3 converted, 1 frozen (the admin's rules stay)`, und
    je eingefrorene Zeile die Check-ID mit dem Grund (Debug).
  - **Vor `sync_catalog`:** `sync_catalog` gibt Zeilen ohne Hash den heutigen Hash als Stand (`module_sync.py:700`).
    Die Umwandlung soll eine solche markierte Zeile beim ersten Start nicht für aktuell halten.

### API (`routers/checks.py`, Präfix `checks`, `require_internal`)

| Route | Antwort |
|---|---|
| `GET /checks/{id}/rules` | 200 `CheckRulesOut`; 404 bei unbekanntem Check oder bei einem Check ohne Regelsatz („This check has no catalog rules“) |
| `PUT /checks/{id}/rules` | Body `CheckRulesInput {overrides: {key: RuleOverride}}`, ersetzt alle Overrides; 200 `CheckRulesOut`; 404 wie oben; 409 bei eingefrorener Zeile; 422 bei unbekanntem Schlüssel, unpassendem Wert, Entwarnung auf der falschen Seite, unbekanntem Teil |

- `CheckRulesOut`: `check_id`, `frozen` (bool), `catalog`, `overrides`, `effective`, `conflicts`. Bei eingefrorener
  Zeile ist `effective` gleich `config.rules`, `catalog` und `overrides` sind leer.
- `RuleOverride`: `value`, `clear` (Zahl oder `null`), `level`, `enabled`, alle optional, `extra="forbid"`.
- `RuleConflict`: `key`, `kind` (`both_changed`, `removed`, `redefined`, `clear_dropped`), `part` (`value`, `clear`,
  `level` oder `null`), `at`.
- Ein `PUT` schreibt Schicht, `config.rules` und Marke in einer Transaktion. Die Zeile wird mit `FOR UPDATE` gelesen,
  so dass ein gleichzeitiges Übernehmen sie nicht überschreibt.
- **`PUT /checks/{id}`:** Hat eine Probe eine Schicht und kommt `config.rules` geändert an, gilt
  `overrides_from(layer.catalog, rules)`. Ist das nicht ausdrückbar, antwortet die Route mit 422: `"This change to the
  rules cannot be kept across catalog updates (<Grund>); change the rules with PUT /checks/{id}/rules"`. Gespeichert
  wird `effective(...)`, nicht der gesendete Satz. Eingefrorene Zeilen und zentrale Checks verhalten sich wie heute.
- Die Desktop- und Web-Typen ändern sich nicht. `sync-from-web.sh --check` bleibt unberührt.

## Externe Integrationen

Keine. Kein Wire-Format ändert sich: Agent-Plan, Report und VictoriaMetrics bleiben gleich. Die neuen Regelfelder
bleiben im Monitoring-Dienst, der Agent bekommt keine Regeln (`_probe` in `app/module_plan.py:105` sendet Sensor, Ziel, Parameter und Felder).

## Trade-offs & Alternativen

- **Wirksame Regeln in `config.rules` materialisieren (gewählt)** oder bei jeder Bewertung aus der Schicht berechnen.
  Materialisiert bleiben der Checker, `ProbeConfig`, alte Clients (`GET /checks` zeigt die wirksamen Regeln) und
  eingefrorene Zeilen unverändert. Der Preis ist eine Invariante (`config.rules` = `effective`), die jeder Schreiber
  einhält. Es gibt nur drei: `_create`, `_update` und die Regel-API mit ihrer Übersetzung; Tests sichern sie ab.
- **Katalog-Stand in der Schicht speichern (gewählt)** oder aus dem Hash rekonstruieren. Der Hash sagt nur, ob sich
  etwas änderte. Der Merge braucht aber den alten Regelsatz, und den Modul-Code des alten Stands gibt es nach einem
  Update nicht mehr.
- **Eigene Spalte (gewählt)** oder Overrides in `config`. Dann sähe `ProbeConfig` (`extra="forbid"`) sie, der Agent-Plan
  müsste sie herausfiltern, und `_same_config` hielte jede Override-Änderung für eine Config-Änderung.
- **Hysterese-Zustand in `_details` (gewählt)** oder in `monitor_object_state`. `_details` trägt schon `values` und
  `baseline` von Lauf zu Lauf; eine Tabelle käme erst mit Objekt-Regeln in P2.
- **Geschwister aus gespeicherten `_details` (gewählt)** oder aus dem laufenden Report. Der Report enthält nur die
  Proben, die diesmal liefen; die gespeicherten Ergebnisse gibt es immer, und ihr Alter ist bekannt. Die Reihenfolge
  der Auswertung lässt sich nicht nach Abhängigkeiten sortieren, ohne den Deadlock-Schutz aufzugeben.

## Risiken & Rollback

- **Hash-Drift:** Ein neues Feld im Dump böte allen 366 Katalog-Checks ein Update an. Der Hash-Test des Prototyps und
  `test_the_definition_hash_is_stable_and_tells_definitions_apart` (`tests/test_module_sync.py:1146`) laufen im
  Verify von T1.
- **Bewertung ändert sich still:** Der Gleichlauf-Test (`tests/test_rule_model_differential.py`) und der Prototyp-Test
  laufen in T2 unverändert mit. Bei der Umwandlung des Altbestands gilt die Gleichheit von `effective` und
  `config.rules` als Bedingung, sonst bleibt die Zeile eingefroren.
- **Merge verliert eine Admin-Grenze:** Die Tabelle aus ADR §6.2 wird je Zeile als Test gebaut, jeder Konflikt landet
  in der Schicht und im Log.
- **Zwei Alembic-Köpfe:** P1c (R-1637, zurückgestellt) und andere Monitoring-Vorhaben können ebenfalls eine Revision
  auf `f4b6d8a0c2e4` setzen. Vor jedem Push wird `origin/main` hereingemergt und `alembic heads` geprüft
  (`tests/test_alembic_builtin.py`); wer als Zweiter merged, hängt seine Revision um.
- **Rollback:** Ein Revert des Branches lässt die Spalte stehen, wenn die Migration lief. Alter Code ignoriert sie;
  die Marke `config` steht bei Zeilen mit Overrides weiter, also friert alter Code genau diese Zeilen wieder ein, wie
  heute. Der Alembic-Downgrade entfernt die Spalte, `config.rules` bleibt die wirksame Fassung. Es geht keine
  Admin-Grenze verloren, nur die Trennung von Katalog und Override.

## Doku-Impact

DE und EN: Die Admin-Doku Monitoring (`#probe-status`: `clear`, `when`, ruhende Regeln; Fund `changed` und
„Geänderte Definitionen“: Merge statt Überspringen, Konflikte, eingefrorene Altzeilen) und die Entwickler-Doku
Monitoring (Modul-Modell: `key`, `clear`, `when`; Katalog-Updates; `rule_layer`, `record_rule_layers`; die Marke
`config`). Die API-Referenz bekommt `GET/PUT /checks/{id}/rules` und die 422 von `PUT /checks/{id}`. Dazu kommt
`changelog.d/arch-monitoring-neu-p1d.md`.

## Offene Fragen

Keine aus Kevins Bereich; die vier der Planung hat er am 2026-11-27 entschieden. Für das Gate notiert:
- Die Ausnahme mit Geltung „Regel“ wandert aus P1d in R-1826 nach P1c (Nicht-Ziele).
- `status.php` wird R-1825 (Entscheidung 3).
