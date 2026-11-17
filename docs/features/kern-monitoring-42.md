# kern-monitoring-42 — vHosts von nginx und Apache im Container

Roadmap: R-1503.

## Problem
Die Erkennung liest vHosts nur von einem nginx oder Apache des Hosts (`WebVhosts` in
`apps/agent/internal/probe/web_vhosts.go`: `nginx -T`, `apache2ctl -S`/`apachectl -S`). Ein Webserver im Container
liefert keine vHosts, also keine Instanzen von `web_domain` und keinen Zertifikats-Check; die Doku nennt das als
„Nicht abgedeckt: vHosts eines Webservers im Container“ (`docs/admin/monitoring.html`, Abschnitt `app-module-vhosts`).

## Ziel und Nicht-Ziele
- Ziel: Für jeden laufenden Docker-Container mit nginx oder Apache (httpd) und mindestens einem veröffentlichten
  TCP-Port meldet die Erkennung dessen vHosts, wie die des Hosts, mit dem **Host-Port** der Veröffentlichung.
  Die Checks von `web_domain` (Handshake, Zertifikatsdatei gegen ausgeliefertes Zertifikat) laufen dann gegen diesen
  Host-Port.
- Kevin 2026-11-17: Die Konfiguration holt der Agent per Docker-Archiv-GET (`docker cp <container>:<pfad> -`, das
  CLI zu `GET /containers/{id}/archive`) und liest sie mit eigenem Parser; **kein `docker exec`**. Für ein
  Include-Muster holt er das Archiv des Verzeichnisses und wirft Einträge, die nicht passen oder nach Schlüssel
  aussehen (`*.key`, `*.pem`), ungelesen weg; Deckel 4 MiB je Container.
- Kevin 2026-11-15 gilt weiter: nur Domainnamen gehen an den Server, nie Pfade, Konfigurationstext oder
  Dateiinhalte; der private Schlüssel eines Zertifikats wird nie geöffnet.
- Nicht-Ziele: die Anwendung im Dokumentverzeichnis (`App`) eines Container-vHosts (die liegt meist in einem anderen
  Container; Container-Anwendungen erkennen die Image-Module); ein vHost auf einem nicht veröffentlichten Port;
  Podman, rootless Docker, Kubernetes; der Hauptserver von Apache ohne `<VirtualHost>`; andere Webserver (Caddy,
  Traefik haben eigene Module).

## Betroffene Komponenten und Dateien
- Agent (`apps/agent/`):
  - `internal/allowlist/allowlist.go` (+ Test): `docker cp -- <container>:<ctrpath> -` mit Container-ID (64 hex) und
    einem einfachen absoluten Pfad als neuer Klasse.
  - neu `internal/probe/web_vhosts_container.go` (+ Test): Container finden (Inspect: läuft, `Path`/`Args` nennen
    nginx, httpd, `httpd-foreground`, `apache2-foreground`), Archiv holen und lesen (`archive/tar`, Deckel, Links,
    Muster, Schlüssel-Einträge), für nginx einen Dump in der Form von `nginx -T` bauen und `nginxVhosts` lesen
    lassen, für Apache die `<VirtualHost>`-Blöcke aus den Dateien lesen (`apacheDirectives`, `block`).
  - `internal/probe/web_vhosts.go`: `WebVhosts` nimmt die Container-vHosts dazu; bei gleichem Namen und Port gewinnt
    der vHost des Hosts (`uniqueVhosts`).
  - `internal/probe/web_vhost_cert.go`: Liegt die Zertifikatsdatei im Container, holt der Agent sie einzeln per
    Archiv (Deckel `maxCertFileBytes`) statt `readCapped`; ein Schlüssel in derselben Datei bleibt ungeparst.
  - `internal/probe/sensor_local.go`: `dockerPublications` bzw. ein Geschwister liefert die Zuordnung je Container
    (ID → Container-Port → Host-Port).
