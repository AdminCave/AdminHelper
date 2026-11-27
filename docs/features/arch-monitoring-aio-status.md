<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring nextcloud-aio: Check auf `status.php` mit Backup-Bedingung

Roadmap R-1825 (Folge von R-1515), Grundlage `docs/adr/0004-monitoring-neuordnung.md` §6.4 (Bedingungen), Vorgänger
P1d (R-1638, `docs/features/arch-monitoring-neu-p1d.md`: `when` an einer Regel). Stand `origin/main@9704ac3f3`.

## Problem / Motivation

Das Modul `nextcloud-aio` (`apps/monitoring/app/catalog/modules/nextcloud_aio.py`, Version 1) prüft den
Mastercontainer und über die App-Sicht `nextcloud_aio`, ob die dauerhaft betriebenen Container laufen und ob ein
Backup läuft (Feld `backup`). Ob Nextcloud selbst antwortet, prüft es nicht: `status.php` des Apache-Containers
fehlt (`nextcloud_aio.py:23`, „Not covered“), weil das nächtliche Backup (`daily-backup.sh` des Mastercontainers)
alle Container stoppt und ein HTTP-Check jede Nacht `critical` würde.

P1d hat `when` an einer Regel gebaut: Eine Regel ruht, solange ein Feld eines anderen Probe-Checks derselben
Instanz die Bedingung bekannt nicht erfüllt. Für `status.php` reicht das nicht, aus zwei Gründen:

1. **Ein Probe-Fehler kommt vor den Regeln.** Ist der Apache-Container gestoppt, meldet der Agent den Lauf als
   `error` („container … is not running: it listens on no TCP port“, `target.go`); `ProbeChecker.evaluate`
   (`apps/monitoring/app/checkers/probe.py:361`) gibt dann `critical` zurück, bevor eine Regel gelesen wird. Ein
   `when` an einer Regel lässt also genau den Fall, um den es geht, nicht ruhen.
2. **Das Ziel liegt in einem anderen Container.** Instanz des Moduls ist der Mastercontainer; `status.php` beantwortet
   der Container `nextcloud-aio-apache` (Port 8000). Ein Ziel bindet heute an den Container der Instanz, an einen
   Compose-Dienst des Projekts oder an den einzigen Container mit dem Image des Moduls (`Target`,
   `apps/monitoring/app/catalog/model.py:112`; `_target_name`, `apps/monitoring/app/module_sync.py:225`). AIO ist kein
   Compose-Projekt, und der Apache-Container trägt ein anderes Image als der Mastercontainer.

Dazu kommt eine Lücke aus P1d: Das Ergebnis eines Geschwister-Checks zählt im selben Report nur, wenn der
Geschwister-Check vorher bewertet wurde; die Reihenfolge ist die der Check-IDs (`_push_checks`,
`apps/monitoring/app/routers/agent.py:418`), also zufällig (uuid4). Beim Wechsel in ein Backup liest der
`status`-Check damit je nach ID noch das alte `backup = false` und meldet einen Fehlschlag mehr als nötig.

## Ziel & Nicht-Ziele

**Ziel**

- Ein Katalog-Check kann als Ganzes ruhen: `Check.when` (eine `Condition` mit `check`, also auf ein Feld eines
  anderen Probe-Checks desselben Moduls). Hält die Bedingung bekannt nicht, ist der Check `ok` mit einer Meldung,
  die das Ruhen und das Ergebnis des Laufs nennt; das gilt auch für einen Probe-Fehler. Fehlt der Wert oder ist er
  veraltet, bewertet der Check wie heute (ADR 0004 §6.4: „Beide Formen fallen bei fehlenden Daten in Richtung
  Melden“).
- Ein Katalog-Ziel kann einen festen Container der Installation nennen: `Target.container`. Gebunden wird er nur,
  wenn der letzte Scan des Hosts einen Container dieses Namens sah.
