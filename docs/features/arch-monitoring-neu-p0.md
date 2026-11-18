<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Neuordnung, Phase 0: Entscheidungen, Mockups, Machbarkeit

Roadmap R-1558 (FEAT, Architektur) mit R-1515 (IDEE, gebündelt als Regelkonzept) · Zug `arch-monitoring-neu-p0` ·
Kevin 2026-11-18: Richtung „Objekt, Regel, Ausnahme, Problem, Abdeckung“ angenommen; Darstellungswunsch „erst der
Hauptzustand, dann wenige Kennzahlen mit Schwelle, Details in der Schublade“. Stand des Codes: `origin/main@3aa2499f1`;
`datei:zeile` gilt für diesen Stand. Die Phasen P1–P5 (R-1559 … R-1563) bauen auf dieser Phase auf und warten auf ihre
Abnahme.

## Problem / Motivation

Das Monitoring ist über zwei Jahre um Einzelwünsche gewachsen. Heute:

1. **Fünf Arten, etwas auszublenden** (Schalter `enabled`, `silent` des Katalog-Syncs, Ignorierlisten je Check-Typ,
   Wartungsfenster, Stummschalten je Person im Hub); keine trägt einen Grund, es gibt keine Gesamtliste, Ausgeblendetes
   verschwindet aus der Ansicht.
2. **Zwei Welten von Checks:** 14 eingebaute Typen mit eigenem Ergebnisformat und eigener Ansicht gegen 125
   Katalog-Module mit deklarativen Regeln und einer generischen Karte. Schwellen lassen sich nur bei den einen im
   Formular ändern, bei Modulen gar nicht (die API erlaubt es, die UI nicht).
3. **Zwei Benachrichtigungswege:** Alarmregeln (Mail/Webhook direkt) und der Benachrichtigungs-Hub (Matrix je Person,
   Vorfälle); die Monitoring-Ansicht zeigt die Vorfälle nicht.
4. **Vier Entstehungswege für Checks** (Vorlage, Modul aus Fund, Scan-Vorschlag, Hand) und keine Antwort auf
   „ist alles überwacht?“.
5. **Zustand und „seit“ hängen am Check**, nicht am Ding: `MonitorState.since`
   (`apps/monitoring/app/models.py:186`) wechselt bei jedem Wechsel des gedämpften Status, „seit wann ist diese Platte
   schlecht“ gibt es nicht. Objekte stecken als Listen in `_details`; die UI rechnet Farben teils selbst und weicht von
   der Bewertung des Servers ab.
6. **Regeln sind nicht update-fest:** ein Katalog-Update schreibt die Regeln eines Modul-Checks neu und behält nur
   `interval_s`/`timeout_s` (`apps/monitoring/app/module_sync.py:432-434`); `Rule`
   (`apps/monitoring/app/catalog/model.py:140`) hat keinen stabilen Schlüssel, an dem eine eigene Änderung hängen
   könnte. Eingebaute Checks bewerten im Code (`apps/monitoring/app/checkers/smart.py:239`,
   `apps/monitoring/app/checkers/plugins.py:276`, `:401`), nicht in Regeln.

Jeder weitere Einzelwunsch (Ausnahme-Knöpfe, Backup- und SMART-Ansicht, Meldung neuer Funde) würde einen weiteren
Mechanismus und eine weitere Sonderansicht erzeugen. Phase 0 klärt das Zielmodell, bevor Code entsteht.

## Ziel & Nicht-Ziele

**Ziel** — Kevin nimmt am Ende dieser Phase ab:

