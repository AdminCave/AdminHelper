<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-20 — Katalog-Updates als Angebot, Grabsteine für Modul-Checks, Fühler-Erweiterungen

Roadmap: R-1264 (Folgearbeit Monitoring-Module), R-1301 (compose_project-Fund nennt den Container). Kevin 2026-11-10
Triage; 2026-11-11: Grabsteine als eigene Tabelle per Alembic-Migration, geänderte Definitionen als Update verfügbar
anbieten, kein automatischer Rollout; R-1301: Container-Feld außerhalb des Summary-Vergleichs.

## Problem / Motivation

- **Katalog-Update:** `sync_catalog` (`apps/monitoring/app/module_sync.py`) legt beim Start nur neue Checks an (still)
  und meldet entfallene. Ändert der Katalog die Definition eines bestehenden Checks (Pfad, Regel, Schwelle), erfährt
  der übernommene Check davon nie.
- **Grabsteine:** Löscht ein Admin einen Modul-Check, legt ihn der nächste Abgleich oder das erneute Übernehmen
  (still) wieder an (arch-monitoring-module, Entscheidung T6). Für Vorlagen-Checks gibt es dafür
  `monitor_check_tombstones`, für Modul-Checks nicht.
- **R-1301:** Ein Fund eines `compose_project`-Moduls nennt nur die Dienste und ihre Images, nicht den Container, an
  den die Checks gebunden werden. Stünde der Name in der Summary, würde nach dem Update jeder compose-Fund `changed`
  (`_seen_again` in `apps/monitoring/app/discovery.py` vergleicht die ganze Summary).
- **Fühler:** `proto` kennt nur STARTTLS, kein implizites TLS (IMAPS 993, POP3S 995, SMTPS 465, LDAPS 636, Redis mit
  TLS). Redis nimmt nur `AUTH <passwort>`, keinen ACL-Nutzer. `DnsParams.name` verlangt `_HOSTNAME` ohne Unterstrich,
  der Agent (`sensor_dns.go`, `dnsName`) nimmt ihn: SRV-Namen wie `_ldap._tcp.<domain>` weist der Server ab.
  `UnixSocketParams.path` erlaubt 1024 Zeichen, der Agent höchstens 107 (`maxSocketPath`, `sun_path`).
- `fastcgi status_path` ist schon gebaut (Agent `sensor_proto.go` `statusPath`, Server `ProtoParams`/
  `UnixSocketParams`), der Teilpunkt der Zeile ist erledigt.

## Ziel & Nicht-Ziele

**Ziel:**

1. Jeder Modul-Check trägt den Hash seiner Katalog-Definition. Weicht der Katalog ab, öffnet der Start-Abgleich den
   Fund als `changed` und nennt die Checks mit neuer Definition (`updatableChecks`). Erst das Übernehmen schreibt die
   neue Konfiguration. Kein automatischer Rollout (Kevin).
2. Ein gelöschter Modul-Check hinterlässt einen Grabstein (Server, Modul, Instanz, Check-Schlüssel) in einer eigenen
   Tabelle (Kevin). Abgleich und Übernehmen legen ihn nicht wieder an. Das Löschen des Servers räumt die Grabsteine
   mit ab.
3. Der compose-Fund nennt den gebundenen Container je Dienst im Feld `containers`. `_seen_again` vergleicht die
   Summary ohne dieses Feld (Kevin). Die Desktop-Inbox zeigt ihn.
4. `proto` mit `tls: true` (implizites TLS, ohne Zertifikatsprüfung wie `http`); Redis-Zugang `redis_acl`
   (Geheimnis `user:password`, `AUTH <user> <passwort>`); `DnsParams.name` mit Unterstrich wie der Agent;
   `UnixSocketParams.path` höchstens 107 Zeichen.

**Nicht-Ziele:** automatischer Rollout geänderter Definitionen; ein Grabstein zurücknehmen per UI (das erneute
Anlegen von Hand bleibt möglich: ein von Hand angelegter Check ist kein Modul-Check); Änderungen an Vorlagen-Grabsteinen.

## Betroffene Komponenten & Dateien

- **Monitoring:**
  - `alembic/versions/<neu>_module_check_tombstones.py`: Tabelle `monitor_module_tombstones`
    (`id`, `server_id`, `module_id`, `instance_key`, `check_key`, `created_at`, eindeutig über die vier
    Schlüssel) und Spalte `monitor_checks.module_check_hash` (nullable).
  - `app/models.py`, `app/module_sync.py` (`_create`, `_adopt`, `sync_catalog`), `app/routers/checks.py`
    (`delete_check`), `app/server_cleanup.py`, `app/routers/findings.py` (`_finding_out`, `_adopt_out`),
    `app/discovery.py` (`_instances`, `_seen_again`).
  - `app/catalog/sensors.py` (`ProtoParams.tls`, `DnsParams.name`, `UnixSocketParams.path`), `app/catalog/model.py`
    (`Credential.use`), `app/check_configs.py` (`ProbeCredential`).
