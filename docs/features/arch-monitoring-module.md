<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module: Fühler, Katalog, Erkennung (Architektur)

Roadmap R-1223 (FEAT, Architektur) · Zug `arch-monitoring-module` · Kevin 2026-11-09, Monitoring-Konzept
(§3, §8.1, §10). Stand des Codes: `origin/main@726c51d13`. Alle `datei:zeile` beziehen sich auf diesen Stand.

R-1224 (zentrale Fühler im Monitoring-Dienst: tls, dns, rdap, smtp/imap, Mail-DNS, DNSBL) war demselben Zug
zugeordnet. Beide Zeilen passen nicht in einen Zug mit höchstens 15 Tasks, deshalb fährt R-1224 im Folgezug
`arch-monitoring-module-2` und baut dort auf dem Fühler- und Check-Modell dieses Zugs auf (siehe „Zuschnitt“).

## Problem / Motivation

Heute braucht jeder neue Dienst einen eigenen Check-Typ mit Checker-Klasse, Config-Modell, Metrikliste und
Svelte-Sektion (`apps/monitoring/app/check_types.py:21`, `apps/monitoring/app/checkers/__init__.py`,
`apps/monitoring/app/check_configs.py`). Das Monitoring-Programm (R-1219..R-1249) soll rund 40 Dienste abdecken; mit
dem heutigen Muster wird das unwartbar, und die Oberfläche wächst Sektion um Sektion. Die meisten Dienste lassen sich
aus wenigen gleichen Messarten zusammensetzen.

Außerdem weiß der Server nichts darüber, was auf einem Host läuft, außer den Subsystemen aus R-0421 (Docker, ZFS,
Proxmox). Neue Dienste muss der Admin heute selbst bemerken und von Hand als Check anlegen.

## Ziel & Nicht-Ziele

**Ziele (R-1223)**
- **Fühler:** ein fester, einkompilierter Satz Messarten im Agent: `unit`, `process` (prozess), `socket`,
  `container`, `http`, `tls`, `certfile` (zertdatei), `file_age` (datei-alter), `proto`, `unixsocket`, `sql`, `dns`,
  `log`. Der Server schickt nur Parameter, nie Befehle (Konzept §3.8).
- **Katalog als Daten:** Module mit Erkennung, Instanz-Art, Checks (Fühler, Parameter, Takt, Bewertung, Zugang,
  Kennzeichen „Testobjekt“), Kennzahlen der Karte; versioniert im Monitoring-Dienst wie die eingebauten Templates.
- **Erkennung:** alle 24 h mit Zufallsversatz (24–48 h) und auf Knopfdruck („Jetzt scannen“, wirkt beim nächsten
  Agent-Lauf, also nach höchstens 5 min). Der Server gleicht das Inventar mit dem Katalog ab und füllt einen
  **Funde-Eingang** (neu, geändert, verschwunden) mit „übernehmen“, „alle übernehmen“ und „ignorieren“. Gelöscht wird
  nie automatisch.
- **Ports nie fest:** ein Check fragt den Port, auf dem der erkannte Prozess oder Container tatsächlich lauscht;
  Katalog-Ports sind nur Hinweise. Unbekannte Ports werden lokal protokollgerecht erkannt (Banner, typische Probe,
  TLS) und als Fund gemeldet.
- **Takt-Planer im Agent:** je Probe ein Takt (5 min, 15 min, 1 h, 24 h); der Agent-Lauf bleibt alle 5 min.
- **Sicherheitsmodell:** keine LAN-Sonde (Ziele nur Loopback, eigene Adressen, eigene Container, geprüft beim
  Verbindungsaufbau), Feld-Freigabe (an den Server gehen nur die angefragten skalaren Felder, gekürzt), Zugangsbremse
  (nach 401/403 Ruhe, bis sich die Zugangsdaten ändern), Zugangsdaten lokal (Datei nur für root, gesetzt über eine
  Agent-CLI, die der Desktop per SSH aufruft; der Server erfährt nur „hinterlegt“).
- **Selbstmessung und Selbstbremse:** Dauer und CPU-Zeit je Collector im Report; reißt ein optionaler Collector
  zweimal hintereinander sein Zeitlimit, verdoppelt sich sein Intervall, und der Report sagt das.
