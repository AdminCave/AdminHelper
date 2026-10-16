<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Linux-Dienste richtig zählen und melden — Spec

Roadmap: R-0418 (BUG). Entscheidungen: Kevin, 2026-10-16 (additive Report-Felder freigegeben).
Stand: `origin/main@af4498a7`. Ledger: `tasks/monitoring-services.md`.

## Problem / Motivation

Der Check `service_process` (Template „Linux Server — Standard“, `apps/monitoring/app/builtin_templates.py:102-111`,
Modus `auto`) und seine Anzeige im Desktop liefern auf einer frischen Installation falsche Ergebnisse. Belegt im Lab
(Ubuntu 24.04, systemd 255) und auf einer Debian-13-Box (systemd 257):

1. **Falsche Zählung im Desktop.** `SecServices.svelte:44` liest `d.active_count`; kein Backend erzeugt das Feld
   (`apps/monitoring/app/checkers/agent.py:423-427` schreibt nur `mode`, `failed`, `enabled_inactive`). Die Anzeige
   lautet deshalb „Alle 0 OK“ bzw. „0/N laufen“, wobei N nur die Zahl der Probleme ist. Ohne Details zeigt die Zeile
   eine rote Pille „0 Probleme“ (`SecServices.svelte:35`).
2. **Dauerwarnung auf jedem frischen Host.** Die Regel „enabled und inactive“ (`services_linux.go:68-73`,
   `checkers/agent.py:401-405`) meldet regulär beendete oneshot-Dienste (`RemainAfterExit=` ist standardmäßig `no`,
   systemd.service(5)), per Condition übersprungene Units und per Timer/Socket gestartete Dienste. Lab: 17 Units auf
   einer sauberen Ubuntu-Box (`e2scrub_reap`, `grub-common`, `pollinate`, …), Status dauerhaft `warning`.
3. **Zwei Quellen für dieselbe Liste.** Bei vollem Inventar (`all_services`) berechnet der Server `enabled_inactive`
   selbst (`checkers/agent.py:394-405`, gekappt auf 500 Einträge in zufälliger Reihenfolge, weil die Agent-Liste aus
   einer Map-Iteration kommt, `services_linux.go:52`); bei gedrosseltem Push (`inventory.go:84-104`) nimmt er die
   Agent-Liste. Große Hosts wechseln dadurch zwischen zwei Ergebnissen.
4. **Listen-Modus funktioniert nach normaler Provisionierung nicht.** Die Überwachungsliste des Agents kommt nur aus
   `monitor init --services`; die Provisionierung übergibt keine. Ohne sie fehlt `report["services"]`
   (`report.go:52-59`), und `_evaluate_list` (`checkers/agent.py:444-478`) wertet jeden in der UI eingetragenen
   Dienst als down → `critical`. Aliase (`sshd` → `ssh.service`, der UI-Platzhalter lautet `"sshd, nginx"`,
   `CheckConfigFields.svelte:287`) und Template-Namen (`getty@.service` lässt `systemctl show` mit Exit 1 abbrechen,
   `services_linux.go:117-124`) verschärfen das.
5. **Kleinere Fehler:** Punkt (gedämpfter Status, `consecutive_fails`) und Liste (rohe Details) widersprechen sich;
   die Hinweise `failed`/`inactive`/`down` sind fest einkodiert (`SecServices.svelte:41-42,57`); `ignore` kennt nur
   exakte Namen (`checkers/agent.py:364-372`); scheitert `systemctl`, meldet der Check „Alle systemd-Units OK“
   (`services_linux.go:87-91`).

## Ziel & Nicht-Ziele

**Ziele**
- Ein frischer Debian-/Ubuntu-Host steht mit dem Standard-Template auf `ok`, solange keine Unit wirklich fehlt.
- Der Desktop zeigt ehrliche Zahlen: Problemzahl immer; „x/y aktiv“ nur, wenn der Agent Zähler liefert; ohne
  Daten einen neutralen Zustand („Noch keine Daten“) statt einer roten Pille.