- Der Push-Pfad bewertet erst die Checks ohne Bedingung auf ein Geschwister, dann die mit: Ein Geschwister-Ergebnis
  desselben Reports zählt immer, unabhängig von den IDs.
- `nextcloud-aio` Version 2 bekommt den Check `status`: `GET /status.php` an `nextcloud-aio-apache:8000` mit
  `Host: localhost`, Felder und Regeln wie im Modul `nextcloud`, ruhend, solange `aio.backup` nicht `false` ist; die
  Karte zeigt die Version.

**Nicht-Ziele**

- Keine Änderung am Agent: Er löst einen Container schon über seinen Namen auf (`containerEndpoint` →
  `inspectContainer`, Muster `^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$`), und der Agent-Plan (`module_plan._probe`)
  schickt `when` nicht mit, weil der Server bewertet. Die Notiz der Zeile („Agent“) und die P1d-Notiz
  („Agent-Änderung“) erwarteten eine; sie ist nicht nötig.
- Keine Änderung an Desktop und Web: `details.resting` hat die Form aus P1d; die Desktop-UI schickt die Config eines
  Checks beim Bearbeiten unverändert zurück (`apps/desktop/ui/src/lib/models/monitorCheck.ts:8`), die Web-UI
  bearbeitet keine Checks.
- Keine Bedingung, die der Admin am Check setzt oder ändert: `when` eines Checks setzt nur das Modul (wie Sensor und
  Ziel). Die Ausnahme mit Bedingung (ADR §6.5) bleibt ein eigenes Vorhaben.
- Keine Ketten: Ein Geschwister, das selbst auf ein Geschwister wartet, zählt mit dem Ergebnis des Reports davor.
  Kein Modul braucht heute mehr als eine Ebene.
- Kein Check auf Port und TLS des öffentlichen Webservers (`APACHE_PORT` gehört dem Admin), kein AIO unter Windows
  oder einer anderen Container-Runtime.
- Keine Alembic-Migration, keine neue Route.

## Betroffene Komponenten & Dateien

Nur `apps/monitoring` (Dienst Monitoring); kein Server-, Gateway-, PKI-, Agent-, FRP- oder Install-Pfad.

| Datei | Änderung |
|---|---|
| `app/catalog/model.py` | `Target.container` (`:112`, Prüfung in `_consistent` `:127`, neuer Serializer); `Check.when` (`:291`, Prüfung in `_consistent` `:392`, Serializer `:314`); `_sibling_fits` (`:464`) für Regel- und Check-Bedingung; `Module._consistent` (`:495`) prüft beide |
| `app/check_configs.py` | `ProbeConfig.when` (`:201`), an `Check.model_validate` in `_fits_the_catalog` (`:222`) weitergereicht |
| `app/routers/checks.py` | `"when"` in `_PROBE_MEASURE` (`:138`): eine API-Änderung oder ein Weglassen von `when` wird wie bei Sensor und Ziel mit 422 abgelehnt |
| `app/module_sync.py` | `probe_config` (`:364`) bindet `Target.container` und schreibt `when` in die Config, nur wenn gesetzt |
| `app/checkers/probe.py` | `evaluate` (`:312`): Check-Bedingung nach der Frische-Prüfung, vor `status == "error"` (`:361`) |
| `app/routers/agent.py` | Reihenfolge im Push (`:161`, `_push_checks` `:418`), `_probe_siblings` (`:525`) liest auch die Check-Bedingung; Risikopfad |
| `app/catalog/modules/nextcloud_aio.py` | Version 2, Check `status`, Karte, Docstring |
| Tests | `tests/test_catalog.py`, `tests/test_check_configs.py`, `tests/test_module_sync.py`, `tests/test_checks_crud.py`, `tests/test_probe_checker.py`, `tests/test_probe_when.py`, `tests/test_catalog_nextcloud_aio.py`, neu `tests/test_check_when.py` |
| Doku | `docs/admin/monitoring.html`, `docs/developer/monitoring.html` (+ EN), ADR 0004 §6.4 (Nachtrag), `changelog.d/arch-monitoring-aio-status.md` |