- **Neue Checks still:** Checks, die ein Katalog-Update einer übernommenen Instanz hinzufügt, sammeln Daten, alarmieren
  aber erst nach dem Übernehmen.
- **Generische Bewertung:** ein Check-Typ `probe` (push-ausgewertet) bewertet das Fühler-Ergebnis: Wertvergleich,
  Schwelle, Delta, Alter, Frische nach Takt.
- **Datenvertrag** für `arch-monitoring-ui` (R-1225..R-1227): Plan, Report-Blöcke, Funde-/Katalog-/Erkennungs-API.

**Nicht-Ziele**
- Zentrale Fühler im Monitoring-Dienst (R-1224) — Folgezug `arch-monitoring-module-2`.
- Die neue Oberfläche (Karten, Querschnitt, Funde-Eingang, Monitoring-Kosten, Zugangsdaten-Dialog) — R-1225..R-1227.
  Dieser Zug liefert dafür API und Agent-CLI; bestehende Sektionen bleiben unverändert.
- Modul-Einträge für konkrete Dienste, Spezial-Collector (`pvesh`, `samba-tool`, `postqueue` …), Konfig-Auszüge
  (`nginx -T` …) und Konfig-Tests — Modul-Wellen `kern-monitoring-7..14` (R-1228..R-1246). Mit diesem Zug kommt nur
  das generische Modul `port` (unbekannter lauschender Port, protokollgerecht geprüft, Konzept §3.12 Stufe 4).
- Das Windows-Ereignisprotokoll im Fühler `log` — Welle W4 (Windows, „Ereignisse“); unter Windows meldet `log`
  „nicht unterstützt“. `sql` gibt es nur unter Linux (SQL Server: nur Dienst und Ereignisse, Kevin 2026-11-09).
- Rücksicht bei Last (Konzept §3.13 Punkt 3) und der Ressourcen-Deckel der Unit — R-1221 (`kern-monitoring-6`).
- Die Freigabeliste mit Build-Test — R-1222. Dieser Zug legt `internal/execx.Run` als einzigen Exec-Pfad an (`runTimed`
  in `plugins.go:62` ruft es nur noch auf); alle neuen Aufrufe laufen mit festen Argumenten darüber, damit R-1222 sie
  an einer Stelle erfasst.

## Betroffene Komponenten & Dateien

| Komponente | Dateien (neu = N) |
|---|---|
| Monitoring | `app/catalog/` (N: Modell, Lader, Module als Python-Daten), `app/models.py`, `alembic/versions/` (N), `app/routers/agent.py` (Plan-Route, Report-Blöcke), `app/module_plan.py` (N), `app/discovery.py` (N: Speichern, Abgleich, Funde), `app/module_sync.py` (N: Übernehmen, Katalog-Abgleich), `app/routers/findings.py` (N), `app/alerter.py` (`muted_reason`, `:353`), `app/checkers/probe.py` (N), `app/check_types.py`, `app/check_configs.py`, `app/checkers/__init__.py`, `app/routers/checks.py`, `app/routers/__init__.py`, `app/schemas.py`, `app/main.py` (Katalog-Abgleich beim Start), `app/server_cleanup.py`, `tests/openapi.snapshot.json` |
| Server | `app/modules/monitoring_proxy/router.py` (neue Agent-Route `GET /agent/{id}/plan` neben `proxy_agent_report`, `:108`; Präfixe `catalog`, `discovery`, `findings` in `_ALLOWED_PATH_PREFIXES`, `:78`), `tests/openapi.snapshot.json` |
| Agent | `internal/execx/` (N: ein Exec-Pfad), `internal/probe/` (N: Fühler, Ziel-Wächter, Feld-Freigabe, Zugangsbremse), `internal/discovery/` (N), `internal/credentials/` (N), `internal/monitor/plugins.go` (`runTimed`, `:62`, ruft nur noch `execx.Run`), `internal/monitor/monitor.go` (`Push`, `:182`), `internal/monitor/report.go` (`buildReportWithState`, `:31`; `report_version`, `:64`; `PushReport`, `:141`), `internal/monitor/reportstate.go`, `internal/config/paths.go`, `cmd/adminhelper-agent/main.go` (Subcommand `monitor credential`, neben `monitor init`/`push`, `:234`) |
| Desktop-UI | nur `src/lib/models/monitoring.ts` (`PUSH_ONLY_CHECK_TYPES`, `:177`) und `src/lib/api/types.ts` (`MonitorCheckType`, `:214`) um `probe`, damit „Jetzt prüfen“ korrekt gesperrt ist |
| Doku | `docs/admin/monitoring.html`, `docs/admin/agent-deployment.html`, `docs/developer/monitoring.html`, `docs/developer/agent.html`, `docs/developer/api-reference.html` (je DE+EN), `changelog.d/arch-monitoring-module.md` |

