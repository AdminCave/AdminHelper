# frps prüft Proxy-Anmeldungen gegen die Tunnel des Servers

Roadmap: R-1215. Architektur-Vorhaben (`start-session.sh arch R-1215`), kein Release-Gate für 0.47.0.
Stand der Zeilenangaben: `origin/main@698a91006`, frp v0.72.0.

## Problem / Motivation

Welche Proxies ein Host bei frps anmeldet, legt heute allein das frpc.toml fest, das der Server für diesen Host
erzeugt (`generate_frpc_toml`, `apps/server/app/modules/frp/config_generator.py:419`): `user` = Server-ID,
Proxy-Name = Tunnel-ID, Typ `stcp` oder `https`, bei `https` die `customDomains` des Tunnels. frps selbst kennt
diese Zuordnung nicht. Er prüft beim Anmelden Token und Zertifikat, beide gelten für jeden Host gleich, und danach
nur, ob ein Proxy-Name oder eine Domain schon vergeben ist. Die Zuordnung Host ↔ Tunnel steht damit nur in der
Datenbank des Servers und im Wohlverhalten jedes frpc.

Das Vorhaben macht sie an frps verbindlich: frps lässt nur Proxies zu, die der Server für genau diesen Host erzeugt
hat, mit genau den Feldern, die der Generator schreibt.

## Ziel & Nicht-Ziele

**Ziel**
1. Jede Proxy-Anmeldung an frps läuft über ein Server-Plugin (frp-Op `NewProxy`). Es lässt die Anmeldung nur zu,
   wenn sie zu einem aktiven Tunnel des anmeldenden Hosts passt, und lehnt alles andere ab (fail-closed: ohne
   Plugin, ohne Policy oder bei einem Fehler meldet sich kein Proxy an).
2. Jeder Host weist sich je Proxy mit einem eigenen Schlüssel aus, den der Server aus `SECRET_KEY` und der Server-ID
   ableitet und ins frpc.toml schreibt. Ein Host kennt nur seinen eigenen.
3. Der Server schreibt die erlaubten Proxies je Host als Policy-Datei in das frps-Konfigurationsverzeichnis, aus
   derselben Auswahl (`active_tunnels`, `config_generator.py:296`), aus der er die frpc.toml erzeugt.
4. Bestehende Installationen laufen nach dem Update ohne Handarbeit weiter: die Agents holen das neue frpc.toml mit
   ihrem nächsten Sync (alle 5 min, `apps/agent/cmd/adminhelper-agent/run.go:25`), ältere Agents reichen den neuen
   Schlüssel unverändert durch (Proxy-Tabellen nehmen jeden Schlüssel außer `plugin*`,
   `apps/agent/internal/frpc/servertoml.go`).

**Nicht-Ziele**
- Keine Änderung an frp selbst (kein Fork), kein eigenes Login-Verfahren, keine Änderung am Visitor-Weg des Desktops.
- Keine Datenbank-Migration, keine neue API, keine neue Oberfläche.
- Keine Änderung an doppelten Domains zwischen Tunneln: was der Server erzeugt, lässt das Plugin zu; Konflikte löst
  frps wie heute.
- Das Plugin ändert den Inhalt einer Anmeldung nie (`unchange: true`), es entscheidet nur.

## Betroffene Komponenten & Dateien

| Komponente | Dateien | Änderung |
|---|---|---|
| Server | `apps/server/app/modules/frp/proxy_key.py` (neu), `config_generator.py`, `schemas.py` (`_GENERATOR_PROXY_KEYS`, `:67`) | Host-Schlüssel ableiten; jede `[[proxies]]`-Tabelle trägt `metadatas.ahProxyKey`; der Schlüssel zählt zu den Generator-Schlüsseln, `extra_config` darf ihn nicht setzen |
| Server | `apps/server/app/modules/frp/policy.py` (neu), `tunnel_router.py` (`:156`, `:247`, `:353`), `config_router.py` (`:109`, `:192`), `servers/router.py` (`:234`), `main.py` (`_run_startup_tasks` `:384`, `lifespan` `:402`) | Policy bauen und atomar schreiben: nach jedem Commit, der Tunnel ändert, beim Start und periodisch im Server-Prozess |
| Agent-Modul (Go) | `apps/agent/internal/frpspolicy/` (neu), `apps/agent/cmd/frps-policy/` (neu) | das Plugin: HTTP-Server auf Loopback, liest die Policy, entscheidet `NewProxy` |
| frps-Image | `apps/frps/Dockerfile`, `apps/frps/Dockerfile.dockerignore` (neu), `apps/frps/frps-supervisor.sh` | mehrstufiger Build (Go-Stufe baut das Plugin), Supervisor startet und überwacht das Plugin und hängt den `[[httpPlugins]]`-Block an seine geprüfte Kopie von frps.toml |
| Build/CI | `docker-compose.test.yml` (`:80`), `.github/workflows/ci.yml` (`:92-97`, `:956`), `.github/workflows/docker.yml` (`:51`) | Build-Kontext des frps-Images wird die Repo-Wurzel; die Image-Tests ziehen jede Basis eines mehrstufigen Dockerfiles |
| Tests | `apps/server/tests/test_config_generator.py`, `test_frp_toml_roundtrip.py`, `test_compose_frps.py`, `test_release_images.py`, neue Testdateien je Task | |