## Datenmodell / API / Migrationen

**Katalog-Modell** (`catalog/model.py`)

- `Check.when: Condition | None = None`. Gültig nur mit `when.check` (ein fehlgeschlagener Lauf hat keine eigenen
  Werte) und nicht an einem zentralen Check (`central`). `Module._consistent` verlangt wie für eine Regel-Bedingung
  einen anderen Probe-Check des Moduls, unter dessen `fields` `when.field` steht und der nicht nur an eine andere
  Instanz gebunden ist; dazu wird `_sibling_fits(check, rule, by_key)` zu `_sibling_fits(check, when, where,
  by_key)`, die Meldungen der Regel-Form bleiben wörtlich. Der Serializer lässt `when` weg, wenn es fehlt.
- `Target.container: str | None` (Muster des Agents, `^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$`): ein fester
  Containername der Installation. Nur mit `kind == "container"` und nicht zusammen mit `service`, `image_fallback`
  oder `alternatives`. `Target` bekommt einen Serializer, der `container` weglässt, wenn es fehlt.
- **Invariante:** Kein Katalog-Check außer `nextcloud-aio.status` dumpt `when` oder `container`; der
  Definitions-Hash (`definition_hash`, `module_sync.py:80`) jedes anderen Checks bleibt Bit für Bit. Ein Test hält
  das fest.

**Bindung** (`module_sync.probe_config`): Mit `t.container` ist der Name des Ziels dieser Name, wenn der letzte Scan
des Hosts einen Container so nannte (`docker ps --all`, auch gestoppte), sonst bleibt der Check mit dem Grund
„no container <name> on this host“ ungebunden (Fund „changed“ zeigt ihn wie jeden anderen). `_lacks_port` und
`image_tags` gelten danach wie gehabt. Ist `check.when` gesetzt, schreibt `probe_config` `config["when"] =
check.when.model_dump()`; sonst fehlt der Schlüssel, die Configs aller anderen Checks bleiben gleich.

**Probe-Config** (`check_configs.ProbeConfig`): Feld `when: Condition | None = None`, geprüft wie im Katalog (über
`Check.model_validate`; `when.check` ist Pflicht). Der Agent-Plan schickt nur feste Schlüssel
(`module_plan._probe`), `when` erreicht den Agent nicht.

**API** (`PUT /checks/{id}`): `when` gehört zu den Teilen, die nur ein Modul setzt (`_PROBE_MEASURE`); eine
geänderte oder weggelassene Bedingung wird mit 422 „Only rules, interval_s and timeout_s of a probe config can be
changed; its module sets the rest“ abgelehnt, eine unverändert zurückgeschickte angenommen. `GET` liefert die Config
samt `when` wie gespeichert. Kein neues Feld in `MonitorCheckOut`, keine Vertrags-Drift zu Desktop oder Web.

**Bewertung** (`ProbeChecker.evaluate`): Reihenfolge nach der Änderung: Nicht-gelaufen-Werte → unbekannter Status →
ohne Zeit → veraltet (alle wie heute) → **Check-Bedingung** → `error` → Werte und Regeln. Hält `config["when"]`
bekannt nicht (`_condition_holds(when, {}, siblings, now, factor) is False`, dieselbe Funktion wie für Regeln):

- Status `ok`, `problems` leer, `firing` leer, `resting` je Regel des Checks `{"key": <rule_key>, "when": <when>}`
  (die Form aus P1d);
- Meldung `Resting (<check>.<field> = <Wert des Geschwisters>): Probe failed: <error>` bzw. `…: OK: <Werte>`;
- ein erfolgreicher Lauf speichert Werte und Baseline wie heute, ein Fehlschlag lässt die gespeicherten stehen.