Gateway: `:443` leitet `location /` schon an den Server (`apps/gateway/nginx.conf:132`); keine Änderung.

## Datenmodell / API / Migrationen

### Ablauf

```
Agent-Lauf (alle 5 min)
  1. GET  /api/monitoring/agent/{id}/plan   (mTLS + Agent-Key; Fehler → zuletzt gespeicherter Plan)
  2. Kern-Collector wie heute; optionale Collector nach Takt und Selbstbremse
  3. fällige Proben laut Plan (Takt-Planer), dann ggf. Erkennung (fällig oder scan=true)
  4. POST /api/monitoring/agent/{id}/report (report_version 4, additive Blöcke)
Monitoring-Dienst
  Plan  = Probe-Checks des Servers + Marker-Suchliste des Katalogs + Scan-Flag
  Report: probes → Check-Typ probe; discovery → Inventar speichern, Abgleich, Funde; self → Metriken
```

Die Plan-Route spiegelt `proxy_agent_report` (`apps/server/app/modules/monitoring_proxy/router.py:108`): dieselben
Abhängigkeiten `require_cert_server` und `require_scope(SCOPE_AGENT)`, ein eigener Ratenzähler je Adresse, der
Monitoring-Dienst prüft den Agent-Key wie bei `/report` (`apps/monitoring/app/routers/agent.py:43`).

### Plan (Monitoring → Agent), `plan_version: 1`

```json
{
  "plan_version": 1,
  "catalog_version": "sha256:…",
  "scan": false,
  "discovery": {"markers": [{"id": "example.config", "paths": ["/etc/example"], "packages": ["example"]}]},
  "probes": [
    {
      "id": "<check-id>", "sensor": "http", "interval_s": 900, "timeout_s": 10,
      "target": {"kind": "container", "name": "example-web-1", "port_hint": 8000, "scheme": "http"},
      "params": {"path": "/api/status/", "method": "GET"},
      "fields": ["database.status", "tasks.celery_status"],
      "credential": {"ref": "example/default", "use": "bearer"}
    }
  ]
}
```

- `target.kind`: `loopback` · `container` · `process` · `unit` · `port`; der Agent löst den tatsächlich lauschenden
  Port auf (Hinweis-Port, sonst der einzige, sonst Status `ambiguous_target`).
- `params` hängt am Fühler; der Monitoring-Dienst prüft sie beim Laden des Katalogs mit einem Modell je Fühler, der
  Agent prüft sie noch einmal und meldet unbekannte als `invalid`.
- `credential.use`: `bearer` · `basic` · `header:<Name>` · `redis_auth` · `none`.

### Report-Blöcke (Agent → Monitoring), `report_version: 4`, alle additiv

```json
{
  "probes": {"<check-id>": {"ts": 1762700000, "duration_ms": 12, "status": "ok",
                             "values": {"database.status": "OK"}, "error": ""}},
  "discovery": {"ts": 1762700000, "duration_ms": 900, "partial": false,
                "units": [{"name": "nginx.service", "state": "active", "sub": "running"}],
                "sockets": [{"proto": "tcp", "addr": "0.0.0.0", "port": 443, "process": "nginx", "container": ""}],
                "containers": [{"id": "…", "name": "…", "image": "…", "compose_project": "…", "compose_service": "…",
                                "state": "running", "health": "healthy", "ports": [{"private": 8000, "public": 8000, "proto": "tcp"}],
                                "mounts": ["/data"]}],
                "markers": {"example.config": true},
                "ports": [{"port": 8443, "proto": "tcp", "protocol": "https"}]},
  "credentials": {"example/default": true},
  "self": {"collectors": {"docker": {"duration_ms": 210, "cpu_ms": 40, "timeouts": 0, "factor": 1, "throttled": false}}}
}
```

