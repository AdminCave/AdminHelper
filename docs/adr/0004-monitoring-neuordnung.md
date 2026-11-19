<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# ADR 0004 — Monitoring-Neuordnung: Objekt, Regel, Ausnahme, Problem, Abdeckung

- **Status:** **vorgeschlagen** — Stand 2026-11-18. Kevins Entscheidungen 1–11 stehen in §14; offen ist die
  Abnahme der Mockups (Frage 12), erst danach baut P1 (R-1559).
- **Betrifft:** `apps/monitoring` (Checker, Regeln, Zustand, Alerter), `apps/server` (Benachrichtigungs-Hub),
  `apps/desktop` (Monitoring-Ansicht), `apps/agent` (Datenlücken, §11), Doku.
- **Basis:** Spec [`docs/features/arch-monitoring-neu-p0.md`](../features/arch-monitoring-neu-p0.md) (R-1558 mit
  R-1515); Mockups unter `apps/desktop/ui/src/mockups/monitoring-neu/`; Regel-Prototyp
  `apps/monitoring/tests/rule_model_prototype.py` mit `test_rule_model_prototype.py` und
  `test_rule_model_differential.py`. Zeilenangaben gelten für `origin/main@3aa2499f1`; Monitoring und Hub sind bis
  `db7eeb363` unverändert.

---

## 1. Problem

Das Monitoring ist um Einzelwünsche gewachsen. Jeder weitere Wunsch (Ausnahme-Knöpfe, eine Backup- oder
SMART-Ansicht, eine Meldung bei neuen Funden) erzeugt heute einen weiteren Mechanismus und eine weitere Sonderansicht:

1. **Fünf Arten, etwas auszublenden:** der Schalter `enabled` (`apps/monitoring/app/models.py:126`), `silent` des
   Katalog-Syncs (`:147`), Ignorierlisten je Check-Typ (`apps/monitoring/app/check_configs.py:94`, `:114`, `:119`,
   `:139`, `:155`), Wartungsfenster (`MonitorMaintenance`, `models.py:481`) und Stummschalten je Person im Hub
   (`NotificationServerMute`, `apps/server/app/modules/notifications/models.py:304`). Keine trägt einen Grund, es gibt
   keine Gesamtliste, Ausgeblendetes verschwindet aus der Ansicht.
2. **Zwei Welten von Checks:** 12 eingebaute Typen (`apps/monitoring/app/check_types.py:21`) bewerten im Code, mit
   eigenem Ergebnisformat und meist eigener Ansicht; 125 Katalog-Module (366 Checks, 625 Regeln) laufen als `probe`
   bzw. `central`, bewerten deklarativ und teilen sich eine generische Karte.
3. **Zwei Benachrichtigungswege:** Alarmregeln (`MonitorAlertRule`, `models.py:222`, Mail und Webhook direkt) und
   der Hub (Matrix je Person, Vorfälle). Die Monitoring-Ansicht zeigt die Vorfälle nicht.
4. **Vier Entstehungswege für Checks** (Vorlage, Modul aus Fund, Scan-Vorschlag, Hand) und keine Antwort auf „ist
   alles überwacht?“.
5. **Zustand und „seit“ hängen am Check:** `MonitorState.since` (`models.py:186`) wechselt bei jedem Wechsel des
   gedämpften Status; „seit wann ist diese Platte schlecht“ gibt es nicht. Objekte stecken als Listen in `_details`,
   die UI rechnet Farben teils selbst.
6. **Regeln sind nicht update-fest:** ein Katalog-Update schreibt die Regeln eines Modul-Checks neu und behält nur
   Intervall und Timeout (`apps/monitoring/app/module_sync.py:433`); `Rule`
   (`apps/monitoring/app/catalog/model.py:140`) hat keinen Schlüssel, an dem eine eigene Änderung hängen könnte.

Fehler, die die Analyse nebenbei fand, hängen nicht an der Neuordnung und sind eigene Roadmap-Zeilen (R-1564 …
R-1574).

## 2. Zielmodell

Fünf Begriffe ersetzen die gewachsenen Mechanismen:

| Begriff | Was es ist | Wer es hält |
|---|---|---|
| **Objekt** | Das Ding, das der Admin meint (Platte, Pool, Container, Dienst, Zertifikat …), mit stabilem Schlüssel (§4), Art, Name, Status, Grund im Klartext, Werten und „seit“ | Monitoring; jeder Check liefert ein einheitliches Ergebnis mit `objects[]` |
| **Regel** | Feld, Vergleich, Wert, Stufe; editierbar, einzeln schaltbar, update-fest (§6) | Katalog bzw. Vorlage, darüber die Overrides des Admins |
| **Ausnahme** | Geltung × Wirkung × Dauer, mit Grund, wer, wann (§7) | Monitoring; „nur für mich“ im Hub |
| **Problem** | Entsteht, wenn ein Objekt schlecht wird; seit, Verlauf, bestätigt, Notiz, behoben (§8) | Lebenszyklus im Monitoring, Bestätigen und Routen im Hub (Frage 1) |
| **Abdeckung** | Was je Server überwacht, gefunden und nicht überwacht oder ausgeblendet ist (§9) | Monitoring |

Invarianten:

- Die Oberfläche bewertet nie selbst. Sie zeigt den Status, den der Server je Objekt liefert.
- Benachrichtigt wird nur über Probleme, auf einem Weg (Hub-Matrix der Person plus Routen).
- Lastabwurf auf dem Host bleibt (er schützt den Dienst); ein nicht gemessenes Objekt heißt „nicht gemessen“ und wird
  nie „unbekannt“ oder ein Problem.

## 3. Darstellungs-Grammatik

Jede Objektart folgt derselben Grammatik; die Mockups zeigen sie für jede Art:

- **Ebene 1, Hauptzustand:** ein Status-Badge, ein Satz Grund im Klartext, „seit“.
- **Ebene 2, Kennzahlen:** höchstens vier Werte, jeder mit seiner Schwelle („41 °C (Warnung ab 55)“).
- **Ebene 3, Schublade:** alle Attribute, Verlauf, Regeln und Schwellen, Ausnahmen, Rohdaten.
- **Identitätszeile:** Name, Modell oder Typ, Ort (Server, Pfad, Pool).
- **Reihenfolge:** schlechteste zuerst; Ausgeblendetes grau am Ende, mit Grund.

