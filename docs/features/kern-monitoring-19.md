# Monitoring: Härtung der Probe-Anlage, der Probe-Ziele und der Probe-Zugangsdaten (kern-monitoring-19)

Roadmap: R-1252, R-1266, R-1299 (Kevin 2026-11-10/11 Triage, alle vor dem Release 0.47.0, R-1110). Nachlese aus den
Prüfungen von `arch-monitoring-module` und `kern-monitoring-15`. Einzelheiten der Sicherheitszeilen stehen nur in der
privaten Roadmap.

## Problem / Motivation
- **R-1252:** Härtung der Probe-Parameter. Probe-Checks sollen nur noch aus übernommenen Katalog-Modulen entstehen
  (`app/module_sync.py`), nicht frei über `POST /checks`, `PUT /checks/{id}` oder Templates; dazu eine Sperrliste
  im Agent für Unix-Sockets und Steuerdienste des Hosts (`neverProbed`, `apps/agent/internal/probe/guard.go`).
- **R-1266:** Härtung der Probe-Zugangsdaten (`monitor credential set`): ein gespeichertes Secret gilt nur für das
  Ziel und den Port seines Moduls.
- **R-1299:** Härtung des Ziel-Abgleichs (`checkListener`, `apps/agent/internal/probe/guard.go`) bei
  veröffentlichten Container-Ports ohne Listener auf dem Host.

## Ziel & Nicht-Ziele
- Die Monitoring-API legt keinen Probe-Check von Hand an und ändert an einem bestehenden nur, was der Katalog zum
  Einstellen vorsieht (Regeln, Intervall, Timeout, Name, Schweregrad, an/aus). Templates nehmen keine Probe-Defs.
  Der Plan an den Agenten trägt nur Probe-Checks eines Moduls.
- Der Agent spricht keine weiteren Steuerdienste von Hosts und Gästen an (Proxmox-API-Dienste, weitere VM-Prozesse)
  und keinen Unix-Socket unter den Laufzeitverzeichnissen solcher Dienste, auch über einen Symlink.
- Ein Secret geht nur an das Ziel, an das es gebunden ist; ein anderes Ziel ergibt `not_allowed`, bis es neu gesetzt
  wird.
- Ein veröffentlichter Container-Port ohne Host-Listener wird wie einer mit `docker-proxy` geprüft; gestoppte
  Dienste behalten `connection refused`.
- Nicht-Ziele: kein Ersatz-Weg für eigene Probe-Checks (eigene Messungen kommen über den Katalog); keine Änderung
  am Wire-Format von Plan oder Report; Podman-DNAT ohne Docker bleibt außen vor (nicht verifiziert, ob der Weg
  existiert; als Nachlese-Frage in der Abschlussprüfung).

## Betroffene Komponenten & Dateien
- **agent** (`apps/agent/internal/probe/`): `guard.go` (`checkListener`, `neverProbed`, `hostDaemons`),
  `sensor_local_linux.go` (`dialUnix`, `checkPeer`), `sensor_unixsocket.go`, `probe.go` (`Access.credential`),
  `sensor_http.go`, `sensor_proto.go`, `sensor_local.go` (`inspectContainer`), Tests; der Report-Zustand
  (`apps/agent/internal/monitor/reportstate.go`) für die Bindung.
- **monitoring** (`apps/monitoring/app/`): `routers/checks.py` (`create_check`, `update_check`), `schemas.py`
  (`TemplateCheckDef`), `module_plan.py` (`_probes`), Tests.
- Die Desktop-Karte für einen Probe-Check ohne Modul (`MonServerDashboard.svelte`) bleibt; sie wird ohne solche
  Checks nur nicht mehr erreicht (fremder toter Code, nicht Teil des Auftrags).

## Datenmodell / API / Migrationen
- Keine Migration: Probe-Checks gibt es erst seit dem Modul-Katalog, nach v0.46.0 (unveröffentlicht).
- API-Verhalten (Kevin 2026-11-11: „probe nur per Katalog-Übernahme“): `POST /checks` mit `check_type=probe` → 422;
  `PUT /checks/{id}` mit Wechsel von oder zu `probe` → 422; geänderte Mess-Teile einer Probe-Config (`sensor`,
  `target`, `params`, `fields`, `credential`, `test_object`) → 422; Templates mit einer Probe-Def → 422.
- Agent: neuer Eintrag im Report-Zustand (Bindung je Ref an die Credential-ID), wie die Bremse (`KeptBrake`).

## Externe Integrationen
- Docker: `docker inspect` der laufenden Container (`NetworkSettings.Ports`), wie heute `inspectContainer`. Die
  Form der Port-Map vor dem Bau in der Docker-Doku nachlesen (Engine API, ContainerInspect).

## Trade-offs & Alternativen
- **Bindung (R-1266):** Kevin hat entschieden: im Agent, an Ziel und Port des Moduls. Umsetzung: beim ersten Einsatz
  nach dem Setzen bindet der Agent die Credential-ID an Sensor, Übergabe, Ziel (Art und Name) und den aufgelösten Port
  bzw. Socket-Pfad; danach verweigert er jedes andere. Alternative wäre, das Ziel bei `credential set` mitzugeben —
  verworfen: der Admin müsste Port und Ziel des Moduls kennen und tippen. Empfehlung: Bindung beim ersten Einsatz,
  Neusetzen löst sie.
- **Probe-Anlage (R-1252):** Durchgesetzt an allen drei Wegen (API, Templates, Plan); der Plan ist die letzte Stelle
  vor dem Agenten und fängt auch Altzeilen.
- **Sperrliste:** Pfad-Präfixe statt einzelner Sockets; der bestehende Peer-Abgleich bleibt davor.

## Risiken & Rollback
- Eine zu weite Socket-Sperrliste sperrt einen Katalog-Fühler aus: Tests prüfen jeden Socket-Pfad des Katalogs.
- `docker inspect` je Check ohne Listener kostet: wie die Listener-Liste mit TTL zwischengespeichert.
- Rollback je Task (je ein Commit).

## Doku-Impact
`docs/admin/monitoring.html` und `docs/en/admin/monitoring.html`: Probe-Checks nur über Module (Tabelle der Check-
Typen, Config-Tabelle, Dashboard-Karte), Bindung der Zugangsdaten, was der Agent nie anspricht. CHANGELOG über
`changelog.d/kern-monitoring-19.md` (neutral).

## Offene Fragen
- keine aus Kevins Bereich; die Bindungsart (erster Einsatz) ist eine Umsetzungswahl innerhalb seiner Entscheidung.