- `probes[id].status`: `ok` · `error` · `denied` (Zugangsbremse aktiv) · `not_allowed` (Ziel keine eigene Adresse) ·
  `unsupported` (Plattform) · `ambiguous_target` · `invalid` · `no_credential`. Der Agent schickt in jedem Report das
  letzte Ergebnis jeder Probe mit seinem `ts`; so bewertet der Monitoring-Dienst ohne Zustand die Frische.
- `values`: nur die in `fields` verlangten Felder, nur Skalare (Zahl, Text, Wahrheitswert), Text auf 256 Zeichen
  gekürzt, höchstens 32 Felder je Probe.
- `discovery` nur in dem Lauf, in dem eine Erkennung lief; nie Konfig-Inhalte, Kommandozeilen, Umgebungsvariablen oder
  Schlüssel (Konzept §3.5). Obergrenzen: 1000 Units, 1000 Sockets, 500 Container.
- `credentials`: Verweise mit `true`, nie Werte oder Hashes.
- `self.collectors[name].throttled`: dieser Collector lief in diesem Lauf nicht (Selbstbremse). Der Monitoring-Dienst
  wertet dann die Push-Checks, die von ihm leben (`docker_health` ← `docker`, `proxmox_backup` ← `proxmox`,
  `zfs_health` ← `zfs`, `smart_health` ← `smart`), in diesem Report nicht aus und behält ihren Zustand.

### Monitoring-API (Admin, über den Server-Proxy)

| Route | Zweck |
|---|---|
| `GET /catalog` | Module mit Name, Version, Karten-Kennzahlen, Checks (für die Karten) |
| `GET /discovery/{server_id}` | letzter Scan, angeforderter Scan, hinterlegte Zugangsdaten (nur Verweise) |
| `POST /discovery/{server_id}/scan` | „Jetzt scannen“ (setzt das Flag, idempotent) |
| `GET /findings?server_id=&status=` | Funde-Eingang |
| `POST /findings/{id}/adopt` · `POST /findings/adopt-all?server_id=` | übernehmen: Checks anlegen bzw. scharf schalten; bei „verschwunden“ die Checks der Instanz abschalten (nie löschen) |
| `POST /findings/{id}/dismiss` | ignorieren (bleibt ignoriert, bis sich der Fund ändert) |

Check-Antworten tragen zusätzlich `module_id`, `module_instance`, `silent`.

### Migration (Monitoring, eine Alembic-Revision)

- `monitor_discovery`: `server_id` (PK), `scanned_at`, `next_scan_at`, `scan_requested_at`, `inventory` (Text, JSON),
  `credentials` (Text, JSON), `updated_at`. Der erste Scan eines Hosts läuft sofort, danach liegt `next_scan_at`
  24–48 h (zufällig) nach dem letzten Scan; `scan_requested_at` erzwingt einen Scan im nächsten Plan.
- `monitor_findings`: `id` (PK), `server_id` (Index), `module_id`, `instance_key`, `kind` (`new` · `changed` · `gone`),
  `status` (`open` · `adopted` · `dismissed`), `summary` (Text, JSON), `catalog_version`, `first_seen`, `last_seen`,
  `decided_at`; eindeutig über (`server_id`, `module_id`, `instance_key`).
- `monitor_checks` + `module_id` (Index), `module_instance`, `module_check_key`, `silent` (Boolean, Standard
  `false`, `server_default` `false`).

Rein additiv; Downgrade entfernt Tabellen und Spalten. `server_cleanup.py` räumt die neuen Tabellen beim Löschen eines
Servers mit ab.

### Katalog