Statusrang, schlechtester zuerst: kritisch > Warnung > unbekannt > veraltet > Info > nicht erhoben > OK. „Unbekannt“
steht über Info, damit ein Hinweis eine Regel ohne Wert nicht verdeckt (wie heute
`apps/monitoring/app/checkers/probe.py:194`). „Veraltet“ und „nicht erhoben“ sind neu: der eine sagt, dass Daten zu
alt sind, der andere, dass sie gewollt nicht erhoben werden (Ausnahme „nicht prüfen“, Lastabwurf, eine VM ohne SMART).

## 4. Objekte und stabile Schlüssel

Ein Schlüssel trägt alles, was am Objekt hängt: Zustand und „seit“, Ausnahmen, Overrides, Problem, Messreihe. Er
überlebt Neustart, Umbenennung des Geräts und Neuanlage des Containers. Form: `<server>/<art>/<id>`; zentrale
Objekte ohne Server (`certificate/…`, `domain/…`, `endpoint/…`), Backup-Objekte je Cluster.

| Objektart | Quelle heute | Schlüssel | Rückfall | Lücke, Instabilität |
|---|---|---|---|---|
| `disk` | `smart_health` | WWN | Modell + Seriennummer; sonst Host + Gerät, **als instabil markiert** | `/dev/sdX` ist nur Ort; Seriennummer und WWN fehlen in `_details` (Agent) |
| `pool` | `zfs_health` | Host + Poolname | — | später Pool-GUID (`zpool -p`, Agent) |
| `guest-backup` | `proxmox_backup` | Cluster + VMID | Einzel-Node ist ein eigener Cluster | Cluster-ID fehlt im Report (R-0519); bis dahin Tag als Ersatz (Frage 10) |
| `backup-job` | `proxmox_backup` | Cluster + Job-ID | — | wie oben |
| `container` | `docker_health` | Host + Compose-Projekt/Dienst/Nummer | Host + Containername | Container-ID ist nur Merkmal; Compose-Nummer fehlt (Agent) |
| `compose-project` | `docker_health` | Host + Projekt | — | bewertet sich als sein schlechtester nicht ausgeblendeter Container |
| `host` | `agent_ping` | Server | — | — |
| `cpu`, `memory` | `agent_resources` | Server + Art | — | — |
| `mount` | `agent_resources` | Server + Pfad (case-sensitiv, Windows-Laufwerk groß) | — | doppelte Mountpoints und Bind-Mounts brauchen Gerät oder Dateisystem-ID (Agent) |
| `sensor` | `agent_resources` | Server + Chip/Label | — | zwei NVMe heißen gleich: Gerätepfad nötig (Agent); NVMe- und drivetemp-Sensoren gehören zur Platte |
| `reboot`, `updates`, `clock` | `system_state` | Server + Art | — | Updates aus `system_state`, `windows-host` und `proxmox-ve` werden ein Objekt `updates` |
| `service` | `service_process` | Server + voller Unit-Name (Alias aufgelöst) | Windows: `SERVICE_NAME` kleingeschrieben; FreeBSD: rc-Name | Windows-Starttyp fehlt (Agent) |
| `certificate` | `central` (tls) und Module | SHA-256-Fingerprint | `host:port` | alle Quellen werden ein Objekt mit einer Bewertung (Frage 6) |
| `domain` | `central` (rdap, dns, mail_dns, dnsbl), Module | Domainname | — | — |
| `endpoint` | `ping`, `tcp`, `http` | Ziel (URL bzw. `host:port`) | — | — |
| Modul-Instanz | `probe` | Server + `module/<modul>/<instanz>` | Platzhalter Modul-ID | benannte Unterobjekte `<instanz>/<name>` nur nach Frage 7 |

`disk_forecast` wird kein eigenes Objekt, sondern Kennzahl und Regel am `mount`.

## 5. Objektzustand, Statuswechsel-Log, Problem-Schlüssel

- **`monitor_object_state`** (P1): Primärschlüssel `check_id` (FK, `ON DELETE CASCADE`) + `object_key` (≤ 200
  Zeichen); `kind`, `name`, `status`, `reason`, `since` (letzter Statuswechsel), `bad_since` (seit wann nicht ok,
  über Wechsel zwischen Warnung und kritisch hinweg), `gone_at`. Geschrieben wird nur bei Änderung (§12.4);
  Messwerte bleiben in VictoriaMetrics und `_details`. Verschwundene Objekte bleiben N Tage. `since` kommt vom Host,
  wo er es liefert (systemd).
- **Statuswechsel-Log zuerst:** die Verlaufsmarken lesen heute `MonitorAlertLog`
  (`apps/monitoring/app/history.py:234`), das nur entsteht, wenn eine Alarmregel sendet. Ein eigenes Log je
  Objektwechsel (90 Tage) trennt Verlauf von Benachrichtigung.
- **Problem-Schlüssel:** heute `check:<id>` (`apps/monitoring/app/alerter.py:556`), künftig
  `obj:<check_id>:<hash des Objektschlüssels>`, damit er in `IncidentKey` (≤ 200,
  `apps/server/app/modules/notifications/schemas.py:72`) passt. Beim Umschalten schließt die Migration offene
  `check:`-Vorfälle.
- **VictoriaMetrics** bekommt weiter den Rohstatus, der Objektzustand den gedämpften. Reihen tragen den Schlüssel
  als Label; eine Reihe nach Gerätename endet mit der Migration (§10).

## 6. Regelmodell

### 6.1 Form

Eine Regel ist `field`, `op`, `value`, `level` (`info`, `warning`, `critical`), dazu optional:

- `key`: stabiler Schlüssel. Ohne ihn gilt der abgeleitete Schlüssel `<field>.<level>`. Im heutigen Katalog ist er in
  jedem der 366 Checks eindeutig; das Feld allein kollidiert in 43 Checks, weil sie ein Feld mit Warnung und
  kritisch bewerten. Ein Katalog ohne `key` bleibt gültig, die Definitions-Hashes aller Module bleiben gleich
  (`test_every_catalog_rule_dumps_as_the_catalog_hashes_it`), kein Check bekommt deshalb ein Update angeboten.