- Server und Monitoring-Dienst: unverändert. Ein vHost ist dort `server`, `name`, `port`, `tls`, `app`; der Check
  `vhost` löst wie ein Port-Ziel über jeden Listener auf dem Host-Port auf (`resolveKind`, `target.go`), auch über
  `docker-proxy`, mit dem Wächter für veröffentlichte Ports.

## Datenmodell / API
Kein neues Feld, keine Migration. `Vhost` bekommt private Felder für den Container (ID, Pfad der Zertifikatsdatei
im Container); sie verlassen den Host nicht.

## Externe Integrationen
- Docker CLI `docker cp` (docs.docker.com/reference/cli/docker/container/cp/): „If `-` is specified for … `DEST_PATH`,
  you can also stream a tar archive … to `STDOUT`“; der Container darf laufen oder gestoppt sein; mit `-L` folgt es
  Links in `SRC_PATH`. Am Dev-Host (Docker 29.9.2) gegengeprobt: eine Datei ergibt ein tar mit einem Eintrag, ein
  Verzeichnis eines Bind-Mounts und eines Volumes kommt ganz, ein Link ohne `-L` kommt als Link-Eintrag (Ziel nicht
  gelesen). Die Doku nennt „mounts created by the user in the container“ als nicht kopierbar; die Probe zeigt
  Bind-Mount und Volume lesbar (nicht dokumentiert, Verhalten bei anderen Docker-Versionen nicht verifiziert).
- nginx: Include-Regeln wie heute (ngx_core_module.html#include), Prefix des Images `/etc/nginx`.
- Apache: `Include`/`IncludeOptional` (Muster erlaubt), `ServerRoot`, `<VirtualHost>`, `ServerName`, `ServerAlias`,
  `SSLEngine`, `SSLCertificateFile` (httpd.apache.org/docs/2.4/mod/core.html, mod_ssl.html).

## Trade-offs und Alternativen
- `docker exec nginx -T` wäre der kürzeste Weg, führt aber Code im Container aus: von Kevin verworfen.
- Lesen über `/proc/<pid>/root` (wie die Mailcow- und WordPress-Ansichten) ginge ohne Docker-Aufruf, verlangt aber
  root-Rechte am fremden Mount-Namensraum; Kevin hat das Archiv-GET gewählt.
- Links: Ohne `-L` kommt ein Link als Eintrag; der Agent folgt einem Link selbst (einmal je Pfad, höchstens 8 Stufen,
  nur absolute Ziele bzw. relativ zum Verzeichnis), statt `-L` zu setzen: so liest er nie das Ziel eines Links, das
  nach Schlüssel aussieht.

## Risiken und Rollback
- Ein großes Verzeichnis-Archiv: Der Agent liest den Strom höchstens bis 4 MiB je Container und bricht dann ab; der
  Container zählt als nicht ganz gelesen (die Erkennung meldet „unvollständig“ wie bei einem unlesbaren Host-nginx).
- Ein Schlüssel kommt im Strom eines Verzeichnis-Archivs mit (Docker packt das ganze Verzeichnis). Der Agent wirft
  den Eintrag ungelesen weg (`tar.Reader` springt über den Inhalt); er wird weder geparst noch gespeichert oder
  gemeldet. Hingenommen von Kevin (Glob-Antwort 2026-11-17).
- Rollback: Revert der Agent-Commits; der Server bleibt unverändert.

## Doku-Impact
`docs/admin/monitoring.html` und `docs/en/admin/monitoring.html` (Abschnitt `app-module-vhosts`, Inventar-Liste,
Zeile `web_domain`), `docs/developer/agent.html` DE+EN (Inventar der vHosts, `docker cp` in der Freigabeliste), `changelog.d/kern-monitoring-42.md`.

## Offene Fragen
Keine: Kevin hat Weg (Archiv-GET) und Glob-Verhalten am 2026-11-17 entschieden.