- **Klickbare Mockups im Design-System** (nur Tokens und Komponenten aus `apps/desktop/ui/src/components/ui/`) für
  jede Objektart nach der Darstellungs-Grammatik:
  - Ebene 1 Hauptzustand: ein Status-Badge, ein Satz Grund im Klartext, „seit“;
  - Ebene 2 Kennzahlen: höchstens vier Werte, jeder mit Schwellen-Kontext („41 °C (Warnung ab 55)“);
  - Ebene 3 Schublade: alle Attribute, Verlauf, Regeln/Schwellen, Ausnahmen, Rohdaten;
  - Identitätszeile (Name, Modell/Typ, Ort); schlechteste zuerst, Ausgeblendetes grau am Ende mit Grund.

  Objektarten: `disk` (HDD, SATA-SSD, NVMe, SAS), `pool`, `guest-backup`, `backup-job`, `host`, `cpu`, `memory`,
  `mount`, `sensor`, `reboot`, `updates`, `clock`, `service`, `container`, `compose-project`, `certificate`, `domain`,
  `endpoint` und die Katalog-Familien (Web/Proxy, Apps, Datenbanken, Mail, Backup-Module, Windows-Rollen,
  Verzeichnis, Virtualisierung, Netz, Host-Hardware, Generisch). Dazu die Ansichten **Lage** (nur Probleme, Grünes in
  einer Zeile), **Server**, **Objekte** (Tabelle mit Filtern), **Querschnitte** (Platten, Backups, Pools, Container,
  Zertifikate, Updates & Neustart, Mounts, Dienste), **Abdeckung** (je Server überwacht / gefunden, nicht überwacht /
  ausgeblendet), **Ausnahme-Dialog** (Geltung × Wirkung × Dauer, Grund, wertgebunden), Liste **Ausgeblendet** und die
  **Schublade**.
- **Machbarkeit Regeln für eingebaute Checks**, belegt durch einen Prototyp mit Tests: stabiler `Rule.key`,
  Overrides als eigene Schicht (Wert, an/aus) mit Drei-Wege-Merge beim Katalog-Update, Operator „steigt“ (Delta) und
  Hysterese je Regel, wertgebundene Ausnahme, Bedingung über einen anderen Check derselben Instanz (R-1515); dazu ein
  Differenzial-Test, der die SMART-Kaskade, die ZFS-Zustände und die Docker-Bewertung als Regeln gegen die heutigen
  Checker fährt und benennt, was Code bleiben muss.
- **ADR 0004** (`docs/adr/0004-monitoring-neuordnung.md`): Zielmodell, stabile Schlüssel je Objektart,
  Regelmodell, Migrationsplan (Mechanismus für Mechanismus, mit Rückweg), Ergebnisse der Experimente, Kevins
  Entscheidungen.
- **Experimente** mit Messwerten: Hub-Fehler beim Melden, Deaktivieren eines kritischen Checks, Monitoring-Neustart
  nach 20 min, 400 Objekt-Upserts auf Postgres, Sammelabruf über 50 Reihen in VictoriaMetrics, Schlüssel bei
  neu angelegten Containern.
- **Kevins Entscheidungen** zu den zehn Fragen (Offene Fragen unten) und zu Unterobjekten mit Namen je Familie.

**Nicht-Ziele** (YAGNI; jeweils eine spätere Phase):

- Kein Produktverhalten ändert sich: keine Migration, keine API, kein neuer Endpunkt, kein Agent-Feld, keine
  Änderung an Checkern, Alerter oder Hub. Fehler, die die Experimente belegen, werden Roadmap-Zeilen.
- Die Mockups sind nicht die P2-Oberfläche: fiktive Daten, kein Server-Abruf, kein i18n (Texte deutsch, wie Kevin
  sie abnimmt), nicht im Produktions-Build. P2 baut die echten Komponenten und darf Teile übernehmen.
- Der Regel-Prototyp lebt nur in den Tests von `apps/monitoring`; P1 ersetzt ihn durch die echte Regel-Schicht und
  kündigt dann seine Löschung an.
- Das Fassaden-Experiment (alter Desktop gegen `/alerts`-Fassade) braucht die Fassade und fährt in P3.
- `smartctl -n standby` an einer echten HDD lässt sich auf der Dev-Box nicht messen (keine HDD); das Ergebnis bleibt
  „nicht verifiziert“, der Messweg steht im ADR.