- Punkt, Pille und Liste stimmen überein; alle Hinweise sind übersetzt.
- Der Listen-Modus funktioniert ohne `--services` am Agent, mit `.service`-Normalisierung und Aliasen.
- `enabled_inactive` hat genau eine Quelle (der Agent); Ergebnisse sind über volle und gedrosselte Pushes stabil.
- `ignore` versteht Glob-Muster (`drkonqi-coredump-processor@*`).
- Scheitert `systemctl`, ist der Check `unknown` mit Grund statt `ok`.

**Nicht-Ziele (YAGNI)**
- Synchronisation der Check-Konfiguration zum Agent (eigener Kanal): der Server wertet den Listen-Modus selbst aus.
- Sprache der Server-Meldungstexte (`message`, gehen auch in Glocke/Mail/Telegram): bleiben wie sie sind; die
  Desktop-Liste rendert aus `_details`-Codes. Die Übersetzung der Meldungstexte aller Checker wird eine eigene
  Roadmap-Zeile (Kevin 2026-10-16).
- Timer-Units als eigene Kategorie, Windows-Starttyp (`enabled_inactive` bleibt unter Windows leer, `scquery.go:15`).
- Docker/ZFS/SMART (R-0417, R-0419), Templates und Discovery (R-0420).

## Betroffene Komponenten & Dateien

- **Agent** (`apps/agent/internal/monitor`):
  - `services_linux.go` — `collectServiceHealth` (`:14-38`), `assembleServiceHealth` (`:43-83`), Kandidaten
    `enabled_inactive` (`:68-73`), Legacy-Pfad `collectWatchedServices`/`parseWatchedServices` (`:108-161`).
  - `services_windows.go` (`:24-41`) — Zähler aus `parseScQuery`.
  - `services.go` — `ServiceEntry`; neuer reiner Helfer für Zähler (ohne Build-Tag, testbar).
  - `inventory.go` (`:33-41`) — Hash bezieht `alias_of` ein.
  - Tests: `services_linux_test.go`, neu `services_test.go`.
- **Monitoring** (`apps/monitoring/app`):
  - `checkers/agent.py` — `ServiceProcessChecker` (`:341-478`): `_is_ignored` (`:364-372`), `_evaluate_auto`
    (`:374-442`), `_evaluate_list` (`:444-478`).
  - `routers/agent.py` (`:226-238`) — `prev_details` heute nur für `agent_resources`; künftig auch für
    `service_process`.
  - Tests: `apps/monitoring/tests/test_service_process_checker.py`.
- **Desktop-UI**: `apps/desktop/ui/src/components/monitoring/section/SecServices.svelte` (`:33-59`, `:78-108`),
  `apps/desktop/ui/src/lib/api/types.ts` (`MonitorServiceDetails`, `:282-287`),
  `apps/desktop/ui/src/lib/i18n/dictionaries.ts` (`monitoring.services.*`, DE `:577-580`, EN `:1199-1202`), neu
  `SecServices.test.ts`.
- **Doku**: `docs/admin/monitoring.html` + EN (`:46`, `:162`), `docs/developer/agent.html` + EN (`:101`, `:112`),
  `docs/developer/monitoring.html` + EN (`:112`, `:122`), `CHANGELOG.md`.

## Datenmodell / API (Report-Format, additiv)

Keine Migration, keine neue Route. Erweiterung des Agent-Reports im Block `systemd` (Kevin 2026-10-16: additiv
freigegeben; alte Server ignorieren unbekannte Schlüssel, alte Agents liefern sie nicht):

```jsonc
"systemd": {
  "failed": [...],                 // wie bisher, immer gesendet
  "enabled_inactive": [...],       // NEU gefiltert (oneshot/Condition/Timer verworfen), immer gesendet
  "counts": {"active": 41, "total": 63},   // NEU: active_state == "active" / geladene Units (Linux: list-units ohne not-found und masked; Windows: sc query); fehlt, wenn list-units bzw. sc query scheitert
  "error": "systemctl list-units failed: …",  // NEU, nur wenn systemctl scheitert
  "all_services": [                // wie bisher gedrosselt; NEU: nach unit sortiert
    {"unit": "sshd.service", "active_state": "unknown", "enabled_state": "alias", "alias_of": "ssh.service"}
  ]
}
```

