<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: Nacharbeiten an frpc-Abgleich, TLS-Pin, Server-TOML, Monitor-Befehlen, `run --once` und Paket-Hinweis

Zug `kern-agent-1` (Roadmap R-0884, R-0885, R-0929, R-0878, R-0879, R-0881, R-0951). Stand des Codes:
`origin/main@fd3a3b32`. Pfade ohne Präfix liegen unter `apps/agent/`.

## Problem / Motivation

1. **frpc-Abgleich bei hängendem systemd (R-0884).** `startFrpc` (`internal/frpc/sync.go:357`) fragt zuerst
   `isActive` (systemctl). Antwortet systemd nicht, endet der Abgleich mit einem Fehler, bevor der laufende frpc die
   neue Konfiguration über seine Admin-API laden kann. Einzelheiten privat.
2. **Abbruch während des Starts (R-0879, BUG).** `startedOn` (`internal/frpc/sync.go:391`) löscht `.started-hash`
   vor dem Start. Endet `ctx` (Signal, Laufbudget) während des Reloads oder Neustarts, fehlt der Hash danach, und der
   nächste Lauf startet frpc neu, statt zu laden: alle Tunnel brechen kurz ab.
3. **Direkter Pin (R-0885).** `verifyAnchorFingerprint` (`internal/httpclient/httpclient.go:154`) prüft beim
   direkt gepinnten Zertifikat (`:176-178`) nur den Hostnamen; der Weg über die CA prüft auch die Gültigkeit.
   Einzelheiten privat.
4. **Schlüssel-Tabelle der Server-TOML (R-0929).** `keyTable.add` (`internal/frpc/servertoml.go:130-146`) baut je
   Schlüssel alle Präfixe als eigene Strings. Einzelheiten privat.
5. **Meldung für Monitor-Befehle (R-0878, BUG).** `commandFailure` (`internal/monitor/services.go:41`) meldet
   `exec.ErrWaitDelay` (Befehl endet mit 0, ein Kindprozess hält stdout offen) und `context.Canceled` als
   „`<name>` did not start“. `runTimed` (`internal/monitor/plugins.go:61`) und `runTimedEnv`
   (`internal/monitor/updates_linux.go:38`) geben `ErrWaitDelay` als Fehler zurück, obwohl die Ausgabe vollständig ist.
6. **`run --once` ohne Signal-Behandlung (R-0881, REF).** `runCmd` (`cmd/adminhelper-agent/run.go:64-65`) startet
   `runOnce(context.Background())`; SIGTERM (Stopp des Timer-Dienstes) beendet den Prozess hart, der Abbruch über
   `ctx` greift nur im Dauerbetrieb und im Windows-Dienst.
7. **Paket-Hinweis mit `--token` (R-0951, REF).** `deb/DEBIAN/postinst:32`, `rpm/adminhelper-agent.spec:94` und die
   Fixture in `cmd/adminhelper-agent/packaging_rpm_test.go:54` nennen `provision … --token <TOKEN>`; die Doku nennt
   seit R-0863 `--token-stdin`, damit der Token nicht in Shell-History und Prozessliste steht.

## Ziel & Nicht-Ziele

Ziel: je Zeile das beschriebene Verhalten, mit Test. Nicht-Ziele: Änderungen am Server, an frps oder am Desktop;
neue Flags; ein anderer Weg als die Admin-API für den Reload.

## Betroffene Komponenten & Dateien

`agent`: `internal/frpc/sync.go`, `internal/frpc/servertoml.go`, `internal/httpclient/httpclient.go`,
`internal/monitor/services.go`, `internal/monitor/plugins.go`, `internal/monitor/updates_linux.go`,
`cmd/adminhelper-agent/run.go`, `deb/DEBIAN/postinst`, `rpm/adminhelper-agent.spec`,
`cmd/adminhelper-agent/packaging_rpm_test.go`, die zugehörigen Tests.

## Datenmodell / API / Migrationen

Keine Migration, keine Server-API, kein neues Flag. Das frpc-Admin-API (`frpc reload`) wird wie bisher genutzt.

## Externe Integrationen

frpc-Admin-API über `frpc reload -c <frpc.toml>` wie im Bestand (`internal/frpc/platform_linux.go:105`); kein neuer
Aufruf.

## Trade-offs & Alternativen

- R-0884: Antwortet systemd nicht, lädt der Abgleich über die Admin-API, sofern frpc auf seinem Admin-Port lauscht
  (`ownsAdminPort`) und der gemeinsame Teil unverändert ist; sonst bleibt es beim Fehler wie heute. Alternative
  eigener HTTP-Client zur Admin-API: verworfen, `frpc reload` liest Port und Zugang schon aus derselben Datei.
- R-0879: bei beendetem `ctx` früh zurück, bevor `.started-hash` gelöscht wird.
- R-0929: Segmentzahl je Schlüssel begrenzen (der Generator schreibt wenige Segmente) statt eines Tries; einfacher
  und schließt die Klasse.
- R-0878: `ErrWaitDelay` gilt in `runTimed`/`runTimedEnv` als Erfolg, `Canceled` bekommt eine eigene Meldung.
- R-0881: `run --once` bekommt denselben `signal.NotifyContext` wie der Dauerbetrieb.

## Risiken & Rollback

Jede Task ein Commit, einzeln zurücknehmbar. Der frpc-Abgleich (T1) und der Pin (T2) berühren Tunnel und
Vertrauen: `security` je Task. Ein abgelaufenes direkt gepinntes Zertifikat wird nach T2 abgewiesen (wie über die CA).

## Doku-Impact

`changelog.d/kern-agent-1.md`; die Paket-Hinweise (T6) sind selbst Nutzertext. `docs/admin/agent-deployment.html`
(DE+EN) nennt `--token-stdin` schon; keine weitere Seite beschreibt das geänderte Verhalten.

## Offene Fragen

Keine.
