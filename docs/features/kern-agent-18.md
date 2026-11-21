# kern-agent-18 — Agent-Zug: Provisionierungs-Ausgabe, Nachlese Windows-Update

Roadmap: R-0443, R-1679.

## Problem / Motivation
- **R-0443:** `provision` meldet bei der FRP-Einrichtung ein Vorhaben statt eines Ergebnisses. Mit FRP-Paket druckt
  der Agent `→ FRP-Client wird eingerichtet...`, auch wenn der Server einen Text ohne Tunnel schickt und `frpc.Apply`
  frpc daraufhin stoppt (`apps/agent/internal/provision/provision.go:189`). Ohne Paket druckt er
  `→ Keine FRP-Tunnel ... FRP wird uebersprungen.` (`provision.go:211`), stoppt dabei aber einen frpc einer früheren
  Provisionierung (R-0398). Der Admin liest also beide Male etwas anderes, als geschehen ist.
- **R-1679:** zwei Hinweise aus der Prüfung von R-1581.
  - Der Kopfkommentar von `apps/gateway/nginx.conf` (Zeilen 1–6) nennt nur die TLS-Rolle. Er sagt nicht, dass die
    Repo-Ebene seit R-1581 auch den signierten Windows-Update-Satz ausliefert, dessen minisign-Signatur der Agent
    prüft und nicht das Gateway.
  - `apps/agent/build-windows-update.sh:33` prüft `VERSION` mit `[0-9]` in `=~`. Unter einer Locale wie
    `de_DE.UTF-8` deckt dieser Bereich mehr als die ASCII-Ziffern ab.

## Ziel & Nicht-Ziele
- **Ziel R-0443:** Nach der FRP-Einrichtung meldet `provision`, was tatsächlich geschehen ist (Kevin 2026-11-21:
  „Ausgabe nach Ergebnis“).
  - Mit Tunneln: „FRP-Client eingerichtet (N Tunnel)“.
  - Ohne aktiven Tunnel, gleich ob mit oder ohne Paket: „keine aktiven FRP-Tunnel, frpc gestoppt“.
  - Die Ausgabe vor dem Aufruf entfällt.
  - Die Texte werden englisch, wie jede neue Code-Ausgabe.
- **Ziel R-1679:**
  - Der Gateway-Kopfkommentar nennt den Windows-Satz und wer seine Signatur prüft.
  - Das Build-Skript prüft `VERSION` locale-fest (`LC_ALL=C`).
  - Ein Test beweist, dass eine Nicht-ASCII-Ziffer abgelehnt wird.
- **Nicht-Ziele:**
  - kein Umbau der übrigen deutschen Agent-Ausgaben (offener Sweep);
  - keine Änderung an Signatur, Trusted Comment oder Ablauf des Update-Satzes;
  - R-1681 ist geschlossen (Kevin 2026-11-21).

## Betroffene Komponenten & Dateien
- `apps/agent/internal/provision/provision.go` und `provision_test.go`.
- `apps/agent/internal/frpc/apply.go` und `apply_test.go`: `Apply` liefert die Zahl der Tunnel aus dem Text, den der
  Server schickt; heute erkennt `hasProxies` in `sync.go` nur, ob es überhaupt einen gibt.
- `apps/agent/build-windows-update.sh` und `scripts/tests/windows_update_set_test.sh`.
- `apps/gateway/nginx.conf`, nur der Kommentar.

## Datenmodell / API / Migrationen
Keine. Kein Wire-Format ändert sich. `frpc.Apply` ist ein internes Go-Paket; sein einziger Aufrufer ist `provision`.

## Externe Integrationen
Keine neuen. Die frpc-TOML wird nur gezählt (`[[proxies]]`-Tabellen wie in `hasProxies`), nicht anders gelesen.

## Trade-offs & Alternativen
- **Die Zahl liefert `Apply` selbst**, statt dass `provision` den Text noch einmal decodiert. So zählt genau der
  Text, den `Apply` angewendet hat; ein zweiter Decoder könnte davon abweichen.
- **Pfad ohne Paket:** Die Meldung lautet dort gleich wie bei einem Text ohne Tunnel. Für den Admin ist das Ergebnis
  dasselbe: kein Tunnel, kein frpc.

## Risiken & Rollback
- **R-0443** ändert nur die Konsolenausgabe und die Signatur von `frpc.Apply`; Steuerfluss und Dateien bleiben.
  - Risiko: Ein Skript eines Admins, das den alten deutschen Text greppt.
  - Bisher ist kein solcher Text dokumentiert (`docs/` nennt ihn nicht), deshalb ein CHANGELOG-Eintrag.
- **R-1679** macht das Build-Skript strenger. Ein gültiges `X.Y.Z` bleibt gültig.
- **Rollback:** Revert des jeweiligen Task-Commits.

## Doku-Impact
- R-0443: `docs/` zitiert die Ausgaben nicht, also keine Seite; nur `changelog.d/kern-agent-18.md`.
- R-1679: keine (Kommentar und Eingabeprüfung).

## Offene Fragen
Keine. Den Ausgabe-Wunsch hat Kevin am 2026-11-21 entschieden; R-1681 hat er geschlossen.