## Betroffene Komponenten & Dateien

| Bereich | Datei(en) | Art |
|---|---|---|
| Mockup-Einstieg | `apps/desktop/ui/mockup.html` | neu; Vite liefert ihn im Dev-Server unter `/mockup.html` aus, `vite build` baut nur `index.html` (`apps/desktop/ui/vite.config.ts` hat keine `rollupOptions.input`) |
| Mockup-Code | `apps/desktop/ui/src/mockups/monitoring-neu/` (`main.ts`, `MockupApp.svelte`, `model.ts`, `grammar.ts`, `ObjectRow.svelte`, `ObjectDrawer.svelte`, `fixtures/*.ts`, `details/*.svelte`, `views/*.svelte`, Tests) | neu; `npm run check`, `npm run lint` und `npm run test` erfassen `src/**` schon |
| Bausteine (nur lesen) | `apps/desktop/ui/src/components/ui/` (`Badge`, `Pill`, `Dot`, `Panel`, `Tabs`, `Segmented`, `MetaList`, `Callout`, `Button`, `Modal`, `Select`, `RadioGroup`, `Switch`, `Input`, `FormField`, `Tag`, `Tooltip`, `EmptyState`) | unverändert |
| Heutige Ansichten (Vergleich, nur lesen) | `apps/desktop/ui/src/components/monitoring/section/Sec*.svelte`, `card/ModuleCard.svelte`, `cross/*View.svelte` | unverändert |
| Regel-Prototyp | `apps/monitoring/tests/rule_model_prototype.py`, `apps/monitoring/tests/test_rule_model_prototype.py` | neu, nur Tests |
| Differenzial-Test | `apps/monitoring/tests/test_rule_model_differential.py` | neu; ruft `SmartHealthChecker.evaluate` (`app/checkers/smart.py:199`), `ZfsHealthChecker.evaluate` (`app/checkers/plugins.py:276`), `DockerHealthChecker.evaluate` (`app/checkers/plugins.py:492`) |
| Heutiges Regelmodell (nur lesen) | `app/catalog/model.py:135` (`RuleUnless`), `:140` (`Rule`), `:358` (`CardItem`); `app/checkers/probe.py:125` (`_rule_holds`, mit `delta_gt` gegen den Lauf davor), `:157` (`_rule_text`), `:168` (`_rate`); `app/module_sync.py:410` (`_update`) | unverändert |
| Zustand heute (nur lesen) | `app/models.py:117` (`MonitorCheck`, `consecutive_fails` `:129`), `:181` (`MonitorState`); `app/check_engine.py:98` (`is_suppressed`), `:135` (`holds_recovery`), `:286` (`_write_state`) | unverändert |
| Architektur | `docs/adr/0004-monitoring-neuordnung.md` | neu (deutsch wie ADR 0001–0003) |
| Entwickler-Doku | `DEVELOPMENT.md` (Mockups öffnen), `docs/developer/monitoring.html` + `docs/en/developer/monitoring.html` (Verweis auf ADR 0004) | geändert |

Die Experiment-Proben (Wegwerf-Code gegen die Test-DB, einen lokalen VictoriaMetrics-Container, Docker) liegen nicht
im öffentlichen Baum; ihr Verfahren und ihre Messwerte stehen im ADR, so dass jede Probe nachgebaut werden kann.

## Datenmodell / API / Migrationen

Keine. Phase 0 entwirft sie für P1 im ADR:

- `monitor_object_state` (PK `check_id` + `object_key` ≤ 200; `kind`, `name`, `status`, `reason`, `since`,
  `bad_since`, `gone_at`), geschrieben nur bei Änderung; ein Statuswechsel-Log; das Ausnahme-Modell; `Rule.key` und
  eine Override-Tabelle. Alle API-Erweiterungen additiv (`MonitorCheckOut`/`MonitorStateOut` bleiben), alte Desktops
  schreiben weiter Ignorierlisten und Wartung, der Server übersetzt beides.