Ein Modul je Datei unter `apps/monitoring/app/catalog/modules/` als Python-Daten (`MODULE = {...}`), beim Start mit
Pydantic geprüft; ungültige Module lassen den Test rot werden, nicht den Dienst. `catalog_version` ist der SHA-256 über
die kanonische JSON-Form aller Module. Ein Modul: `id`, `name`, `version`, `detect` (`container_image`-Präfixe,
`units`, `processes`, `markers`, `port_hints`), `instance` (`compose_project` · `container` · `unit` · `process` ·
`port`), `checks` (je `key`, `sensor`, `target`, `params`, `interval`, `fields`, `rules`, `credential`, `test_object`),
`card` (Kennzahlen). `test_object: true` verlangt einen Takt von mindestens 15 min (Kevin 2026-11-09, Frage 10).

## Externe Integrationen

Keine neue externe API. Die Fühler sprechen lokale Protokolle; vor der Implementierung je Task in der Primärquelle
nachlesen (nicht verifiziert, bis dort gelesen): SMTP (RFC 5321, STARTTLS RFC 3207), IMAP (RFC 9051), POP3 (RFC 1939,
STLS RFC 2595), LDAP StartTLS (RFC 4511 §4.14), PostgreSQL SSLRequest (postgresql.org, „Message Flow“), FastCGI
(Spezifikation), Redis `INFO` (redis.io), HAProxy `show stat` (Management Guide), systemd `systemctl show`
(freedesktop.org), `journalctl --after-cursor`/`--show-cursor` (freedesktop.org), Docker Engine API über die CLI
(`docker ps`, `docker inspect`).

## Trade-offs & Alternativen

- **Plan holen (gewählt) statt Plan in der Report-Antwort:** Die Antwort auf `POST /report` käme ohne neue Route aus,
  aber „Jetzt scannen“ und neu übernommene Checks wirkten erst nach bis zu 10 min, und der Plan wäre an den Report
  gekoppelt. Das Konzept verlangt „nach höchstens 5 min; der Agent fragt den Server“. Kosten: eine weitere
  Agent-Route im Server-Proxy (Risikopfad, `security`), ein GET je Lauf.
- **Katalog als Python-Daten statt JSON/YAML:** YAML bräuchte eine neue Abhängigkeit, JSON trägt keine Kommentare;
  gerade das Warum eines Takts („Status-Seite ist teuer“) gehört an den Eintrag. Python-Dateien sind trotzdem reine
  Daten (ein Dict, Prüfung per Pydantic, kein Code im Modul).
- **Ports im Agent auflösen statt beim Übernehmen festschreiben:** Ändert sich der Port eines Containers, folgt der
  Check ohne neuen Fund; das Konzept verlangt „immer den tatsächlich lauschenden Port“.
- **Letztes Ergebnis je Probe in jedem Report statt nur bei Ausführung:** etwas größerer Report, dafür bewertet der
  Monitoring-Dienst ohne Zustand und erkennt veraltete Proben am `ts`.
- **`sql` über die Client-Programme (`mariadb --protocol=socket`, `runuser -u postgres -- psql`) statt Go-Treibern:**
  keine neuen Abhängigkeiten, Anmeldung genau wie der Admin lokal (unix_socket bzw. peer), feste Abfragen im Agent;
  fehlt das Programm, meldet der Fühler `unsupported`.
- **Selbstbremse nur für optionale Collector:** CPU, RAM, Platten, Last, Netz und Dienste sind billig und tragen die
  Basis-Checks; sie laufen immer. Gebremst werden `docker`, `proxmox`, `zfs`, `smart`, Proben und die Erkennung.
  Erholung: nach drei Läufen im Zeitlimit halbiert sich der Faktor wieder; Höchstfaktor 8.

## Risiken & Rollback

- **Kompromittierter Server:** Er kann einem Agent nur Parameter für einkompilierte Fühler schicken. Grenzen im
  Agent, nicht im Katalog: Ziele nur Loopback, eigene Adressen und eigene Container (geprüft an der tatsächlich
  verbundenen Adresse, also auch gegen DNS-Rebinding), HTTP nur GET/HEAD ohne Weiterleitung auf fremde Hosts, nur
  skalare Felder mit Längengrenze, Proben höchstens alle 5 min, Zugangsdaten nur an das Ziel der Probe, die sie
  nennt. Restrisiko: Er kann einzelne Felder lokaler Lese-Endpunkte abfragen lassen, auch mit hinterlegten
  Zugangsdaten. Das folgt aus dem Modell „Server schickt Parameter“ (Konzept §3.8) und steht in der Doku.