- `clear`: Hysterese. Eine feuernde Regel hält, bis der Wert die Entwarnungsgrenze passiert.
- `when`: Bedingung (§6.4). `unless` (heute einmal im Katalog, Defender) bleibt als Feld, damit der Hash stabil
  bleibt; es ist einem `when` mit `ne` auf das eigene Ergebnis gleichwertig.
- `if_absent`: was ein fehlender Wert bedeutet (heute schon im Katalog).

Operatoren: die zehn heutigen (`eq`, `ne`, `in`, `lt`, `le`, `gt`, `ge`, `max_age`, `delta_gt`, `drop_pct_gt`;
`apps/monitoring/app/checkers/probe.py:125`) plus `rises`: der Wert ist größer als im Lauf davor **desselben
Objekts**; ein Fall (Zähler zurückgesetzt) ist kein Anstieg, ohne Lauf davor ist nichts gestiegen. Ein Gleichlauf-Test
bewertet jeden Katalog-Check mit Prototyp und heutigem `_rate` (über 1000 Bewertungen) und findet keinen Unterschied.

`rule_problems` prüft einen Regelsatz vor dem Speichern: Schlüssel doppelt, Operator unbekannt, Entwarnung auf der
falschen Seite der Grenze, Bedingung mit unbekanntem Operator oder unbekanntem Check.

### 6.2 Overrides und Drei-Wege-Merge

Die Änderung des Admins ist eine eigene Schicht je Regelschlüssel (`value`, `clear`, `level`, `enabled`); der
Katalog-Regelsatz bleibt unverändert und behält seinen Hash. Bewertet wird mit `effective(katalog, overrides)`. Der
Regelschlüssel ist dort eingefroren, damit ein Stufen-Override die Regel nicht umbenennt.

Ein Katalog-Update ist ein Drei-Wege-Merge aus altem Katalog, neuem Katalog und Overrides:

| Lage | Ergebnis | Meldung an den Admin |
|---|---|---|
| Katalog ließ den Teil unverändert | Wert des Admins bleibt | — |
| Katalog zog auf den Wert des Admins nach | Override entfällt | — |
| Beide änderten denselben Teil | Wert des Admins bleibt | `both_changed` |
| Katalog entfernte die Regel | Override entfällt | `removed` |
| Regel bewertet ein anderes Feld oder mit anderem Operator | Grenzen des Admins entfallen, Stufe und Schalter bleiben | `redefined` |
| Grenze wanderte über die Entwarnung | Entwarnung entfällt, die Regel bewertet ohne sie | `clear_dropped` |

Ändert der Katalog die Stufe einer Regel ohne `key`, ist sie eine neue Regel: der Override endet als `removed` und
die Katalogwerte gelten. Die Richtung ist Melden. Wer Stufen verschieben will, gibt der Regel einen `key`.

### 6.3 Was Regel wird und was Code bleibt

Der Differenzial-Test (`test_rule_model_differential.py`) bildet die SMART-Kaskade, die ZFS-Zustände und die
Docker-Bewertung als Regelsätze nach und fährt 118 Fälle gegen die echten Checker. Jede Familie zerfällt in einen
**Sensor**, der Werte ohne Grenze liest, und einen **Regelsatz**, der jede Grenze und Stufe trägt. Szenarien tragen nur
Urteile, die `docs/` festschreibt oder, wo die Doku schweigt, der Test des Checkers. Eine Gegenprobe mit zwei
verschobenen Schwellen macht drei Fälle rot.

Code bleibt, im Sensor:

- Typprüfung und Zahlen lesen (`agent_number`, ganze Zahlen);
- die Plattenart aus Protokoll und Rotation;
- **Bitfelder** (smartctl-Exit-Status, NVMe `critical_warning`) dekodiert zu einzelnen Wahrheitswerten. Eine Grenze
  auf den rohen smartctl-Status bewertete Bit 0x20 („Schwelle in der Vergangenheit überschritten“) kritisch, obwohl
  der Checker es ausdrücklich nur meldet;
- Exit-Code und Health aus dem Text von `docker ps`;
- der Wert des letzten Laufs je Objekt (für `rises`), künftig aus dem Objektzustand;
- Zeitpunkte parsen (Scrub-Ende) und Größen ableiten (Pool-Belegung).

Regel wird alles andere: Grenzen, Stufen, Zustandslisten, Altersgrenzen, Zähler, Abhängigkeiten zwischen Feldern
derselben Messung.

Abweichungen (der Test hält die vier Docker- und ZFS-Fälle als benannte Abweichungen fest, den SAS-Fall fand die
Prüfung des Tests; P1 behebt alle im Regelmodell):

| Fall | Checker | Regelsatz | Fehlt im Regelmodell |
|---|---|---|---|
| Container beendet mit Exit 143/137 ohne OOM, Policy `no` | ok (gestoppt) | kritisch | `not in` (`exit_code not in [0, 137, 143]`) |
| Container beendet mit Exit 1, Policy `unless-stopped` | ok | kritisch | `unless` mit mehreren Werten bzw. `when … not in` |
| Unbekannter Container-Zustand (`migrating`) | Warnung | ok | `not in` über die bekannten Zustände |
| Plattenart außer HDD, SATA-SSD, NVMe (etwa SAS) | HDD-Grenzen (`apps/monitoring/app/checkers/smart.py:254`) | ok | Rückfall-Regel mit `kind not in […]` |
| Letzter Scrub vor genau 35 Tagen | Warnung (ganze Tage, `>=`) | ok (`max_age` zählt Sekunden strikt) | Sensor liefert das Alter in ganzen Tagen, Regel `ge 35` |

Drei der fünf Fälle fallen heute im Regelsatz in Richtung Schweigen; P1 braucht deshalb vor der Umstellung
eingebauter Checks den Operator `not in` und ein `unless` mit Liste. Empfehlung für das Alter: der Sensor liefert
ganze Tage, weil auch die Anzeige Tage zeigt („letzter Scrub vor 36 Tagen (Warnung ab 35)“); ein Operator mit
Einheit wäre eine zweite Art, dasselbe zu sagen.

