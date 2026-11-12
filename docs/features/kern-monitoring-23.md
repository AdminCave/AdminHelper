# kern-monitoring-23 — Port-Erkennung: frps-Ports ohne Fehlalarm

Roadmap: R-1375 (BUG, Kevin 2026-11-12). Ledger: `tasks/kern-monitoring-23.md`.

## Problem / Motivation
Die Port-Erkennung legt für jeden nach außen lauschenden TCP-Port ohne bekanntes Modul eine Instanz des Moduls
`port` an; deren Check fragt mit `protocol: auto` (`apps/monitoring/app/catalog/modules/port.py`, Regel
`ok == False` → critical). Auf einem AdminHelper-Server mit frps stehen die frps-Ports dauerhaft auf critical:

- Bind-Port (Standard 7000, TLS only): nach dem TLS-Handshake schließt frps die Verbindung, `detail: closed+tls`.
- vhost-HTTPS-Port (Standard 7443, Routing nach SNI): ohne passenden Hostnamen schließt frps, `detail: closed`.

Ursache: `recognizeOn` (`apps/agent/internal/probe/sensor_proto.go:1022`) wertet eine Gegenstelle, die nach
gelungenem Connect ohne erkennbares Protokoll schließt, als `closed` ohne `ok`. Dazu schreibt frps bei jeder Probe
alle 15 Minuten eine Warnung ins Log.

## Ziel & Nicht-Ziele
Ziel (Kevins Entscheidung, beide Varianten):
1. **„closed“ ist kein Ausfall:** gelingt der TCP-Connect und erkennt `auto` kein Protokoll, ist das Ergebnis ok
   mit `detail` `unknown` (ohne TLS) bzw. `tls` (TLS-Handshake gelang). Critical bleibt ein Port, dessen Connect
   scheitert (refused, Timeout). Schließt die Gegenstelle schon vor dem `HEAD`, versucht der Agent wie nach einem
   stillen Port noch TLS.
2. **frps als eigener Dienst:** ein neues Katalog-Modul `frps` erkennt den frps-Container (Image
   `ghcr.io/admincave/adminhelper/frps`, dazu `snowdreamtech/frps`) und beansprucht ihn; seine veröffentlichten
   Ports werden damit keine `port`-Instanzen mehr. Sein Check fragt den Containerzustand (Sensor `container`).
3. Bestehende `port`-Checks für die frps-Ports gehen nach dem Update auf ok (durch 1); ihre Instanzen werden durch 2
   ein Fund „gone“, den der Admin übernimmt (das schaltet ihre Checks ab und beendet die Log-Warnungen).

Nicht-Ziele: kein frps-Protokoll-Check, keine Zertifikats-Restlaufzeit (beides R-1235, Modul AdminHelper selbst);
kein frps ohne Container (ein nackter frps-Prozess bleibt eine `port`-Instanz, die nach 1 ok ist); keine
Migration und keine automatische Übernahme von Funden.

## Betroffene Komponenten & Dateien
- Agent: `apps/agent/internal/probe/sensor_proto.go` (`recognize`, `recognizeOn`), `discover.go` (Doc-Kommentar
  der Namen), `sensor_proto_test.go`.
- Monitoring: neu `apps/monitoring/app/catalog/modules/frps.py`, Tests `apps/monitoring/tests/test_catalog_frps.py`
  und ein Fall in `apps/monitoring/tests/test_discovery_match.py`.
- Doku: `docs/admin/monitoring.html` + EN (Modul-Abschnitt, Zeile ~289), `changelog.d/kern-monitoring-23.md`.

## Datenmodell / API / Migrationen
Keine Migration, kein neues Feld. Der Name `closed` aus `RecognizePort` entfällt; eine übernommene
`port`-Instanz, deren gemerktes Protokoll `closed`/`closed+tls` war, wird beim nächsten Scan einmal ein Fund
„changed“ (Protokoll jetzt `unknown`/`tls`). Das Katalog-Modul ist Datenvertrag des Monitoring-Dienstes, der Agent
braucht keine Änderung dafür.

## Externe Integrationen
frps (fatedier/frp): `transport.tls.force`/TlsOnly schließt Nicht-TLS-Verbindungen, vhost-HTTPS routet nach SNI —
Verhalten aus Kevins Beobachtung (private Notiz), nicht erneut gegen die frp-Doku verifiziert; der Fix hängt nicht
daran (er wertet jedes Schließen nach Connect gleich).

## Trade-offs & Alternativen
- Statt Modul: frps-Ports im Agent nie proben (`NeverProbed`). Verworfen: das sperrte auch gewollte Proben des
  Admins und hilft nicht bei Docker (der Listener heißt dort `docker-proxy`).
- Variante 2 allein: behebt den Alarm, lässt aber die Log-Warnungen; Kevin will beide.
- Schließen nach Connect als `warning`: verworfen (Kevin: ok, critical nur bei refused/timeout).

## Risiken & Rollback
Ein Dienst, der jede Verbindung sofort schließt (überlastet, tcpwrappers), meldet künftig ok statt critical — bewusst
so entschieden. Ein späteres Modul, das denselben Container beansprucht (R-1235), muss sich mit `frps` abstimmen.
Rollback: Revert der Task-Commits.

## Doku-Impact
`docs/admin/monitoring.html` + EN: Katalog jetzt mit drei Modulen (`frps`), Port-Check: Schließen nach Connect ist
ok. CHANGELOG `### Fixed`.

## Offene Fragen
Keine (Kevin hat beide Varianten entschieden).
