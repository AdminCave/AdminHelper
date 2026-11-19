# kern-provision-2 — Nachlese Provisionieren

Roadmap: R-1629, R-1612, R-1613, R-1614, R-1628 (Zug `tasks/kern-provision-2.md`).

## Problem / Motivation
Nachlese aus kern-provision-1 (Prüfer und Abschlussprüfung):
- **R-1629:** Der Befehlsbau des Desktops (`apps/desktop/ui/src/lib/provisioning/command.ts`) prüft Kopf und Werte
  eines Katalogbefehls auf Steuerzeichen; die Zeichenprüfung wird vereinheitlicht und erweitert. Einzelheiten nur in
  `tasks/private/`.
- **R-1612:** Der Windows-Befehl im Automationsmodus gibt den Token als `--token <wert>` an die `.exe`; während der
  Provisionierung steht er damit in der Prozessliste. Der Agent kann ihn über stdin lesen (`--token-stdin`). Dazu ist
  der Zweig in `catalog.py`, der ein unlesbares `<ABI>/All` überspringt, ungetestet.
- **R-1613 / R-1628 (Server):** `progress.py` setzt `server_id` ungequotet in die Monitoring-URL; `_certificate`
  meldet auch das Zertifikat einer widerrufenen Geräte-Linie; der Test ohne Monitoring-Key prüft nicht, dass kein
  Request rausgeht; das leere `downgrade` der Migration `6a4e9feea1c5` ist nicht an der Funktion begründet.
- **R-1614 / R-1628 (Desktop):** Ein unbekannter `reason` oder `port.purpose` aus dem Katalog erscheint als roher
  i18n-Schlüssel; der Dialogtest prüft das Label der Aktions-Tabs nicht über die Rolle; ein Fortschrittstest „früherer
  Token, dann falsche Antwort“ fehlt.
- **R-1628 (Harness, Kevin 2026-11-19 angenommen):** `scripts/tests/openapi_breaking_test.sh` bekommt für die
  R-1594-Ausnahmen einen Fall gegen das echte oasdiff, wie für R-0411/R-0533/R-1080.

## Ziel & Nicht-Ziele
Ziel: die genannten Lücken schließen, ohne sichtbares Verhalten zu ändern außer (a) dem Windows-Automationsbefehl
(Token per Pipe statt Argument) und (b) einer lesbaren Ersatzbeschriftung für unbekannte Katalogwerte.
Nicht-Ziele: neue Plattformen, Windows-Installationsbefehl (R-1578), Umbau des Katalogformats über den einen neuen
Wertetyp hinaus.

## Betroffene Komponenten & Dateien
- desktop-ui: `src/lib/provisioning/command.ts` (+ Test), `src/components/infra/provisioning/ProvisioningDialog.svelte`
  (+ Test), `ProvisioningProgress.test.ts`, `src/lib/i18n/dictionaries.ts`.
- server: `app/modules/provisioning/catalog.py`, `progress.py`, `alembic/versions/6a4e9feea1c5_server_os_type_platform.py`,
  `tests/test_provisioning_catalog.py`, `tests/test_provisioning_progress.py`.
- scripts (Harness): `scripts/tests/openapi_breaking_test.sh`.

## Datenmodell / API / Migrationen
- Katalog (`GET /api/provisioning/platforms`): der Windows-Befehl `reregister` ersetzt im Automationsmodus das Argument
  `{"flag":"--token","value":"token"}` durch `{"flag":"--token-stdin","value":"tokenStdin","mode":"automation"}`. Das
  Feld `value` ist im Schema `string` (bewusst offen, `types.ts`); kein Schema-Bruch, kein OpenAPI-Snapshot-Wechsel.
  Der Desktop setzt für `tokenStdin` den gequoteten Token als Pipe vor den Kopf: `'<token>' | & '…exe' provision …
  --token-stdin`. Ein älterer Desktop kennt den Wert nicht und baut im Windows-Automationsmodus keinen Befehl (sein
  dokumentiertes Verhalten für Unbekanntes), der interaktive Modus bleibt.
- Keine Migration; nur der Docstring von `downgrade()` in `6a4e9feea1c5`.

## Externe Integrationen
PowerShell-Pipeline in eine native `.exe`: der String geht mit Zeilenende an stdin; der Agent liest eine Zeile und
trimmt (`strings.TrimSpace`, `apps/agent/cmd/adminhelper-agent/main.go`). Auf Windows nicht verifiziert (keine
Windows-Box im Pool); Linux-Gegenstück ist der dokumentierte Weg von `agent-install.sh`.

## Trade-offs & Alternativen
- R-1612: (A) neuer Wertetyp `tokenStdin` mit Pipe (empfohlen: Token nie im argv); (B) Automationsmodus für Windows
  streichen (weniger Funktion); (C) `$env:`-Variable (steht im Umfeld des Kindprozesses, nicht besser als stdin).
- R-1614 Ersatzbeschriftung: generischer Text („unbekannt“) statt Schlüssel, der Rohwert bleibt nicht sichtbar.

## Risiken & Rollback
Gering; jede Task einzeln per Revert zurücknehmbar. Desktop/Server-Gleichlauf: neuer Server + alter Desktop verliert
nur den Windows-Automationsbefehl.

## Doku-Impact
`docs/admin/agent-deployment.html` (DE+EN) nennt, dass auch der Windows-Automationsbefehl des Desktops den Token über
stdin gibt; `changelog.d/kern-provision-2.md`. Sonst keine.

## Offene Fragen
- R-1629 Designfrage (Restrisiko, Kevins Bereich): Der Befehlskopf kommt vom Server (R-1595). Empfehlung: so lassen —
  der Desktop vertraut seinem Server ohnehin (mTLS, Admin-Sitzung), der Befehl steht vor dem Kopieren lesbar im Fenster;
  eine Allowlist im Desktop machte R-1595 rückgängig. Blockiert keine Task.