- **Agent:** `internal/probe/sensor_proto.go` (implizites TLS, `redis_acl`), `sensor_unixsocket.go` (`redis_acl`),
  `sensor_http.go` (Konstante), Tests `sensor_proto_test.go`.
- **Desktop-UI:** `components/monitoring/card/FindingsInbox.svelte` (+Test): Zahl der Checks mit neuer Definition,
  gebundener Container; Typen in `lib/api/types.ts`, Texte DE+EN in `lib/i18n/dictionaries.ts`.
- **Doku:** `docs/admin/monitoring.html`, `docs/developer/monitoring.html`, `docs/developer/agent.html`, je DE+EN;
  `changelog.d/kern-monitoring-20.md`.

## Datenmodell / API / Migrationen

- **Migration** (Kevin 2026-11-11): neue Tabelle, neue nullable Spalte; Downgrade entfernt beide. Altzeilen haben
  `module_check_hash = NULL`; der erste Start-Abgleich setzt ihn auf den Hash der heutigen Definition, ohne ein
  Update anzubieten (ohne Hash lässt sich eine frühere Änderung nicht belegen).
- **REST (additiv):** Fund `updatableChecks` (Check-IDs), Adopt-Antwort `updatedChecks`. Summary eines
  compose-Funds trägt `containers` (`{Dienst: Container}`). Der Server reicht die Antworten durch
  (`monitoring_proxy`), kein Schema-Wechsel dort.
- **Agent-Vertrag:** neuer Param `tls` bei `proto`, neuer Zugang `redis_acl`. Ein älterer Agent meldet beide
  `invalid`, der Check steht auf `unknown`.

## Externe Integrationen

- Redis `AUTH [username] password` (redis.io/docs/latest/commands/auth, ab Redis 6) — vor T6 an der Doku prüfen.
- Implizites TLS: RFC 8314 (IMAPS/POP3S/Submissions), LDAPS (RFC 4513 nennt Port 636 nicht normativ: „nicht
  verifiziert“ im Kommentar, wo nötig).

## Trade-offs & Alternativen

- **Hash statt Vergleich der gespeicherten Konfiguration:** Ein Vergleich `probe_config(...) != row.config` hielte
  jede Admin-Änderung für ein Katalog-Update. Der Hash der Katalog-Definition beim Anlegen trennt beides. Kosten: eine
  Spalte (Empfehlung).
- **Update über das Übernehmen statt eigener Route:** Das Übernehmen eines `changed`-Funds ist schon die
  Admin-Entscheidung über neue und entfallene Checks; neue Definitionen fügen sich dort ein. Eine eigene Route je
  Check wäre mehr Vertrag für dasselbe.
- **Container außerhalb der Summary-Spalte vs. Schlüssel in der Summary, aus dem Vergleich genommen:** Ein Schlüssel
  `containers`, den `_seen_again` beim Vergleich weglässt, braucht keine Migration (Empfehlung).

## Risiken & Rollback

- Migration auf einer großen `monitor_checks`-Tabelle: nur `ADD COLUMN` nullable, keine Umschreibung.
- Ein falscher Hash (etwa durch eine nicht deterministische Serialisierung) böte bei jedem Start ein Update an: der
  Hash nimmt `model_dump(mode="json")` mit sortierten Schlüsseln, ein Test prüft die Stabilität.
- Rollback: Revert des Merges und `alembic downgrade` um eine Revision.

## Doku-Impact

Admin-Doku Monitoring (Katalog-Updates, gelöschte Modul-Checks, Container im Fund, implizites TLS, Redis-ACL),
Entwickler-Doku Monitoring (Tabelle, Hash, Felder) und Agent (Params, Zugänge), je DE+EN; CHANGELOG-Fragment.

## Offene Fragen

1. **„credential use none“** (Titel R-1264): Gemeint sein kann (a) ein Zugang ohne Nutzung, der nur „hinterlegt“
   meldet, oder (b) ein optionaler Zugang, ohne den der Check trotzdem läuft. Der Code und die Ledger von
   arch-monitoring-module nennen es nicht. Task T8 steht auf `[?]`; Empfehlung (b), weil Redis und HTTP-Dienste
   oft ohne Passwort laufen und ein Check ohne hinterlegten Zugang sonst `no_credential` meldet.