`ok` statt `unknown`: wie eine ruhende Regel in P1d (alle Regeln ruhen → `ok`) und damit die Dämpfung
(`consecutive_fails`, Standard 3) zurückgesetzt bleibt; mit `unknown` zählte jedes Backup-Fenster Fehlschläge hoch,
und der erste Fehlschlag nach dem Backup meldete sofort.

**Push-Pfad** (`routers/agent.py`): Ein Helfer `_sibling_names(config)` sammelt die Geschwister-Namen aus den Regeln
und aus `config["when"]`; `_probe_siblings(db, check, config)` nutzt ihn, und der Push sortiert die Checks stabil
nach „nennt kein Geschwister“ vor „nennt eins“, innerhalb der Gruppen weiter nach ID. Die Reihenfolge bleibt
deterministisch (die Begründung von 4.46 für `order_by(MonitorCheck.id)`).

**Migrationen:** keine. Bestehende AIO-Instanzen bekommen den neuen Check beim Start über `sync_catalog`
(`module_sync.py:814`): still angelegt, Fund „changed“ und offen; erst das Übernehmen macht ihn meldend.

## Externe Integrationen

Nextcloud All-in-One, offizielles Repo `nextcloud/all-in-one` (gelesen @5446eb3):

- `Containers/apache/nextcloud.conf`: `Listen 8000`, `<VirtualHost *:8000>`; `Containers/apache/healthcheck.sh`:
  `nc -z 127.0.0.1 8000`; `Containers/apache/Caddyfile`: `reverse_proxy 127.0.0.1:8000`.
- `php/containers.json`: feste Namen, darunter `nextcloud-aio-apache`; keine Compose-Labels.
- `Containers/mastercontainer/daily-backup.sh`: legt `daily_backup_running` an, stoppt die Container, sichert, startet
  sie und entfernt die Markierung danach; `Containers/apache/start.sh` wartet vor dem Start auf Nextcloud (Port 9000).
- Nextcloud `status.php`: JSON mit `installed`, `maintenance`, `needsDbUpgrade`, `versionstring`, wie im Modul
  `nextcloud` genutzt.

**Nicht verifiziert** an einer laufenden AIO-Installation (keine in CI oder im VM-Pool): dass `status.php` an
`nextcloud-aio-apache:8000` mit `Host: localhost` antwortet und wie lange Apache nach dem Backup braucht. Belegt ist
es nur aus den Quellen oben.

## Trade-offs & Alternativen

1. **Bedingung am Check statt an der Regel.** Alternative: eine Regel-Bedingung, die auch einen Probe-Fehler
   ruhen lässt (etwa ein Flag `rests_errors`). Sie verteilte dieselbe Bedingung auf jede Regel, und welche Regel
   den Fehler „trägt“, wäre willkürlich. Ein Check, dessen Ziel im Backup-Fenster fehlt, ruht als Ganzes: Das ist
   die Aussage, die das Modul treffen will. **Empfehlung: am Check.**
2. **`ok` statt `unknown` beim Ruhen.** Siehe oben (P1d-Verhalten, Dämpfung). `unknown` hieße außerdem „kein Wissen“,
   obwohl der Server weiß, warum der Check schweigt. **Empfehlung: `ok` mit eigener Meldung.**
3. **Fester Containername statt Erkennung über das Image.** Die AIO-Container tragen eigene Images
   (`ghcr.io/nextcloud-releases/aio-apache`); eine Suche über ein zweites Image bräuchte ein neues Feld mit eigener
   Mehrdeutigkeit. AIO vergibt die Namen fest (`containers.json`), der Agent prüft sie mit demselben Muster.
   **Empfehlung: `Target.container`.**
4. **Reihenfolge im Push.** Ohne sie bleibt beim Wechsel ins Backup ein roher Fehlschlag mehr möglich (je nach
   Check-IDs zwei Reports in Folge statt einem); die Dämpfung deckte beides beim Standard 3, nicht bei einem
   Admin-Wert 1 oder 2. Die
   Alternative, im Handler das Geschwister aus dem Report selbst zu bewerten, verdoppelte die Bewertung. **Empfehlung:
   stabile Sortierung, eine Ebene.**