`_details` des Checks (Postgres `state.details`, vom Desktop gelesen):
- `auto`: `mode`, `failed`, `enabled_inactive`, NEU `active_count`/`total` (nur wenn `counts` gesendet).
- `list`: `mode`, `watched: [{name, state}]` mit `state ∈ running | down | nodata` (statt `running: bool`; der
  Desktop liest beide Formen, damit alte Details nach dem Update nicht falsch rendern).

## Abläufe

**(a) Zählung.** Empfehlung: der Agent schickt `counts` (billig: eine Zählung über die schon geparsten Maps, Linux
und Windows), der Server legt sie als `active_count`/`total` in `_details`. Alternative „nur Problemzahl“ verworfen:
„x/y aktiv“ ist die Information, die Admins in der Übersicht erwarten, und `counts` kostet keinen Prozessaufruf.
Fehlen die Zähler (alter Agent), zeigt der Desktop nur die Problemzahl bzw. „OK“.

**(b) Fehlalarme.** Der Agent prüft die Kandidaten aus `list-units` (`active == inactive && enabled == enabled`) mit
**einem** gebündelten Aufruf
`systemctl show -p Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic -- <kandidaten>`
nach und verwirft eine Unit, wenn eines gilt:
- `Type=oneshot` und `Result=success` (regulär beendet; `RemainAfterExit=no` ist Standard, systemd.service(5)),
  nur wenn der Start versucht wurde (`ConditionTimestampMonotonic` ≠ 0);
- `ConditionResult=no` (per Condition übersprungen; Property in org.freedesktop.systemd1(5)), nur wenn der Start
  versucht wurde (`ConditionTimestampMonotonic` ≠ 0);
- `TriggeredBy` nicht leer (Start durch Timer/Socket/Pfad; org.freedesktop.systemd1(5)), ohne weitere Bedingung.
`Result=success` und `ConditionResult=no` sind auch die Vorgabewerte einer Unit, deren Start nie versucht wurde;
`ConditionTimestampMonotonic` ist dann 0 (org.freedesktop.systemd1(5): „0 if they have never been checked.
Conditions are checked when a unit is requested to start.“). Beispiel: ein enabled Dienst, dessen Start-Job an einer
fehlenden Abhängigkeit scheitert, bleibt `inactive (dead)` und steht nicht in `--failed`; er bleibt Kandidat.
Fehlt eine Property oder ist ihr Wert leer, wird nichts verworfen (fehlt `ConditionTimestampMonotonic`, greifen die
ersten beiden Regeln nicht). Scheitert der Sammelaufruf mit Exit > 0 (z. B. ein ungültiger Name), fragt der Agent
höchstens 50 Kandidaten einzeln ab; scheitert eine Einzelabfrage, bleibt die Unit Kandidat. Ein Aufruf, der am
Timeout abgebrochen wurde oder nicht startete, beendet die Nachprüfung, und die noch ungeprüften Units bleiben
Kandidat: 50 Einzelabfragen à 15 s Timeout überschritten das `TimeoutStartSec=270` der Agent-Unit und kosteten den
ganzen Report. Der Server übernimmt `systemd.enabled_inactive` unverändert und berechnet es nicht mehr
aus `all_services`; `failed` = `systemd.failed` ∪ `failed` aus dem (sortierten, auf 500 gekappten) Inventar.

