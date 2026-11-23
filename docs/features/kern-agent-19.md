# kern-agent-19 — provision meldet einen frpc, der nicht startet

Roadmap: R-1682 (BUG, Nachlese kern-agent-18).

## Problem / Motivation
Seit kern-agent-18 druckt `provision` das FRP-Ergebnis statt des Vorhabens: "FRP client set up (N tunnels)" oder
"No active FRP tunnel, frpc stopped". Scheitert aber der Start oder Stopp des frpc-Dienstes, macht
`warnOnServiceFailure` (`apps/agent/internal/frpc/apply.go:164`) den Fehler `errFrpcService` zu `nil` und schreibt nur
eine Warnzeile ins Log. `Apply` (`apply.go:137`) liefert dann die Zahl der Tunnel, und `provision.go:220` meldet
"FRP client set up (N tunnels)" direkt nach der Warnung: Die Erfolgszeile widerspricht dem, was passiert ist. Ebenso
meldet der Pfad ohne Paket "frpc stopped", wenn der Stopp gescheitert ist.

## Ziel & Nicht-Ziele
- **Ziel:** Die Ergebniszeile von `provision` sagt, was wirklich ist. Scheitert der Dienst, lautet sie etwa
  "FRP client configured (N tunnels), but frpc did not start: <Ursache>. The next agent run tries again." bzw. für
  den Stopp "frpc could not be stopped: <Ursache> …". Die Provisionierung bleibt erfolgreich (das Token ist
  verbraucht), wie bisher; der Hash wird wie bisher entfernt, damit der nächste Lauf erneut anwendet.
- `Apply` und `ApplyWithoutBundle` geben den Dienstfehler als eigenen, exportierten Fehlerwert zurück
  (`frpc.ErrServiceDeferred`, umschließt die Ursache), statt ihn zu schlucken; `provision` unterscheidet ihn per
  `errors.Is` von einem echten Fehler (Schreibfehler bleibt fatal wie heute).
- Eine einzige Meldung statt Warnzeile plus Erfolgszeile.
- **Nicht-Ziele:** kein Wiederholversuch beim Provisionieren, keine Änderung an Sync, am Hash-Verhalten oder am
  Exit-Code von `provision`.

## Betroffene Komponenten & Dateien
- `apps/agent/internal/frpc/apply.go` (`Apply`, `ApplyWithoutBundle`, `warnOnServiceFailure`), Test `apply_test.go`.
- `apps/agent/internal/provision/provision.go` (Ergebnis-Switch ab Zeile 216), Test `provision_test.go`.
- `changelog.d/kern-agent-19.md`.

## Datenmodell / API / Migrationen
Keine. Nur Go-API innerhalb des Agents und Konsolenausgabe.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- **Fehlerwert statt Ergebnis-Struct:** `Apply` behält `(int, error)`; ein Sentinel mit `errors.Is` ist der
  kleinste Eingriff und passt zum bestehenden `errFrpcService`. Ein Struct `{Tunnels, ServiceFailed}` wäre
  expliziter, ändert aber jede Test-Attrappe.

## Risiken & Rollback
Gering: nur die Ausgabe und die Fehlerklassifikation. Risiko: ein Aufrufer, der den neuen Fehler nicht kennt,
bräche ab; `provision` ist der einzige Aufrufer (`grep frpc.Apply`). Rollback: Revert.

## Doku-Impact
Keine Seite beschreibt die Ausgabe von `provision` wörtlich; nur das CHANGELOG-Fragment.

## Offene Fragen
Keine.
