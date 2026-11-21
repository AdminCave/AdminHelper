# kern-agent-18 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-18 · Review: am Ende
Spec: docs/features/kern-agent-18.md (Roadmap R-0443, R-1679)
Heavy: linux-full — apps/agent (Provisionierung) und apps/gateway/nginx.conf; nur Ausgabe und Kommentar, kein Cross-Host-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0443: provision meldet das FRP-Ergebnis statt des Vorhabens  [x]
Komponente: agent · Dateien: apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, apps/agent/internal/frpc/sync.go, changelog.d/kern-agent-18.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @83f6920e9 2026-11-21T07:11:51+01:00
Review: am Ende (Branch-Review)
Änderung: `frpc.Apply` liefert die Zahl der `[[proxies]]`-Tabellen des angewendeten Texts mit. `provision` druckt danach „FRP client set up (N tunnels)“ bzw. bei 0 und im Pfad ohne Paket (`provision.go:211`) „no active FRP tunnel, frpc stopped“; die Ausgabe vor dem Aufruf (`provision.go:189`) entfällt. Tests für alle drei Fälle (N > 0, Text ohne Tunnel, ohne Paket) erst rot.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/provision/... ./internal/frpc/...
Doku: changelog.d/kern-agent-18.md (docs/ zitiert die Ausgaben nicht)

### T2 — R-1679: build-windows-update.sh prüft VERSION locale-fest  [ ]
Komponente: scripts · Dateien: apps/agent/build-windows-update.sh, scripts/tests/windows_update_set_test.sh
Änderung: Die Prüfung von `VERSION` (`build-windows-update.sh:33`) läuft unter `LC_ALL=C`. Der Test ruft das Skript unter einer UTF-8-Locale mit einer Nicht-ASCII-Ziffer in `VERSION` auf und erwartet die Ablehnung; er ist erst rot.
Verify: bash scripts/dev/verify.sh scripts --strict -- windows_update_set_test
Doku: keine (Eingabeprüfung eines Release-Skripts)

### T3 — R-1679: Gateway-Kopfkommentar nennt den signierten Windows-Satz  [ ]
Komponente: server · Dateien: apps/gateway/nginx.conf
Änderung: Der Kopfkommentar (`nginx.conf:1-6`) nennt, dass die Repo-Ebene auch den minisign-signierten Windows-Update-Satz ausliefert, dessen Signatur der Agent prüft, nicht das Gateway. Nur Kommentar.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: keine (Kommentar)

## Entscheidungen
- 2026-11-21: Neue Ausgaben englisch (Konvention für neue Code-Strings); der Inhalt folgt Kevins Wahl „Ausgabe nach Ergebnis“.