Das Plugin liegt im Go-Modul des Agents, weil es dort Toolchain, `verify.sh agent`, die CI-Jobs (Linux und Windows),
`govulncheck` und die Lizenzprüfung schon gibt; ein eigenes Modul bräuchte neue Harness- und CI-Pfade. Es benutzt
nur die Standardbibliothek. Die Paketbauten (`build-deb.sh`, `build-rpm.sh`) und der Cross-Build bauen weiter nur
`./cmd/adminhelper-agent`, das Plugin landet nur im frps-Image.

## Datenmodell / API / Migrationen

- **Keine** Alembic-Migration, keine API-Änderung, kein OpenAPI-Drift. Server ↔ Web ↔ Desktop unverändert.
- **frpc.toml (Server → Agent):** neu je `[[proxies]]` die Zeile `metadatas.ahProxyKey = "<hex>"`.
  `ahProxyKey = HMAC-SHA256(K, "frp-proxy-v1:" + server_id)`, `K = HMAC-SHA256(SECRET_KEY, "adminhelper/frp-proxy-key")`.
  Ein Wechsel von `SECRET_KEY` ändert alle Schlüssel; die Agents holen sie mit dem nächsten Sync.
- **Policy-Datei (Server → Plugin):** `FRP_CONFIG_DIR/frps-policy.json` (im frps-Container `/etc/frp`, read-only),
  0644, atomar ersetzt, deterministisch sortiert, außerhalb des Eingabe-Hashes des Supervisors (eine Änderung
  startet frps nicht neu). Inhalt je Server-ID: SHA-256 des Schlüssels; je Tunnel-ID Typ, `customDomains`,
  `subdomain`, `loadBalancer.group` und SHA-256 von `loadBalancer.groupKey`, jeweils genau so, wie der Generator sie
  für diesen Tunnel schreibt (aus `extra_config`, leer sonst). Die Datei enthält keinen Schlüssel im Klartext. Das
  Format hat ein Feld `version`; Server-Test und Go-Test lesen dieselbe Fixture
  (`apps/agent/internal/frpspolicy/testdata/`).
- **frps.toml:** unverändert vom Server. Der Supervisor hängt an seine geprüfte Kopie einen festen Block
  `[[httpPlugins]]` (`ops = ["NewProxy"]`, Adresse auf `127.0.0.1`) und lehnt `[[httpPlugins]]` im Eingang weiter ab.

## Externe Integrationen

frp Server-Plugins (v0.72.0): <https://github.com/fatedier/frp/blob/v0.72.0/doc/server_plugin.md>, Konfiguration
`[[httpPlugins]]` (`name`, `addr`, `path`, `ops`) laut `conf/frps_full_example.toml` derselben Version.
Verifiziert am Quelltext v0.72.0:
- `NewProxy` trägt `user` (`user`, `metas`, `run_id`), `proxy_name` (frpc setzt den Präfix `user.` selbst), `proxy_type`,
  `custom_domains`, `subdomain`, `group`, `group_key` und die Proxy-Metadaten `metas`; die Antwort
  `{reject, reject_reason, unchange, content}`.
- Jeder Fehler beim Plugin-Aufruf lehnt die Anmeldung ab. frps ruft das Plugin ohne eigenes Timeout und synchron im
  Lese-Loop der Client-Verbindung: das Plugin muss selbst kurze Timeouts setzen und darf nicht hängen.
- frpc versucht eine abgelehnte Anmeldung nach rund 30 s erneut.
- Das frps-Dashboard gibt die Proxy-Metadaten aus.