Der Test bildet die Checker von `origin/main@3aa2499f1` ab. R-1568 und R-1570 (PR #568) ändern die Bewertung:
abwesendes SMART wird Info bzw. unbekannt, ein fehlender `smart_passed` unbekannt statt kritisch; ZFS bewertet
`SUSPENDED` und `REMOVED` und liest die Scrub-Grenzen aus der Config. Mit dem Merge zieht der Test nach (Sensor ohne
Vorgabe für `smart_passed`, Regel ohne `if_absent`); die Schlüsse dieses Abschnitts bleiben.

### 6.4 Bedingungen (R-1515)

Eine Bedingung `Condition(field, op, value, check?, object?, max_age?)` vergleicht einen gemessenen Wert mit einem
Vergleichsoperator (`eq`, `ne`, `in`, `lt`, `le`, `gt`, `ge`); sie hat keinen Lauf davor und kein eigenes Alter, außer
`max_age` für die Frische des gelesenen Werts. Zwei Formen, gleich gebaut, verschieden weit:

- **`when` an einer Regel** (Katalog): liest unter derselben Modul-Instanz, aus dem eigenen Ergebnis (`check` leer)
  oder aus einem anderen Check des Moduls, optional aus einem Objekt darunter. Sie nennt nie eine Instanz: aufgelöst
  wird immer in der Instanz, an die der Check gebunden ist, denn ein Katalog-Modul kennt nur seine eigenen Checks.
  Die Regel bewertet, solange die Bedingung nicht bekannt falsch ist; fehlt der Wert oder ist er zu alt, bewertet
  sie.
- **Bedingung an einer Ausnahme** (Admin): liest ein beliebiges Objekt desselben Servers (Objekt, Feld = Zustand
  oder Kennzahl, Wert), weil der Admin die Zusammenhänge seiner Installation kennt. Die Ausnahme gilt nur, solange
  die Bedingung bekannt wahr ist; sonst ruht sie und das Objekt wird normal bewertet.

Beide Formen fallen bei fehlenden Daten in Richtung Melden.

**Empfehlung zu R-1515** (Anlass: der HTTP-Check von Nextcloud AIO schlägt im Backup-Fenster fehl): beide Formen
bauen. R-1515 selbst wird ein `when` im Katalog-Modul, weil die Abhängigkeit eine Eigenschaft des Moduls ist und jeder
Nutzer sie ohne Einrichtung bekommen soll. Das Modul `nextcloud-aio` lässt `status.php` heute aus, weil eine Regel
kein Feld eines anderen Checks lesen kann (`apps/monitoring/app/catalog/modules/nextcloud_aio.py:23`); sein Check
`aio` meldet das laufende Backup schon (Feld `backup`), also bekommt ein neuer `status.php`-Check eine Regel mit
`when` auf dieses Feld. Die Schublade nennt die ruhende Regel mit ihrer Bedingung. Abhängigkeiten,
die nur eine Installation kennt, drückt der Admin als Ausnahme mit Bedingung aus; sie steht in der Liste
„Ausgeblendet“ mit Grund, wer und wann. Die Spec empfahl zuerst nur die Ausnahme-Form; der Prototyp zeigt, dass `when`
das heutige `unless` verallgemeinert und deshalb im Katalog kaum Neues braucht. Kevin hat am 2026-11-18 so
entschieden (§14, Frage 11).

### 6.5 Wertgebundene Ausnahme

Eine Ausnahme kann an einen Wert gebunden sein („8 umgelagerte Sektoren akzeptiert“). Ändert sich der Wert, endet
sie endgültig (`ended_at`), auch wenn der Wert später zurückkehrt; sie endet auch, wenn der Wert fehlt (eine
schlafende Platte liefert keinen). Der Admin bestätigt dann neu. Das unterscheidet sie bewusst von der Bedingung, die
bei fehlenden Daten nur ruht: eine wertgebundene Ausnahme ist eine Zusage über genau diesen Wert, und eine Lücke in
den Daten darf sie nicht unbemerkt verlängern.

## 7. Ausnahmen

- **Geltung:** Objekt, Regel, Check, Check-Typ, Server, Tag, Cluster. Greifen mehrere, gewinnt die engste
  (Objekt > Regel > Check > Check-Typ > Server > Tag > Cluster), damit der Admin am Objekt genau einen Grund liest.
- **Wirkung:** nicht prüfen (das Objekt ist „nicht erhoben“) · prüfen, nicht bewerten (grau) · bewerten, nicht melden
  · nur für mich still (bleibt im Hub gespeichert).
- **Dauer:** dauerhaft · bis Zeitpunkt · wiederkehrendes Fenster mit Zeitzone.
- **Spur:** Grund optional, wer und wann immer, nur Admins, Rückfrage vor dem Speichern, Audit. Liste
  „Ausgeblendet“ mit allen Ausnahmen; zur Prüfung vorgelegt werden migrierte, dauerhafte älter als 90 Tage und
  solche ohne Objekt.
- **Ende:** das Ende einer Ausnahme meldet den aktuellen Zustand nach (Frage 9).
- Eine Ausnahme mit Geltung „Regel“ nimmt nur diese Regel aus der Bewertung; „nicht prüfen“ gibt es dafür nicht,
  weil ein Check ganz oder gar nicht läuft.

## 8. Problem und Benachrichtigung

- **Problem-Lebenszyklus im Monitoring** (öffnen, „seit“, schließen, Flattern, Dauer-unknown, Abhängigkeit vom Host:
  „Host down“ unterdrückt Folgemeldungen). Bestätigen, Notiz und Routen bleiben im Hub; Schlüssel 1:1 (§5, Frage 1).
- **Ein Weg:** Alarmregeln werden Routen im Hub (Frage 3). Vor dem Umschalten zeigt ein Diff-Bericht je
  bestehendem Nutzer, was sich ändert: Stufenvergleich heute Gleichheit, im Hub „mindestens“; Info-Checks, die der
  Hub heute verwirft (`apps/monitoring/app/alerter.py:600`), bekommen eine Ereignisklasse „Hinweis“, sonst gingen
  Meldungen still verloren; der Cooldown je Regel entfällt; feste Empfänger brauchen ein Routenziel „Team“; SMTP je
  Regel entfällt (Kanäle im Admin-Panel, R-1531); der Betreff ändert sich; Ruhezeit und Digest gelten neu.
- **Kompatibel bleiben:** `/alerts` als Fassade für alte Desktops, das alte Webhook-Format als Kanal-Option,
  `alert.triggered` unverändert, `MonitorAlertLog` bis das Statuswechsel-Log es ersetzt.

## 9. Abdeckung

- **Profile** (heute Vorlagen) hängen an Tags, je Profil eine Fund-Politik: vorschlagen (Standard) oder still
  übernehmen (Frage 4). Neue Funde meldet die Ereignisklasse „Hinweis“ (R-1543).
- **Je Server** zeigt die Abdeckung: überwacht, gefunden und nicht überwacht, ausgeblendet (mit Grund),
  ausgeschlossen. Grundlage sind Checks, Funde, Tombstones (`MonitorCheckTombstone`, `MonitorModuleTombstone`,
  `models.py:377`, `:398`) und Ausnahmen.
- „Verschwunden“ gilt weiter erst nach zwei vollen Scans; ein Tag-Wechsel, der heute ohne Tombstone löscht, legt
  künftig einen an.

## 10. Migrationsplan

| Heute | Ziel | Phase | Rückweg |
|---|---|---|---|
| `enabled` als Schalter des Nutzers | Ausnahme „nicht prüfen“, Geltung Check, dauerhaft; die Spalte bleibt für das System | P1 | Spalte unverändert, alte Desktops schalten weiter |
| `silent` (Katalog-Sync) | Abdeckungszustand „neu, still“: bewerten, nicht melden | P4 | Spalte bleibt bis P4 |
| Ignorierlisten (`ignore_mounts`, `ignore` der Dienste, `ignore_devices`, `exclude_vmids`, `ignore_containers`) | Objekt-Ausnahme „prüfen, nicht bewerten“, dauerhaft, Marke „migriert“ | P1 | die Config-Felder bleiben; alte Desktops schreiben sie weiter, der Server übersetzt |
| `exclude_stopped`, `alert_on_unavailable`, `disk_overrides`, `temp_overrides`, `unless`, `if_absent` | Regeln bzw. Overrides, keine Ausnahme | P1 | wie oben |
| Wartungsfenster (`MonitorMaintenance`, ohne „wer“) | Ausnahme Server/alle „nicht melden“, bis oder wiederkehrend mit Zeitzone | P1 | `/maintenance` bleibt; der Server übersetzt |
| Server-Mute und Vorfall-Mute je Person (Hub) | Ausnahme „nur für mich“; bleibt im Hub gespeichert, die Liste führt beides zusammen | P2 | unverändert gespeichert |
| Alarmregeln (`MonitorAlertRule`) | Routen im Hub, nach Diff-Bericht | P3 | alte Regeln werden nur deaktiviert, bis die Migration abgeschlossen ist |
| Template- und Modul-Tombstones | Abdeckung „ausgeschlossen“ | P4 | Tabellen bleiben |
| Abgelehnte Vorschläge und Funde (`MonitorTemplateSuggestionDismissal`, `models.py:551`) | Abdeckungs-Entscheidung | P4 | Tabelle bleibt |
| Messreihen und Zustände nach Gerätename oder Container-ID | Reihe je stabilem Schlüssel; alte Reihen bleiben lesbar bis zur Aufbewahrungsgrenze | P1 | alte Reihen unverändert |

Migrationsgefahren:

- Ignorieren markiert heute das ganze Feld `config` als überschrieben; Vorlagen-Schwellen kommen danach nie mehr an.
  Die Migration trennt Ignorierliste und Schwellen.
- Alte Einträge haben kein „wer“, „wann“ oder Grund: sie erscheinen als „unbekannt (migriert)“ und stehen zur
  Prüfung.
- Unassign und Tag-Entzug löschen heute Checks, Zustände und Tombstones; die Migration darf daraus keine Ausnahmen
  ableiten, die es nicht gab.
- Instabile Schlüssel (SMART nach Gerätepfad, Docker nach Container-ID) migrieren nur über den Rückfall und tragen die
  Marke „instabil“, bis der Agent die Lücke schließt (§11).

Mechanik:

- Zwei Datenbanken (Monitoring und Server) teilen keine Transaktion: jede Migration ist idempotent je Quelleintrag,
  Alt-Daten werden erst nach dem Abschluss entfernt. Geheimnisse, die zwischen den Datenbanken wandern
  (SMTP-Zugang einer Alarmregel), prüft der `security`-Prüfer.
- API-Erweiterungen nur additiv; `MonitorCheckOut` und `MonitorStateOut` bleiben; neue Präfixe kommen in die
  Freigabeliste des Proxys.
- Rückweg nach einer Migration nur über `restore.sh`; deshalb fährt jede Migration zuerst trocken und legt den
  Diff-Bericht vor (Abnahme P1: Migration an einer Kopie echter Daten, mit Rückweg).
- Reihenfolge: Statuswechsel-Log → Objektergebnis und `monitor_object_state` → Ausnahme-Modell mit Migration der
  Ignorierlisten, von `enabled` und der Wartung (P1) → Bedienung (P2) → Probleme und Routen (P3) → Abdeckung (P4).

## 11. Datenlücken im Agent und Leistung

Der Agent liefert heute nicht, was stabile Schlüssel und die Ebene-2-Kennzahlen brauchen. Jede Lücke ist eine
Allowlist-Änderung; alte Agents bleiben lesbar (fehlendes Feld = Rückfall-Schlüssel bzw. „neue Agent-Daten“ in der
Ansicht):

- Platten: Seriennummer und WWN in `_details`, SSD-Verschleiß, SAS-Pfad, `smartctl -n standby` (R-1569);
- ZFS: `zpool -p`, Pool-GUID, vdev-Zustände;
- Docker: `finished_at`, Compose-Nummer;
- Proxmox: Cluster-ID (R-0519), `last_backup_ts` in `_details`;
- Host: Gerätepfad der Sensoren, Gerät des Mounts, Windows-Starttyp und Zeitsynchronisation (R-1583), Alter der
  Paketlisten, „Neustart nötig seit“, Version des Agents (R-0702).

Leistung: alles Neue rechnet der Server aus vorhandenen Reports; auf dem Host entsteht keine Zusatzlast. „Nicht
prüfen“ spart Host-Arbeit nur bei Probes, eingebaute Collector laufen unabhängig. SMART ohne `-n standby` weckt
vermutlich schlafende HDDs (nicht verifiziert, R-1569, Messweg §12.7).

## 12. Experimente

Lokal auf der Entwicklungsmaschine, 2026-11-18: Proben auf pytest-Ebene gegen den Code dieses Branches (Wegwerfdatei,
nicht im Baum), Postgres 17.11 (Test-Datenbank, eigenes Wegwerf-Schema), VictoriaMetrics v1.155.0 (die Version aus
`docker-compose.yml`) als Wegwerf-Container, Docker Compose v5.6.1. Die Zahlen sind Größenordnungen eines Laufs auf
einer Maschine, keine Lastmessung.

### 12.1 Hub-Fehler beim Melden

- **Verfahren:** ein Check kritisch, zuletzt `ok` gemeldet; der erste Hub-POST scheitert mit einem
  Verbindungsfehler; `dispatch_alert_bg` mit echten Sessions (SQLite), danach die nächste Bewertung und eine
  Erholung.
- **Messwert:** nach dem Fehlschlag steht `notified_status` auf `critical`, `hub_status` und `hub_sent_at` sind leer
  (`_release_hub_slot`, `apps/monitoring/app/alerter.py:345`, gibt nur den Glocken-Platz zurück). Die nächste
  Bewertung entscheidet `skip`. Die Erholung entscheidet `notify`, an den Hub geht trotzdem nichts, weil kein Platz
  offen ist. Hub-POSTs insgesamt: einer, der gescheiterte.
- **Folgerung:** Ein Hub-Ausfall verliert den Alarm ganz, er kommt nicht verspätet (R-1572, dort mit rotem Test
  belegt). P3 trennt deshalb „Problem offen“ von „an den Hub übergeben“: eine Outbox im Monitoring wiederholt bis zur
  Quittung des Hubs (§8).

### 12.2 Deaktivieren eines kritischen Checks

- **Verfahren:** zwei Checks über den TestClient der App, einer kritisch mit offenem Hub-Platz, einer ok;
  `POST /checks/{id}/toggle`, Wiedereinschalten, `DELETE /checks/{id}`; Hub-POSTs gezählt, `GET /status/summary`
  vorher und nachher.
- **Messwert:** die Summary zählt vorher und nachher `critical: 1`, also den abgeschalteten Check weiter. Abschalten,
  Wiedereinschalten und Löschen senden keinen Hub-POST. Der Zustand bleibt eingefroren auf
  `critical`/`critical`/`critical` (Status, gemeldet, Hub).
- **Folgerung:** R-1566 (`apps/monitoring/app/routers/checks.py:782`, in PR #568) und R-1571
  (`checks.py:529`) sind bestätigt. Im Zielmodell ist Abschalten die Ausnahme „nicht prüfen“ (§7). Sie schließt das
  offene Problem mit dem Grund „ausgenommen“, und das Objekt zeigt „nicht erhoben“ statt des eingefrorenen Status
  (§3). Nach ihrem Ende entscheidet die nächste Bewertung (Frage 9), nicht der alte Zustand.

### 12.3 Monitoring 20 Minuten gestoppt (`agent_ping`)

- **Verfahren:** fünf Server, letzter Report 20 Minuten vor dem Neustart, beim Start aus `monitor_agent_liveness`
  geladen (`hydrate_agent_liveness`, `apps/monitoring/app/checkers/agent.py:161`). Die Uhr ist gesteuert. Vier
  Agents pushen in den ersten vier Minuten, einer zwei Sekunden nach dem ersten Lauf. `AgentPingChecker` mit der
  Standardvorlage (`stale_minutes` 15).
- **Messwert:** Der erste Lauf kommt fünf Minuten nach dem Start (`IntervalTrigger` ohne Startzeit,
  `apps/monitoring/app/scheduler.py:104`). Ein Lauf direkt beim Start hätte alle fünf kritisch gemeldet
  („unreachable for 20 min“). Beim ersten Lauf sind vier ok, der späte ist kritisch („unreachable for 25 min“). Beim
  zweiten Lauf sind alle ok. Aus dem Code abgeleitet, nicht gemessen: mit `consecutive_fails` 1 der Vorlage und
  `_alone_wait` (`apps/monitoring/app/alert_bundle.py:230`, vier Minuten bei `5m`) geht der Einzelalarm etwa eine
  Minute vor der Entwarnung hinaus.
- **Folgerung:** Das Alter des Heartbeats zählt die Stillstandszeit des Monitorings mit (`agent.py:236`). Einen Sturm
  verhindert nur der Abstand von einer Periode bis zum ersten Lauf, und ein Push knapp danach löst einen Fehlalarm
  aus (neue Zeile R-1607). Im Zielmodell zählt das Alter ab dem späteren von letztem Report und Start des
  Monitorings. Ein Objekt, das seit dem Start noch nicht berichten konnte, steht auf „nicht erhoben“ statt auf
  kritisch.

### 12.4 400 Objekt-Upserts je Report

- **Verfahren:** eine Tabelle in der Form von `monitor_object_state` (§5) in einem Wegwerf-Schema. Ein Server mit
  20 Checks zu je 20 Objekten, 60 Reports, je Report wechseln vier Objekte den Status. Drei Varianten:
  - **A:** jeder Report schreibt alle 400 Zeilen per Upsert, samt `last_seen`;
  - **B:** alle 400 Zeilen per `ON CONFLICT … DO UPDATE … WHERE status/reason IS DISTINCT FROM`;
  - **C:** den Bestand lesen und nur die geänderten Zeilen schreiben.

  Die Transaktion bis zum Commit ist die Dauer der Zeilensperren.
- **Messwert:**

  | Variante | Transaktion p50 / p95 / max | Zeilen-Updates (60 Reports) | Tabelle danach |
  |---|---|---|---|
  | A | 33,0 / 51,1 / 127,4 ms | 24 000 (20 170 davon HOT) | 488 KiB |
  | B | 28,6 / 47,0 / 54,7 ms | 240 | 112 KiB |
  | C | 5,0 / 5,8 / 31,5 ms | 240 | 112 KiB |

  Die Sperrprobe nutzt Variante B ohne jede Änderung, offen gehalten. Eine zweite Verbindung mit
  `SELECT … FOR UPDATE NOWAIT` auf eine unveränderte Zeile scheitert am Sperrfehler: das Upsert sperrt auch die Zeilen,
  die sein `WHERE` nicht ändert.
- **Folgerung:** Variante C bestätigt „geschrieben wird nur bei Änderung“ (§5). Den Unterschied bildet die
  Anwendung, und es gibt kein `last_seen` je Objekt: A erzeugt 400 Zeilenversionen je Report, bei 288 Reports am Tag
  rund 115 000 je Server und Tag für den Autovacuum. „Zuletzt gesehen“ trägt der Check (`MonitorState.last_check`),
  „verschwunden“ folgt aus der Differenz zwischen Report und Bestand.

### 12.5 Sammelabruf über 50 Reihen

- **Verfahren:** 50 Reihen `monitor_check_status_value{check_id, server_id}` mit je 10 080 Werten (sieben Tage, einer
  je Minute) über `/api/v1/import/prometheus` (Format laut
  [URL-Beispielen](https://docs.victoriametrics.com/victoriametrics/url-examples/)), danach `/internal/force_flush`
  ([Single-Server-Doku](https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/), dort als
  Test-Hilfe beschrieben). Der Container läuft mit `-search.disableCache`. Verglichen werden 50 Einzelabrufe
  `query_range` mit `check_id="…"` nacheinander und ein Abruf mit `check_id=~"a|b|…"`, je Median aus fünf Läufen,
  lokal ohne Netz dazwischen.
- **Messwert:**
  - 24 Stunden mit Schritt 5 min: 50 Einzelabrufe zusammen 98,7 ms, der Sammelabruf 12,9 ms (50 Reihen, 14 450
    Punkte);
  - sieben Tage mit Schritt 1 h: 106,7 ms gegen 12,9 ms (8 450 Punkte);
  - Import der 504 000 Werte: 1,4 s.
- **Folgerung:** Ein Sammelabruf je Ansicht und Metrik ist schon ohne Netz etwa achtmal schneller. Über Desktop,
  Server und Monitoring kommt je Einzelabruf eine Runde dazu (heute bis zu drei `query_range` je Check,
  `GET /checks/{id}/metrics`). Die Objekt-Tabelle (P2) holt ihre Sparklines deshalb mit einem `=~`-Selektor je
  Metrik. Mehr als 50 Reihen in einem Selektor sind nicht gemessen.

### 12.6 Schlüssel bei neu angelegtem Container

- **Verfahren:** ein Compose-Projekt mit einem Dienst. Nach jedem Schritt werden das Label
  `com.docker.compose.container-number`, der Name und die Container-ID gelesen. Die Schritte: Neuanlage
  (`up --force-recreate`), Hochskalieren auf drei, Löschen von Nummer 2 mit erneutem Hochskalieren, Herunterskalieren
  auf eins, `down` mit neuem `up`.
- **Messwert:**
  - Neuanlage: neue IDs, Name und Nummer bleiben (1, 2).
  - Hochskalieren auf drei: Nummer 3 kommt dazu.
  - Nummer 2 gelöscht und wieder auf drei skaliert: der neue Container bekommt Nummer 4, die Lücke bleibt.
  - Herunterskalieren auf eins: Nummer 1 bleibt.
  - `down` und `up`: wieder 1 und 2, mit neuen IDs.
- **Folgerung:** Der Schlüssel aus Host, Projekt, Dienst und Nummer (§4) übersteht Neuanlage und `down`/`up`, die ID
  nicht. Bei einem skalierten Dienst kann ein ersetzter Container eine neue Nummer bekommen. Er gilt dann als neues
  Objekt, und der alte verschwindet nach der Regel für Verschwundenes (§9). Der Agent liest heute Projekt und Dienst
  (`apps/agent/internal/monitor/plugins.go:149`), die Nummer nicht (§11).

### 12.7 `smartctl -n standby` (nicht verifiziert)

- **Quelle:** smartctl(8) aus smartmontools 7.4, die lokale Manpage des Debian-Pakets; die Seite auf
  smartmontools.org verweigerte den automatischen Abruf. Wörtlich zu `-n`: „[ATA, SCSI] Specifies if smartctl should
  exit before performing any checks when the device is in a low-power mode.“ Weiter sagt sie:
  - `standby` überspringt SLEEP und STANDBY;
  - der Standard-Exit ist 2, also Bit 1, derselbe Wert wie „device open failed“; `-n standby,STATUS` setzt einen
    eigenen Wert;
  - ohne `-d` kann die Erkennung des Gerätetyps die Platte trotzdem wecken;
  - `-n` wird ignoriert, wenn die Abfrage des Energiezustands nicht unterstützt wird.
- **Heute:** Der Agent ruft `smartctl --all --json=c` ohne `-n` (`apps/agent/internal/monitor/smart.go:141`). Für
  `/dev/sdX`, die der Scan `scsi` nennt, lässt er `-d` bewusst weg (`:142`). Bei Bit 0 oder 1 verwirft er die Platte
  (`:160`).
- **Folgerung:** P1 empfiehlt `-n standby,<eigener Wert>`, ausgewertet als „schläft, letzter Stand von …“
  (Frage 8). Gibt es eine erste erfolgreiche Abfrage, geht ihr Gerätetyp als `-d` mit, damit die Typ-Erkennung nicht
  weckt (R-1569).
- **Messweg** für eine echte HDD, auf einem Host mit drehender Platte, nicht auf der Entwicklungsmaschine:
  1. `hdparm -y /dev/sdX` schickt die Platte in den Standby;
  2. `hdparm -C /dev/sdX` meldet „standby“;
  3. `smartctl -n standby,7 --all --json=c -d sat /dev/sdX; echo $?` erwartet 7;
  4. `hdparm -C` meldet weiter „standby“;
  5. Gegenprobe ohne `-n`: danach meldet `hdparm -C` „active/idle“.

  Dass `hdparm -C` selbst nicht weckt, ist nicht verifiziert.

## 13. Phasen

| Phase | Zeile | Inhalt | Abnahme |
|---|---|---|---|
| P0 | R-1558 (mit R-1515) | dieses ADR, Mockups, Regel-Prototyp, Experimente (§12), Kevins Entscheidungen | Kevin nimmt Screens und Entscheidungen ab |
| P1 Fundament | R-1559 | Statuswechsel-Log, Objektergebnis und `monitor_object_state`, Ausnahme-Modell mit API und Migration, Status „nicht erhoben“, Regel-Schicht (`key`, Overrides, Merge, `rises`, `clear`, `when`, `not in`), Agent-Datenlücken | Migration an einer Kopie echter Daten mit Rückweg; alte Desktops laufen weiter |
| P2 Eine Bedienung | R-1560 | Objekt-Tabelle, Schublade, Ausnahme-Dialog, neue Server-Seite, Querschnitte, Regel-Editor | Paritätsliste je alter Ansicht, Screenshots echter Zustände |
| P3 Lage und Probleme | R-1561 | Problem-Schicht (Flattern, Dauer-unknown, Host-Abhängigkeit), Routen statt Alarmregeln, Lage-Ansicht, Zeitleiste | Diff-Bericht der Routen; Benachrichtigungen je Woche sinken |
| P4 Abdeckung | R-1562 | Profile an Tags mit Fund-Politik, Hinweis bei neuen Funden, Massen-Aktionen, Abdeckungsansicht | „Ist alles überwacht?“ je Server beantwortet |
| P5 Feinschliff | R-1563 | Befehlspalette, gespeicherte Ansichten, Sparklines | — |

Leitplanken: jede Phase ist für sich auslieferbar und besser als vorher; eine alte Ansicht fällt erst, wenn die neue
alles kann; Verhalten und Migration entscheidet Kevin je Phase. Messbare Ziele: Benachrichtigungen und Fehlalarme je
Woche, „was ist kaputt und seit wann“ auf einen Blick, Ausblenden mit zwei Klicks und Spur, keine Zusatzlast auf
Hosts.

## 14. Entscheidungen

Die Fragen 1–11 sind entschieden: Kevin hat sie am 2026-11-18 per Rückfrage in der Session beantwortet, jede nach
der Empfehlung. Je Frage stehen die Empfehlung und Kevins Antwort wörtlich (die gewählte Option); die Mockups zeigen
die gewählte Variante. Frage 12 folgt mit der Abnahme.

1. **Wo lebt das Problem?** Lebenszyklus im Monitoring; Bestätigen, Notiz und Routen im Hub; Schlüssel 1:1.
   Kevin 2026-11-18: „Monitoring + Hub (Empfohlen)“.
2. **Ein Ausnahme-Modell** ersetzt `enabled` als Nutzerschalter, Ignorierlisten, Wartungsfenster und Mutes, mit
   Migration (§10). Empfehlung: ja. Kevin 2026-11-18: „Ja, mit Migration (Empfohlen)“.
3. **Alarmregeln werden Routen im Hub**, mit Diff-Bericht, `/alerts`-Fassade und Kanal „altes Webhook-Format“.
   Empfehlung: ja. Kevin 2026-11-18: „Ja, Routen im Hub (Empfohlen)“.
4. **Fund-Politik je Profil:** vorschlagen (Standard) oder still übernehmen. Empfehlung: ja. Kevin 2026-11-18:
   „Je Profil wählbar (Empfohlen)“.
5. **Standard-Schwellen** CPU/RAM/Disk: die Vorlagen-Werte (CPU 90/95, RAM 90/98, Disk 80/90), weil sie heute auf den
   Servern aktiv sind; Checker, Schema und Doku ziehen nach. Kevin 2026-11-18: „Vorlagen-Werte (Empfohlen)“.
6. **Zertifikatsfristen** mit einer Bewertung für alle Quellen: relativ zur Laufzeit (25 %/10 %) mit absoluter
   Untergrenze. Kevin 2026-11-18: „Relativ + Untergrenze (Empfohlen)“.
7. **Unterobjekte mit Namen** (einzelne Datenbanken, Backup-Clients, Zertifikat je vhost) gegen „kein Name verlässt
   den Agent“: Entscheidung je Familie. Kevin 2026-11-18: „Je Familie entscheiden (Empfohlen)“.
8. **SMART weckt schlafende Platten nicht** (`-n standby`), Anzeige „schläft, letzter Stand von …“. Empfehlung: ja.
   Kevin 2026-11-18: „Ja, nicht wecken (Empfohlen)“.
9. **Ende einer Ausnahme meldet nach.** Empfehlung: ja. Kevin 2026-11-18: „Ja, nachmelden (Empfohlen)“.
10. **Cluster-Geltung:** bis der Report die Cluster-ID liefert, gilt ein Tag als Ersatz. Empfehlung: ja.
    Kevin 2026-11-18: „Ja, Tag als Ersatz (Empfohlen)“.
11. **R-1515:** beide Formen der Bedingung (§6.4), R-1515 selbst als `when` im Katalog-Modul `nextcloud-aio`.
    Kevin 2026-11-18: „Beide, R-1515 als when (Empfohlen)“.
12. **Abnahme der Screens** (Lage, Server, Objekte, Querschnitte, Abdeckung, Ausnahme-Dialog, Schublade, jede
    Objektart).

## 15. Bewusst nicht (YAGNI)

- Keine Außen- und keine LAN-Sonde: der Agent prüft nur Loopback, eigene Adressen und eigene Container; Öffentliches
  prüft der Server.
- Keine Fernaktionen in der Schublade (R-1083): sie bietet nur, was es gibt (jetzt prüfen, Ausnahme, Wartung,
  Verbinden).
- Keine zweite Bewertung in der Oberfläche, kein Operator mit Zeiteinheit (§6.3); keine Regel-Bedingung über die
  eigene Instanz und keine Bedingung über den eigenen Server hinaus (§6.4).
- Kein Umbau des Katalogs: Regeln ohne `key` bleiben gültig, Hashes bleiben gleich (§6.1).