Lokal geprüft (systemd 257): `e2scrub_reap` → `Type=oneshot, Result=success`; `systemd-pstore` →
`ConditionResult=no`; `anacron` → `TriggeredBy=anacron.timer`; alle sechs Kandidaten der Box mit
`ConditionTimestampMonotonic` ≠ 0; nie gestartete Units (`alsa-restore`, `alsa-state`) → `Result=success,
ConditionResult=no, ConditionTimestampMonotonic=0`; `sshd.service` → `Id=ssh.service,
Names=ssh.service sshd.service`; eine nicht vorhandene Unit → `Type=` leer, `ConditionResult=no`; `getty@.service` im
Batch → `Failed to get properties: … neither a valid invocation ID nor unit name.` und Exit 1. Achtung: eine
`not-found`-Unit erfüllt `ConditionResult=no` — sie ist aber nie Kandidat, weil `list-unit-files` sie nicht als
`enabled` führt.

**(c) Listen-Modus.** Der Server wertet ihn selbst aus, ohne neue Agent-Konfiguration. Je konfiguriertem Namen:
1. Normalisieren: ohne Suffix → `<name>.service`.
2. Quelle in dieser Reihenfolge: `report["services"]` (Agents mit `--services`, Legacy) → `systemd.all_services`
   des aktuellen Pushes (Treffer über `unit` oder über einen Alias-Eintrag mit `alias_of`) → `prev_details.watched`
   (gedrosselter Push: das Inventar hat sich seit dem letzten vollen Senden nicht geändert, denn jede Zustandsänderung
   ändert den Hash, `inventory.go:33-41`).
3. Ohne Daten → `nodata` (z. B. Tippfehler, Unit existiert nicht, Name neu eingetragen, letztes volles Inventar
   älter): zählt nicht als down; die Anzeige nennt den Namen neutral „nicht gefunden“. Status: `critical`, wenn
   mindestens ein Name `down` ist; `unknown`, wenn kein Name Daten hat; sonst `ok`.
Dafür bekommt `service_process` im Push-Pfad `prev_details` wie `agent_resources` (`routers/agent.py:226`). Der
Agent ergänzt im Inventar Alias-Einträge (`list-unit-files` führt sie mit Zustand `alias`, systemctl(1)) um
`alias_of`, aufgelöst mit einem gebündelten `systemctl show -p Id -- <aliase>` (ohne Template-Namen `*@.service`).
Der Legacy-Pfad `collectWatchedServices` fragt bei einem Batch-Fehler einzeln nach und löst über `Names` auf.

**(d) `ignore` und Kappung.** `ignore`-Einträge sind Glob-Muster (`fnmatch.fnmatchcase`) mit derselben
`.service`-Normalisierung wie heute. Der Agent sortiert `all_services` nach `unit`; die Kappung auf 500 im Checker
wird damit deterministisch und betrifft nur noch `failed` aus dem Inventar (das immer gesendete `systemd.failed`
deckt diese Units ohnehin) und die Listen-Suche.

**(e) Desktop.** `SecServices.svelte` rendert aus `_details`: kein Details-Objekt → neutrale Pille
„Noch keine Daten“; Pillenfarbe aus dem effektiven Check-Status (`check.state.status`, dieselbe Quelle wie der
Punkt), die Liste darunter aus `_details`; Hinweise über i18n-Schlüssel (`monitoring.services.note.failed|inactive|
down|nodata`); „x/y aktiv“ nur mit `active_count`/`total`.

## Externe Integrationen

- systemd: `systemctl show -p …` (Properties `Id`, `Names`, `Type`, `Result`, `ConditionResult`, `TriggeredBy`,
  `ConditionTimestampMonotonic`, dokumentiert in org.freedesktop.systemd1(5)); Unit-File-Zustand `alias`
  (systemctl(1), Tabelle zu `is-enabled`);
  `RemainAfterExit=` Standard `no` (systemd.service(5)). Geprüft gegen die lokal installierten Manpages von
  systemd 257 (Debian 13); freedesktop.org war per WebFetch nicht erreichbar (403) — **gegen die Web-Version nicht
  verifiziert**. Ab welcher systemd-Version `TriggeredBy` existiert: **nicht verifiziert**; fehlt die Property,
  wird nichts verworfen (sicherer Rückfall, nur weniger Filterung). Ubuntu 24.04 (systemd 255) im Lab: Ausgabe von
  `list-units`/`list-unit-files` im erwarteten Format.