## Risiken & Rollback

- **Zeitfenster am Backup-Anfang:** Der Agent fährt alle fünf Minuten einen Zyklus (`defaultInterval`,
  `apps/agent/cmd/adminhelper-agent/run.go`) und darin beide Probes mit Intervall 300 kurz nacheinander
  (`runDueProbes`); die Dämpfung zählt je Report (`next_fail_count`, `check_engine.py`). Fällt die Markierung zwischen
  den `aio`- und den `status`-Lauf eines Zyklus, gibt dieser Report einen rohen Fehlschlag, der nächste ruht; die
  Dämpfung (Standard 3, `models.py:130`) deckt ihn. Ein Admin mit `consecutive_fails = 1` bekommt dann gelegentlich
  eine Meldung zu Backup-Beginn; das steht in der Admin-Doku.
- **Nach dem Backup:** Die Markierung fällt, sobald die Container gestartet sind; Apache wartet auf Nextcloud. Ein
  kurzer Start (unter 3 × 5 min) bleibt unter der Dämpfung; ein langer (etwa nach einem automatischen Update) wird
  gemeldet, zu Recht.
- **Port 8000 ist nicht veröffentlicht:** Veröffentlicht ist nur `APACHE_PORT` (Caddy, `containers.json`). Liest der
  Agent die lauschenden Ports im Netz des Containers nicht (`listeningIn`, `apps/agent/internal/discovery/
  discovery.go`: nur Linux, eigenes Netz, lesbarer Namespace), sieht der Scan nur diesen Port, und `_lacks_port`
  lässt den Check mit dem Grund „container nextcloud-aio-apache has no port 8000“ ungebunden. Das ist sichtbar und
  besser als ein falsch gebundenes Ziel.
- **Reihenfolge und Sperren:** Ändert sich die Config eines Checks zwischen zwei gleichzeitigen Pushes desselben
  Servers, können beide die Sperren der Zustandszeilen in verschiedener Folge nehmen. Postgres bricht dann eine
  Transaktion ab; der SAVEPOINT je Check (R-0635) begrenzt den Verlust auf diesen Check dieses Reports.
- **Hash-Stabilität:** Ein ungewollt gedumptes `when`/`container` änderte jeden Hash und meldete jede übernommene
  Instanz als „changed“. Der Invarianten-Test fängt das.
- **Rollback:** Revert des Merges. Der alte `ProbeConfig` lehnt eine gespeicherte Config mit `when` ab; der
  Agent-Plan lässt diese Checks dann mit Log-Zeile aus (`module_plan._probes`), sie veralten zu `unknown` („the agent
  no longer runs it“), der Admin kann sie löschen. Kein Datenverlust, keine Migration zurückzunehmen.

## Doku-Impact

Admin-Doku Monitoring DE+EN: Zeile `nextcloud-aio` (neuer Check, Ruhen im Backup, nicht mehr „Not covered“) und der
Absatz zu `when` (ein Check kann als Ganzes ruhen). Entwickler-Doku Monitoring DE+EN: Zeile `probe.py`
(Check-Bedingung vor `error`, Reihenfolge im Push) und der Absatz zu `Rule`/`Condition` (`Check.when`,
`Target.container`). ADR 0004 §6.4: Nachtrag, dass R-1825 die Empfehlung als Check-Bedingung umsetzt. Changelog-
Fragment `changelog.d/arch-monitoring-aio-status.md` (umlautfrei).

## Offene Fragen

Keine an Kevin. Die Zeile ist angenommen (Kevin 2026-11-27); Verhalten (`ok` beim Ruhen) folgt ADR 0004 §6.4 und der
P1d-Entscheidung, dass Meldung und Status eines Checks ohne Bedingung bleiben, wie sie sind. Zu berichten: Eine
Agent-Änderung ist nicht nötig.
