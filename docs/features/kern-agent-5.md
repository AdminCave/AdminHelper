<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-5 — Agent: Wächter, Container-Wurzel und http-Fühler

Roadmap: R-1438, R-1439, R-1519 (Härtung des Wächters), R-1513 (Container-Wurzel), R-1499, R-1517 (http-Fühler,
BUG), R-1508 (vHost-Weiterleitung, FEAT). R-1440 fährt nicht mit (offene Frage an Kevin, nächster Zug
`tasks/kern-agent-6.md`).

## Problem / Motivation

- **R-1438:** Die Namenslisten des Wächters (`apps/agent/internal/probe/guard.go`: `forwarders`, `forwarderNames`,
  `blockedProcesses`, `activators`) kennen einige Programme noch nicht, die einen Port weiterreichen, einen Dienst je
  Verbindung starten oder SSH auf einem anderen Port anbieten.
- **R-1439:** Der Unix-Socket-Weg (`sensor_local_linux.go` `checkPeer`, `sensor_local_freebsd.go` `checkPeer`) kennt
  für Super-Server, die je Verbindung einen Dienst starten, keine Regel, wie sie der TCP-Weg (`activator`) hat.
- **R-1519:** Der Wächter liest die Argumente eines Port-Weiterleiters (`pastaPort`) nicht in jeder Form so, wie das
  Programm selbst sie liest; er soll in Zweifelsfällen abweisen.
- **R-1513:** Die App-Ansichten öffnen die Wurzel eines Containers über `/proc/<pid>/root` (`openProcRoot`,
  `app_wordpress.go`); dass die PID danach noch zum Container gehört, prüft niemand.
- **R-1499:** Der http-Fühler im Modus `auto` erkennt TLS mit `speaksTLS` (`sensor_http.go`) und wartet dafür bis
  `answerWait` (2 s) auf Stille. Mit `timeout_s` ≤ 2 bleibt nach dieser Frist kein Budget für die eigentliche Anfrage,
  ein stiller Klartext-Server scheitert. Kevin 2026-11-16: Stille-Frist = min(`answerWait`, halbe Restzeit des
  Budgets).
- **R-1517:** `fetchExpecting` liest den Body eines `data.`-Checks mit `io.ReadAll` ohne eigene Grenze; begrenzt ist
  er nur durch den Transport (`cappedBody`, 1 MiB). Der Leser soll selbst begrenzen wie die anderen.
- **R-1508:** Ein vHost-Check fragt die lokale Adresse mit dem Namen des vHosts (Host/SNI). Leitet der vHost auf
  seinen eigenen Namen weiter (Moodle `forcelogin` → `https://<vhost>/login/…`), lehnt `sameTarget` das als anderes
  Ziel ab und der Check bleibt `unknown`.

## Ziel & Nicht-Ziele

**Ziel:** die sieben Zeilen wie oben; der Wächter weist in jedem neuen Zweifelsfall ab (fail-closed).

**Nicht-Ziele:** keine neue Zielart, kein neuer Fühler; keine Weiterleitung auf einen anderen Host, ein anderes
Schema oder einen anderen Port; R-1440 fährt im nächsten Zug.

## Betroffene Komponenten & Dateien

Nur `apps/agent` (Go): `internal/probe/guard.go`, `guard_test.go`, `sensor_local_linux.go`,
`sensor_local_freebsd.go` (+ Tests), `app_wordpress.go`, `app_wordpress_linux.go` und die Aufrufer von
`containerRoot` (`app_wordpress_cron.go`, `app_mail.go`, `app_proxy.go`, `app_nextcloud_aio.go`), `sensor_http.go`
(+ Tests). Doku: `docs/admin/monitoring.html` und `docs/en/admin/monitoring.html` (Abschnitt „Nur dieser Host“,
vHost-Checks), `changelog.d/kern-agent-5.md`.

## Datenmodell / API / Migrationen

Keine. Kein Wire-Format ändert sich; neue Abweisungen erscheinen als `not_allowed` wie bisher.

## Externe Integrationen

Namen der Programme (comm, argv) und die Optionen von pasta vor der Umsetzung in Handbuch oder Quellen nachlesen;
Unbelegtes im Code-Kommentar als nicht verifiziert markieren.

## Trade-offs & Alternativen

- R-1513: Die Wurzel über ein vorher geöffnetes `/proc/<pid>`-Verzeichnis öffnen und über dasselbe Handle die
  cgroup gegen die Container-ID prüfen (eine neu vergebene PID ändert das Handle nicht, ein toter Prozess liefert
  ESRCH) — empfohlen; ein zweites `docker inspect` ließe ein Fenster offen.
- R-1508: Nur eine Weiterleitung auf denselben Namen, dasselbe Schema und denselben Port wie der vHost; die Verbindung
  geht weiter an die lokale Adresse, Host und SNI bleiben der vHost-Name.

## Risiken & Rollback

Strengere Listen können bisher erlaubte Checks auf `not_allowed` setzen (gewollt, fail-closed). Jede Task ist ein
eigener Commit und einzeln zurücknehmbar.

## Doku-Impact

`docs/admin/monitoring.html` DE+EN: der Abschnitt „Nur dieser Host“ (Super-Server auch an Unix-Sockets) und die
vHost-Checks (Weiterleitung auf den eigenen Namen); Changelog-Fragment neutral.

## Offene Fragen

- R-1440 fährt nicht mit (nächster Zug `tasks/kern-agent-6.md`).