- **Last auf Kundendiensten:** Takt im Katalog, Testobjekte ≥ 15 min, Selbstbremse, Zugangsbremse; Erkennung mit
  eigenem Zeitrahmen (60 s) und Timeout je Teil; die Protokollerkennung fasst Port 22, 3306 und 9100–9107 sowie
  Ports von `sshd`, `mysqld`, `mariadbd` nie an und schickt an Unbekanntes nie einen `Host`-Kopf.
- **Report-Pfad:** neue Blöcke werden je Block isoliert ausgewertet; ein kaputter Block verwirft nicht den Report.
- **Alte Agenten / alter Dienst:** Agent ≤ v3 ruft keinen Plan ab und schickt keine neuen Blöcke; ein neuer Agent
  gegen einen alten Dienst bekommt 404 auf den Plan und arbeitet wie bisher (Log auf Info, kein Fehler).
- **Rollback:** Revert des Merge-Commits; die Migration ist additiv und hat ein Downgrade. Die Zugangsdaten-Datei
  bleibt auf den Hosts liegen (nur root lesbar).

## Doku-Impact

Neu bzw. erweitert, DE+EN: `docs/admin/monitoring.html` (Module, Funde-Eingang, Jetzt scannen, stille Checks, Zugangsdaten),
`docs/admin/agent-deployment.html` (`adminhelper-agent monitor credential`), `docs/developer/monitoring.html` (Katalog, Abgleich, Check-Typ
`probe`, Datenvertrag), `docs/developer/agent.html` (Fühler, Ziel-Wächter, Takt-Planer, Selbstbremse, Report v4),
`docs/developer/api-reference.html` (neue Routen); `changelog.d/arch-monitoring-module.md`.

## Entscheidungen

- **Kevin 2026-11-09 (Monitoring-Konzept §10, übernommen):** Fühler und Module als Architektur (1) · Zugangsdaten
  lokal auf dem Host, Datei nur für root, gesetzt über den Desktop per SSH, der Server weiß nur „hinterlegt“ (3) ·
  keine LAN-Sonde: Agenten prüfen nur ihren eigenen Host (4) · nur eine Freigabeliste, die bekannten Fallen nur als
  Prüfliste/Negativtest · Testobjekt-Endpunkte erlaubt, nur alle 15 min, im Katalog markiert (10) · nur IPMI lokal
  (11) · SQL Server nur Dienst und Ereignisse (13) · keine Außensonde, kein Label „nur intern geprüft“ (9b) · Totmann
  nur als Desktop-Warnung (9c) · alles vor 0.47.0 (8).
- **Kevin 2026-11-09 (Konzept §3.5, §3.6, §3.13):** Erkennung alle 24 h mit Versatz 24–48 h; Ports nie fest annehmen;
  Zugangsbremse bei 401/403; Feld-Freigabe; neue Checks starten still.
- **Session 2026-11-09:** R-1224 fährt im Folgezug `arch-monitoring-module-2` (15-Task-Grenze, `/feature-plan` §3a).
- **Session 2026-11-09:** „Neue Checks still“ heißt: Übernimmt der Admin einen Fund, alarmieren dessen Checks sofort
  (das Übernehmen ist die Zustimmung). Bringt ein Katalog-Update einer übernommenen Instanz neue Checks, laufen diese
  still und erscheinen als Fund „geändert“, bis der Admin ihn übernimmt.
- **Session 2026-11-09:** Plan per `GET` statt in der Report-Antwort; Katalog als Python-Daten; Ports im Agent
  auflösen; `sql` über die Client-Programme; Selbstbremse nur für optionale Collector (Trade-offs oben).
- **Session 2026-11-09:** Die Bedienung „Desktop setzt Zugangsdaten per SSH“ baut `arch-monitoring-ui`; dieser Zug
  liefert die Agent-CLI `adminhelper-agent monitor credential set|delete|list` (Geheimnis nur über stdin), die der Desktop
  per SSH aufruft.

## Offene Fragen

Keine, die den Bau aufhält. Am Gate genannt: R-1224 wandert in den Folgezug; das Windows-Ereignisprotokoll im Fühler
`log` kommt mit Welle W4.