- Vertrags-Drift Server ↔ Web ↔ Desktop ↔ Agent: keine in P0.

## Externe Integrationen

- **VictoriaMetrics** (nur Experiment): `GET /api/v1/query_range` mit einem Selektor über mehrere Reihen
  (`{__name__="…", check_id=~"a|b|…"}`) und Import über `/api/v1/import/prometheus`; Doku
  <https://docs.victoriametrics.com/victoriametrics/url-examples/> und
  <https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/>. Vor dem Experiment nachlesen,
  im ADR mit Link zitieren.
- **smartmontools** (nur Messweg im ADR): Bedeutung von `-n standby` laut Handbuchseite `smartctl(8)`
  (<https://www.smartmontools.org/browser/trunk/smartmontools/smartctl.8.in>).
- Kein FRP, kein Tauri-IPC, keine Proxmox-API.

## Trade-offs & Alternativen

| Frage | Gewählt | Alternativen | Begründung |
|---|---|---|---|
| Wo leben die Mockups? | Zweiter Vite-Einstieg `mockup.html` in `apps/desktop/ui`, nur Dev-Server | (a) eigenes Paket `apps/mockups`; (b) Storybook; (c) statische HTML-Datei; (d) Design-System-Repo | Nur so nutzen die Mockups die echten Svelte-Komponenten und Tokens und laufen durch dieselben Gates (svelte-check, ESLint, Prettier, vitest, Token-Test). (a) dupliziert Build und Abhängigkeiten, (b) bringt eine neue Abhängigkeit für eine Phase, (c) und (d) zeigen nicht das echte Design-System. Kosten: Mockup-Code im Repo, den P2 übernimmt oder löscht. |
| Mockup-Daten | Fiktive Fixtures (Hosts `pve-01`, `nas-01`, `web-01` …, Domains `example.org`, Adressen 192.0.2.x/198.51.100.x/203.0.113.x) | Echte Reports | Das Repo ist öffentlich; echte Daten tragen Homelab-Namen. Die Abnahme an echten Daten ist P2 (Konzept-Leitplanke). |
| Abnahme-Weg | Screenshots je Ansicht (headless Chromium) an Kevin; dazu dieselbe Mockup-Seite als privates Artefakt, damit er klicken kann | Nur `npm run dev` auf der Dev-Box | Die Dev-Box hat kein Display; das Artefakt enthält nur fiktive Daten und bleibt privat. |
| Regel-Prototyp | Testmodul in `apps/monitoring/tests`, Differenzial-Test gegen die heutigen Checker | (a) gleich die echte Regel-Schicht unter `app/`; (b) nur Text im ADR | (a) wäre P1 ohne Entscheidungen, (b) belegt nichts. Der Differenzial-Test zeigt je Szenario, ob die Regelform dasselbe Urteil fällt, und macht sichtbar, was Code bleiben muss. |
| Experiment-Proben | Wegwerf-Code außerhalb des öffentlichen Baums, Verfahren und Messwerte im ADR | Committete Charakterisierungstests | Ein Test, der heutiges Fehlverhalten festschreibt, ist ein Anti-Muster; belegte Fehler werden Roadmap-Zeilen, deren Fix-Vorhaben den roten Test bringt. |
| Ein ADR statt mehrerer | ADR 0004 mit Abschnitten | ADR je Thema | Die Themen hängen aneinander (Schlüssel → Objektzustand → Ausnahme → Problem); eine Seite hält sie konsistent. |

## Risiken & Rollback

- **Produktions-Build zieht Mockups an:** nur, wenn `main.ts` oder `vite.config.ts` sie einbinden; T1 belegt mit
  einem Build-Test (`dist/` enthält nach `vite build` kein `mockup.html`), dass das nicht passiert.
- **Token-/i18n-Tests über `src/`:** `src/styles/tokens.test.ts` prüft jedes `var(--…)` unter `src/`;
  `src/lib/i18n/i18n.test.ts` prüft benutzte Schlüssel. Mockups nutzen nur bestehende Tokens und kein `t()`.
- **Differenzial-Test bindet an heutige Checker:** ändert ein Parallel-Vorhaben einen Checker (etwa die SMART- oder
  ZFS-Fehlerzeilen), kann er rot werden. Er prüft deshalb nur Szenarien, deren Urteil die Doku festschreibt, und
  nennt jede bewusste Abweichung als eigenes Szenario.
- **Mockups wirken wie Zusagen:** jede Ansicht trägt den Hinweis „Mockup, fiktive Daten“, Kennzahlen, die neue
  Agent-Daten brauchen (WWN, SSD-Verschleiß, SAS, Paketlisten-Alter …), sind markiert.
- **Rollback:** alles ist neu und von nichts referenziert; Revert des Merge-Commits entfernt die Phase vollständig.

## Doku-Impact

Neu ADR 0004 (deutsch, wie ADR 0001–0003). `DEVELOPMENT.md` nennt den Mockup-Einstieg; die Entwickler-Seite zum
Monitoring-Stack (`docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`) verweist auf ADR 0004.
Bedienungs-Doku ändert sich nicht (kein Nutzerverhalten); kein CHANGELOG-Eintrag.

## Offene Fragen

Kevins Entscheidungen (Konzept §9), je mit Empfehlung; die Mockups zeigen die empfohlene Variante:

1. **Wo lebt das Problem?** Empfehlung: Lebenszyklus (öffnen, seit, schließen, Flattern, Dauer-unknown) im
   Monitoring; Bestätigen, Notiz und Routen im Hub; Schlüssel 1:1.
2. **Ein Ausnahme-Modell** ersetzt `enabled` (als Nutzerschalter), Ignorierlisten, Wartungsfenster und Mutes, mit
   Migration. Empfehlung: ja.
3. **Alarmregeln werden Routen im Hub**, mit Diff-Bericht vor dem Umschalten, `/alerts` als Fassade und Kanal „altes
   Webhook-Format“. Empfehlung: ja.
4. **Fund-Politik je Profil:** vorschlagen (Standard) oder automatisch still übernehmen. Empfehlung: ja.
5. **Standard-Schwellen** CPU/RAM/Disk vereinheitlichen. Empfehlung: die Vorlagen-Werte (CPU 90/95, RAM 90/98,
   Disk 80/90), weil sie heute auf den Servern aktiv sind.
6. **Zertifikatsfristen** mit einer Bewertung für alle Quellen. Empfehlung: relativ zur Laufzeit (25 %/10 %) mit
   absoluter Untergrenze.
7. **Unterobjekte mit Namen** (einzelne Datenbanken, Backup-Clients, Zertifikat je vhost) gegen „kein Name verlässt
   den Agent“: Entscheidung je Familie; die Mockups zeigen je Familie die Variante mit und ohne Namen.
8. **SMART: schlafende Platten nicht wecken** (`-n standby`), Anzeige „schläft, letzter Stand von …“. Empfehlung: ja.
9. **Ende einer Ausnahme = Nachmeldung** des aktuellen Zustands. Empfehlung: ja.
10. **Cluster-Geltung:** bis der Report den PVE-Clusternamen liefert, gilt ein Tag als Ersatz. Empfehlung: ja.
11. **R-1515 (Bedingung über Checks einer Instanz):** als Ausnahme mit Geltung „Check“ und Bedingung „solange Check X
    Zustand Y meldet“ (empfohlen) oder als Regel-Bedingung `when`. Der Prototyp prüft beide Formen, das ADR empfiehlt.
12. **Abnahme der Screens** (Lage, Server, Objekte, Querschnitte, Abdeckung, Ausnahme-Dialog, Schublade, jede
    Objektart).