Nicht verifiziert: ob frps Domains vor dem Vergleich normalisiert (Groß-/Kleinschreibung); das Plugin vergleicht
exakt mit dem, was der Generator schreibt.

## Trade-offs & Alternativen

| Variante | Für | Gegen |
|---|---|---|
| **A: Server-Plugin `NewProxy` + Schlüssel je Host in den Proxy-Metadaten + Policy-Datei** (Empfehlung) | frp bleibt unverändert; alte Agents funktionieren; keine Migration; fail-closed; prüft genau das, was der Generator schreibt | ein zweiter Prozess im frps-Container; Policy kann bis zum nächsten Schreiben veralten; Image-Build wird mehrstufig |
| B: Zuordnung über das mTLS-Zertifikat | stärkste Bindung | frp reicht dem Plugin keine Zertifikatsdaten durch; ginge nur mit einem frps-Fork |
| C: eigenes Token je Host über die Op `Login` | bindet schon die Verbindung | der Schlüssel müsste in die Login-Metadaten (Wurzel-Schlüssel des frpc.toml), die heutige Agents ablehnen: alle Agents müssten vor dem Server aktualisiert werden |
| D: Schlüssel als Datenbankspalte statt abgeleitet | einzeln rotierbar | Migration, neues Geheimnis in der DB; Rotation je Host ist heute nicht gefragt |
| E: Plugin in Python im Server-Image | eine Sprache weniger im frps-Image | frps sitzt allein im Netz `frpedge` und erreicht den Server nicht; ein Python-Prozess im frps-Image wäre ein zweiter Laufzeit-Stack |

Plugin-Port: der Supervisor nimmt einen festen Standard-Port auf Loopback und weicht aus, wenn `bindPort`,
`vhostHTTPSPort` oder `webServer.port` ihn belegen; so braucht es keine neue API-Ablehnung.

## Risiken & Rollback

- **Tunnel nach dem Update kurz weg:** frps startet mit dem neuen Image neu, die Agents melden sich ohne Schlüssel
  an, bis ihr nächster Sync das neue frpc.toml bringt (bis 5 min, offline länger). Ein Übergangsfenster ohne
  Prüfung ist bewusst nicht vorgesehen (Frage 1).
- **Manuell verteilte frpc.toml** (Download, ZIP) tragen keinen Schlüssel und werden nach dem Update abgelehnt, bis
  sie neu verteilt sind (Frage 2).
- **Plugin fällt aus:** neue Anmeldungen scheitern (fail-closed), bestehende Proxies bleiben. Der Supervisor prüft
  das Plugin bei jedem Poll mit kurzem Timeout, beendet es bei Ausbleiben hart und startet es neu; das Log nennt
  jeden Neustart.
- **Policy veraltet:** geschrieben nach jedem Commit, der Tunnel ändert, beim Start und periodisch im Server-Prozess
  (Ziel ≤ 60 s). Mehrere Worker schreiben denselben deterministischen Inhalt atomar.
- **Rollback:** Revert des PRs und das alte frps-Image; der zusätzliche Schlüssel im frpc.toml stört frps ohne
  Plugin nicht (frps nimmt Metadaten an). Keine Daten zu migrieren.

## Doku-Impact

`docs/admin/frp-tunnel.html` DE+EN (Prüfung der Anmeldungen, Verhalten nach dem Update, manuell verteilte frpc.toml,
`SECRET_KEY`-Wechsel), `docs/admin/betrieb.html` / `docs/en/admin/operations.html` (zweiter Prozess im
frps-Container, Zustand im Supervisor), `docs/developer/server.html` DE+EN (Policy-Datei, Schlüssel), weitere Seiten
mit dem Build des frps-Images per grep (`apps/frps`, `cicd.html`); `changelog.d/arch-frps-identity.md`.

## Offene Fragen

1. **Update ohne Übergangsfenster** — Empfehlung: hinnehmen und in CHANGELOG und Doku nennen (Tunnel bis zum
   nächsten Agent-Sync weg). Ein Fenster ohne Prüfung käme als eigene Task dazu.
2. **Manuell verteilte frpc.toml** — Empfehlung: hinnehmen und in der Doku nennen (nach dem Update neu verteilen).
3. **Schwere Prüfung** — Empfehlung: `scenario --tunnel` vor dem Merge (echter Datenpfad Agent → frps → Visitor);
   ask-first.
4. Hinweis: der PR ändert `.github/workflows/`, Kevin merged ihn.