## Trade-offs & Alternativen

1. **Filtern im Agent vs. im Server.** Der Server sieht `Type`/`Result`/`ConditionResult` nicht; sie für alle
   ~300 Units ins Inventar zu legen, bläht jeden vollen Push auf. Der Agent prüft nur die wenigen Kandidaten nach
   (ein zusätzlicher Prozessaufruf je Zyklus, nur wenn es Kandidaten gibt). **Empfehlung: Agent.**
2. **Listen-Modus: Server wertet aus vs. Liste zum Agent synchronisieren.** Synchronisation bräuchte einen neuen
   Rückkanal (Push-Antwort oder Konfig-Abruf), Persistenz im Agent und Versionierung (L). Die Server-Auswertung nutzt
   das ohnehin gesendete Inventar plus `prev_details` (M, keine Migration). Nachteil: ein neu eingetragener Name hat
   bis zum nächsten vollen Inventar (≤ 1 h oder bei der nächsten Zustandsänderung) `nodata`. **Empfehlung: Server.**
3. **Zähler vom Agent vs. nur Problemzahl.** Siehe (a). **Empfehlung: Agent-Zähler.**
4. **`watched` mit `state` statt `running: bool`.** Nötig für `nodata`; der Desktop liest beide Formen.

## Risiken & Rollback

- **Zu viel verworfen:** Ein Dienst, der per Timer läuft *und* dauerhaft laufen soll, fällt aus `enabled_inactive`.
  Gegenmittel: `failed` bleibt unverändert; wer einen bestimmten Dienst erzwingen will, nutzt den Listen-Modus.
- **Zu wenig verworfen:** Eine enabled Unit, deren Start nie versucht wurde, bleibt Kandidat, auch wenn sie
  harmlos ist, z. B. weil ihr Ziel-Target nie erreicht wurde (`WantedBy=` eines nicht aktiven Targets).
  Gegenmittel: `ignore` (mit Glob). Der Preis dafür, dass ein Dienst, dessen Start an einer Abhängigkeit scheiterte,
  weiter gemeldet wird.
- **Alte Agents** liefern weiter ungefilterte `enabled_inactive` und keine Zähler; der Desktop zeigt dann die
  Problemzahl ohne „x/y“. Kein Fehlbild, nur weniger Information.
- **Wechsel der `_details`-Form** im Listen-Modus: abgedeckt durch das Lesen beider Formen.
- **Rollback:** Revert des Merge-Commits; keine Migration, Report-Felder additiv.

## Doku-Impact

Sichtbar, DE + EN: `docs/admin/monitoring.html` (`:46` Tabelle, Abschnitt Standard-Template `:162`): was `auto`
meldet und was nicht (oneshot/Condition/Timer), `ignore` mit Glob, Listen-Modus (Namen, `.service`, Aliase, Daten
spätestens mit dem nächsten vollen Inventar). Entwickler-Doku DE + EN: `docs/developer/agent.html` (`:101`, `:112`)
und `docs/developer/monitoring.html` (`:112`, `:122`) — neue Report-Felder. `CHANGELOG.md` (Fixed).

## Offene Fragen

Keine. Entschieden von Kevin am 2026-10-16:

1. **Listen-Modus ohne Daten:** Ein Name ohne Daten (`nodata`, z. B. Tippfehler oder nicht existierende Unit) zählt
   nicht als down; die Anzeige nennt ihn neutral „nicht gefunden“. Der Check wird nur `unknown`, wenn *kein* Name
   Daten hat.
2. **Server-Meldungstexte** (deutsch, auch in englischer UI und in Mail/Telegram): nicht in diesem Vorhaben, sondern
   eine eigene Roadmap-Zeile (betrifft alle Checker).
3. **Kandidaten-Deckel** für die Einzelabfrage nach einem gescheiterten Sammelaufruf: höchstens 50; darüber bleiben
   die restlichen Kandidaten ungeprüft (wie heute gemeldet).
