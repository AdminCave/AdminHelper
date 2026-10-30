<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-2 — Agent: Tunnel-Abbau, Konfig-Prüfung, Eingaben über stdin, Temp-Reste

Zug der Kern-Session (Roadmap R-0963, R-0964, R-0983, R-0965, R-0385). Details zu den SEC-Zeilen stehen nur in
`tasks/private/`.

## Problem
- **R-0963:** Der Agent baut den letzten Tunnel nur über systemd ab (`stopFrpc`, `apps/agent/internal/frpc/sync.go:473`).
  Antwortet systemd nicht, bleibt frpc mit seinen Tunneln in mehreren Fällen laufen, in denen der Server keinen
  Tunnel mehr will (`syncWithoutFrpConfig` :446, `refuseServerConfig` :336, `applyConfig` ohne `[[proxies]]`).
- **R-0964:** Die Prüfung der Server-Konfig (`apps/agent/internal/frpc/servertoml.go`) braucht Grenzen für die Zahl
  der Schlüssel; ihre Meldungen zitieren Schlüssel ungekürzt, und die Wertprüfung (:104) läuft vor der
  Segmentprüfung (:108).
- **R-0983:** `provision --token-stdin` liest die Token-Zeile mit Echo (`readStdinToken`,
  `apps/agent/cmd/adminhelper-agent/main.go:99`); interaktiv eingefügt steht der Token im Terminal.
- **R-0965:** `monitor init` nimmt den API-Key nur als Argument (`main.go:194`), sichtbar in der Prozessliste;
  postinst (:33), README (:361, :384), `reprovisionHint` (`internal/enroll/client.go:21`) und
  `agent-deployment.html` zeigen noch die Argument-Form.
- **R-0385:** Eine abgebrochene Erneuerung lässt `<datei>.<n>.tmp` im Identitätsverzeichnis liegen
  (`writeTemp`, `internal/enroll/enroll.go:301`); niemand räumt sie.

## Ziel & Nicht-Ziele
- Ziel: Ohne Antwort von systemd baut der Agent die Tunnel über die Admin-API seines eigenen frpc ab (Konfig ohne
  Proxies, Reload); der Fehler bleibt stehen, der nächste Lauf versucht systemd erneut.
- Ziel: feste Grenzen für Schlüssel je Tabelle und je Text in der Konfig-Prüfung; Meldungen kürzen Schlüssel;
  Segmentprüfung vor der Wertprüfung.
- Ziel: auf einem Terminal liest `--token-stdin` ohne Echo; aus Pipe/Datei unverändert.
- Ziel: `monitor init --api-key-stdin` (wie `--token-stdin`); Hinweise und Doku zeigen die stdin-Formen.
- Ziel: Temp-Reste der drei Identitätsdateien räumt, wer `LockIdentity` hält, mit exakter Namensprüfung, nie per
  Glob über fremde Namen; `CheckStorable` räumt nichts.
- Nicht-Ziel: eine Größengrenze für `extra_config` am Server (eigene Komponente, eigene Zeile, falls nötig).
- Nicht-Ziel: `--api-key` entfernen (bleibt für bestehende Skripte).

## Betroffene Komponenten & Dateien
Nur `apps/agent` (Komponente `agent`): `internal/frpc/sync.go`, `internal/frpc/servertoml.go`,
`cmd/adminhelper-agent/main.go`, `internal/enroll/enroll.go`, `internal/enroll/renew.go`,
`internal/enroll/client.go`, `internal/provision/provision.go`, `deb/DEBIAN/postinst`, dazu `go.mod`/`go.sum`
(`golang.org/x/term`), `THIRD_PARTY_LICENSES.md`, README, `docs/admin/agent-deployment.html` DE+EN.

## Datenmodell / API / Migrationen
Keine Server-API, keine Migration. Neue CLI-Option `monitor init --api-key-stdin` (additiv).

## Externe Integrationen
- frp: Reload über die Admin-API übernimmt nur die Proxies (https://github.com/fatedier/frp#reload-config).
  Dass ein Reload mit null Proxies alle Tunnel schließt und frpc ohne Proxies weiterläuft: **nicht verifiziert**,
  T1 prüft es vor der Umsetzung im frp-Quelltext/der Doku und mit dem echten frpc (`frpc verify -c`).
- `golang.org/x/term` (BSD-3-Clause, Go-Autoren; hängt nur an `x/sys`): `term.IsTerminal`, `term.ReadPassword`,
  Linux und Windows.

## Trade-offs & Alternativen
- R-0963: Konfig ohne Proxies + Reload (empfohlen; nur der eigene frpc über `ownsAdminPort`) gegenüber frpc per
  Signal beenden (PID nicht sicher dem Dienst zuzuordnen, systemd startet ihn neu).
- R-0964: Grenze im Agent (empfohlen, eine Komponente, wirkt gegen jeden Server) gegenüber Grenze am Server.
- R-0983: `x/term` (empfohlen) gegenüber eigenem ioctl/Console-Mode je Plattform.

## Risiken & Rollback
- T1 ändert den Fehlerpfad des Tunnel-Abbaus: der Hash bleibt bei Fehler weg, der nächste Lauf wiederholt.
- T2 kann eine echte Server-Konfig ablehnen, wenn die Grenzen zu eng sind: Grenzen deutlich über dem, was der
  Generator für viele Tunnel schreibt; Test mit der Konfig des Generators für viele Tunnel.
- Jede Task einzeln per `git revert` zurücknehmbar.

## Doku-Impact
`agent-deployment.html` DE+EN (CLI-Tabelle `monitor init`, Hinweis zur verdeckten Token-Eingabe), README
(provision/monitor-Beispiele), `changelog.d/kern-agent-2.md`.

## Offene Fragen
Keine aus Kevins Bereich: alle Zeilen sind triagiert (Kevin 2026-10-30), die Abhilfen nennen die Zeilen.
