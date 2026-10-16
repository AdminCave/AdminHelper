<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent übernimmt FRP-Tunnel selbst — Spec

Roadmap: R-0398 (BUG). Entscheidungen: Kevin, 2026-10-16 (Planungsgespräch, Fragen per Rückfrage beantwortet).
Stand: `origin/main@b84b9495`. Ledger: `tasks/agent-frpc-sync.md`.

## Problem / Motivation

Ein Agent-Host, der provisioniert wurde, bevor es für ihn einen FRP-Tunnel gab, bekommt einen später
angelegten Tunnel nie. Erst ein erneutes Provisionieren richtet frpc ein. Im Feld so beobachtet
(Installation v0.45.0, 2026-10-16).

Ursachen im Code:

- `apps/agent/internal/provision/provision.go:152` ruft `frpc.Apply` nur, wenn die Aktivierung ein FRP-Paket
  liefert. Der Server liefert es nur bei FRP-Config **und** mindestens einem Tunnel
  (`apps/server/app/modules/provisioning/helpers.py`, `build_frp_bundle`). Ohne Paket fehlt `/etc/frp/adminhelper.conf`
  (geschrieben nur in `apps/agent/internal/frpc/apply.go:91`). Damit wird der Server-API-Key gar nicht gespeichert,
  entgegen dem Paketkommentar `provision.go:10` („writes the server API key (always)“), und `frpc.service` bleibt
  aus.
- `apps/agent/internal/frpc/sync.go:26` endet dann bei jedem Timer-Lauf still mit „Keine Konfiguration gefunden“.
- Würde der Agent die Sync-Config immer schreiben, liefe er in das nächste Problem: ohne FRP-Config antwortet
  `GET /api/frp/provision/{id}/config-hash` mit 404 „Keine FRP-Config vorhanden“
  (`apps/server/app/modules/frp/provision_router.py:57`). 404 ist im Agent ein dauerhafter Fehler
  (`apps/agent/internal/httpclient/httpclient.go:36`). `runOnce` (`cmd/adminhelper-agent/run.go:86`) gibt ihn zurück,
  und der Oneshot-Dienst endet bei jedem Lauf rot.

Dazu kommen drei Schwächen am selben Ablauf:

- **Neu-Provisionieren bei laufendem frpc.** `Apply` schreibt die neue `frpc.toml`, speichert deren Hash
  (`apply.go:120`) und ruft nur `systemctl enable --now frpc.service` (`platform_linux.go:22`). Ein laufender frpc
  wird dabei nicht neu gestartet und läuft mit der alten Config weiter. Der gespeicherte Hash passt schon zum
  Server, also korrigiert auch der nächste Abgleich nichts (aus dem Code gelesen).
- **Jede Tunnel-Änderung startet frpc neu** (`sync.go:100`, `systemctl restart`). Alle Sitzungen zu diesem Host
  brechen ab, auch über unveränderte Tunnel.
- **`loginFailExit` ist in frp standardmäßig `true`.** Ist frps beim ersten Login nicht erreichbar, beendet sich
  frpc. systemd startet ihn alle 5 s neu (`Restart=on-failure`, `RestartSec=5` in `apps/agent/systemd/frpc.service`),
  im Journal steht eine Neustartschleife.

## Ziel & Nicht-Ziele

**Ziele**

1. Ohne Tunnel läuft kein frpc. Der Agent-Lauf endet ohne Fehler (Exit 0), auch wenn auf dem Server gar keine
   FRP-Config existiert.
2. Ein später angelegter Tunnel greift beim nächsten Timer-Lauf ohne Handarbeit. frpc wird dabei dauerhaft
   aktiviert (`enable --now`), also auch nach einem Reboot.
3. Ändern sich nur Tunnel (`[[proxies]]`), übernimmt frpc das per Reload. Unveränderte Tunnel und ihre offenen
   Verbindungen bleiben stehen.
4. Neu-Provisionieren übernimmt die neue Config sofort, auch wenn frpc schon läuft.
5. frpc gibt bei nicht erreichbarem frps nicht auf, sondern versucht es selbst weiter.
6. Fällt der letzte Tunnel weg, wird frpc gestoppt und deaktiviert. Die `frpc.toml` mit dem frps-Token wird
   gelöscht.

**Nicht-Ziele (YAGNI)**

- Ein schnellerer Abgleich als der 5-Minuten-Timer (`adminhelper-agent.timer`: `OnUnitActiveSec=300`,
  `RandomizedDelaySec=30`). Das wird eine eigene Roadmap-Zeile.
- frpc als Dienst unter Windows. `platform_windows.go` bleibt bei No-ops, Windows bekommt nur die neuen
  Seams als No-op.
- Desktop-Tunnel (R-0402) und frps-Seite (frps-Supervisor) sind eigene Vorhaben.
- Bestandshosts heilen, die ohne Tunnel provisioniert wurden. Ihnen fehlt der Server-API-Key, ohne den kein
  Abgleich möglich ist. Sie werden einmal neu provisioniert (CHANGELOG, Doku).

## Betroffene Komponenten & Dateien

| Komponente | Datei | Änderung |
|---|---|---|
| server | `apps/server/app/modules/frp/provision_router.py` (`_load_sync_inputs` :44, 404 :57, `get_provision_config_hash` :83) | config-hash ohne FRP-Config → 200 `{"hash": null}` |
| server | `apps/server/tests/test_provisioning.py:283-284` | erwartet heute 404 ohne FRP-Config → 200 mit `hash: null` |
| server | neu `apps/server/tests/test_frp_provision_sync.py` | Vertrag config-hash; Generator setzt kein `loginFailExit`/`webServer`, Common-Teil vor dem ersten `[[proxies]]` (`config_generator.py:156`, :178, :184) |
| agent | `apps/agent/internal/frpc/apply.go` | `WriteSyncConfig` herauslösen; `Apply` nutzt den gemeinsamen Anwende-Pfad und speichert den Server-Hash |
| agent | `apps/agent/internal/frpc/sync.go` | Ablauf nach Tabelle unten; lokaler Vorspann (`loginFailExit`, später `webServer.*`) |
| agent | `apps/agent/internal/frpc/platform_linux.go` / `platform_windows.go` | Seams: aktiv?, aktivieren, deaktivieren und stoppen, Reload; Windows No-ops |
| agent | neu `apps/agent/internal/frpc/admin.go` (+ Test) | `admin.conf` (Port, Hex-Passwort, 0600), freier Port, Prüfung des eigenen Listeners über `/proc/net/tcp` |
| agent | `apps/agent/internal/provision/provision.go` | schreibt die Sync-Config immer; `frp=null` → Ablauf „nichts zu tun“ |
| scripts | `scripts/tests/box_tunnelbox.sh`, `box_visitorbox.sh`, `multibox.sh`, `multibox_test.sh` | Szenario: Tunnel nach dem Provisionieren; zweiter Tunnel bei offener Sitzung |
| docs | `docs/admin/agent-deployment.html`, `docs/developer/agent.html`, `docs/developer/server.html:99`, `docs/developer/api-reference.html:163` (je DE+EN), `CHANGELOG.md` | siehe Doku-Impact |

## Datenmodell / API / Migrationen

- **Keine Alembic-Migration.**
- **API-Vertrag (Kevins Entscheidung):** `GET /api/frp/provision/{id}/config-hash` antwortet ohne FRP-Config mit
  200 `{"hash": null}` statt 404.
  - Unverändert bleibt: 404 „Server nicht gefunden“ (der Agent wertet das zu Recht als dauerhaft), die 403 der
    Scope-Prüfung und die Hash-Semantik bei vorhandener Config.
  - Mit Config, aber ohne aktiven Tunnel (die Tunnel, die der Generator als `[[proxies]]` ausgibt,
    `active_tunnels`): `GET …/config` liefert den Common-Teil ohne `auth.token` und ohne `[[proxies]]`, der Hash
    ist der dieses Texts (T8, Kevin 2026-10-16 nach dem Branch-Review: ein Host ohne Tunnel bekommt keine
    frps-Zugangsdaten, und jeder Agent schließt damit den letzten Tunnel, fail-closed). Der neue Agent stoppt
    frpc auf diesen Text; ein alter startet frpc damit neu, frpc meldet sich ohne Token nicht an und wird von
    systemd neu gestartet, bis der Agent aktualisiert ist. Das Provisionierungs-Paket trägt mit Config denselben
    Text (T10): Eine Neu-Provisionierung mit altem Agent schreibt damit den neuen Key; einen gestoppten frpc
    startet sie ohne Tunnel, ein laufender frpc behält seinen Tunnel bis zu seinem nächsten Neustart (von Kevin
    hingenommen).
  - `GET …/config` antwortet 404 nur ohne Config. Der neue Agent fragt ihn nur bei einem Hash ≠ null ab.
  - Das OpenAPI-Schema der Route ist heute `{}` (`apps/server/tests/openapi.snapshot.json`) und bleibt so. Ändert
    sich der Snapshot, ist das eine Vertragsänderung und gehört zurück an Kevin.
- **Generator-Vertrag (neu, durch Test fixiert):** `generate_frpc_toml` setzt weder `loginFailExit` noch
  `webServer.*`, die stellt der Agent lokal voran. Der Common-Teil steht vor dem ersten `[[proxies]]`.
- **Dateien auf dem Agent-Host (Linux):**
  - `/etc/frp/adminhelper.conf`: jetzt immer vorhanden.
  - `/etc/frp/frpc.toml`: lokaler Vorspann + Server-Text, 0600. Gelöscht bei 0 Tunneln oder ohne FRP-Config.
  - `/etc/frp/.config-hash`: Hash des **Server**-Texts, nicht der lokal ergänzten Datei.
  - neu `/etc/frp/admin.conf` (0600): Port und Passwort der lokalen frpc-Admin-API.
  - neu `/etc/frp/.started-hash`: Common-Teil, mit dem frpc zuletzt gestartet wurde; vor jedem Start gelöscht,
    damit auf einen gescheiterten Neustart kein Reload folgt.

**Kompatibilität**

| Kombination | Verhalten |
|---|---|
| alter Agent, neuer Server, ohne FRP-Config | `hash: null` wird zu `""`. Ohne Hash-Datei gleich, also kein Fehler (heute 404). |
| alter Agent, neuer Server, mit Config | unverändert, solange der Host einen aktiven Tunnel hat; fällt der letzte weg: Text ohne Token und Tunnel, frpc startet neu und meldet sich nicht an (Neustart-Schleife von systemd bis zum Update, Tunnel zu; T8) |
| alter Agent, neuer Server, Neu-Provisionierung ohne aktiven Tunnel | Paket mit dem Text ohne Token und Tunnel: neuer Key in der Sync-Config; nur `enable --now`, ein laufender frpc behält seinen Tunnel bis zum nächsten Neustart (T10, hingenommen) |
| neuer Agent, alter Server, mit Config | wie bisher; ohne Tunnel liefert der alte Server einen Text mit Token, aber ohne Proxies, und der neue Agent stoppt frpc |
| neuer Agent, alter Server, ohne FRP-Config | 404 → dauerhafter Fehler bei jedem Lauf. Annahme: Agents kommen aus dem Paket-Repo desselben Servers (`:8445`), also gleiche Version. Für manuell installierte Pakete **nicht verifiziert**. |
| Rollback auf alten Agent | Der alte Sync überschreibt `frpc.toml` beim nächsten Hash-Wechsel mit dem Server-Text ohne Vorspann. `admin.conf` bleibt ungenutzt liegen. |

## Ablauf des Abgleichs (Linux)

| Lage | Ablauf |
|---|---|
| `adminhelper.conf` fehlt (Bestandshost) | Info mit dem Ausweg „einmal neu provisionieren“, Exit 0 |
| `hash: null` | frpc stoppen und deaktivieren, `frpc.toml` und Hash löschen, Exit 0 |
| Hash gleich, frpc soll laufen und läuft | nichts (`systemctl is-active`, kein `/healthz`) |
| frpc soll laufen, läuft aber nicht (z. B. Admin-Port nach Reboot belegt), Hash gleich oder neu mit Proxies (T9) | neuen Port und neues Passwort wählen, Datei neu schreiben, starten |
| Hash neu, TOML ohne `[[proxies]]` | frpc stoppen und deaktivieren, `frpc.toml` löschen, Hash speichern |
| Hash neu, mit Proxies, frpc aus | schreiben, `enable --now` |
| Hash neu, mit Proxies, frpc läuft, Common-Teil gleich | schreiben, Reload, wenn frpc mit diesem Common-Teil gestartet wurde (`.started-hash`) und der Admin-Port einem Listener von root gehört; sonst oder wenn der Reload scheitert, Neustart |
| Hash neu, mit Proxies, Common-Teil anders (Token, Adresse, `user`, TLS) | schreiben, Neustart |
| Provision mit FRP-Paket | Sync-Config schreiben, dann derselbe Anwende-Pfad wie oben mit dem Paket-Text, aber immer Neustart statt Reload |
| Provision ohne FRP-Paket | Sync-Config schreiben, dann wie `hash: null` (stoppt einen frpc aus einer früheren Provisionierung) |
| Server-Text setzt `webServer` oder `loginFailExit` (Schlüssel oder Tabelle, groß oder klein geschrieben) | Fehler, nichts schreiben, starten oder speichern; den lokalen Kopf setzt nur der Agent |

Der Hash wird erst nach erfolgreichem Anwenden gespeichert (wie heute `sync.go:107`). Ein gescheiterter Schritt
wird beim nächsten Lauf wiederholt.

## Externe Integrationen (frp v0.69.1)

| Behauptung | Quelle | Stand |
|---|---|---|
| Reload übernimmt Proxies/Visitors, globale Parameter nicht („global client parameters won't be modified except 'start'“) | [README v0.69.1](https://github.com/fatedier/frp/blob/v0.69.1/README.md), Abschnitt „Hot-Reloading frpc configuration“ | per WebFetch geprüft, 2026-10-16 |
| `webServer.addr/port/user/password` aktivieren die Admin-API, `frpc reload -c <datei>` | README, Abschnitte „Hot-Reloading“ und „Client Admin UI“ | per WebFetch geprüft |
| `loginFailExit` ist standardmäßig `true` und steht als Top-Level-Schlüssel in der TOML | [`pkg/config/v1/client.go`](https://github.com/fatedier/frp/blob/v0.69.1/pkg/config/v1/client.go) ~Z. 54–57 (Feld), ~Z. 88 (`Complete()`) | per WebFetch geprüft |
| Unveränderte Proxies bleiben beim Reload laufen (Vergleich per `reflect.DeepEqual`), offene Verbindungen eines geänderten Proxys laufen aus | `client/proxy/proxy_manager.go` Z. 139–182, `client/proxy/proxy.go` Z. 120, `client/service.go` Z. 381–408 | aus dem Code gelesen (Planungs-Agent), **nicht Ende-zu-Ende geprüft**; der Szenario-Test in T7 belegt es |
| Nach dem ersten erfolgreichen Login verbindet frpc unbegrenzt neu, unabhängig von `loginFailExit` | `client/service.go` Z. 258–300 | aus dem Code gelesen (Planungs-Agent) |
| Basic-Auth der Admin-API nur mit gesetztem `user`/`password`; `/healthz` ohne Auth; `GET /api/config` liefert Token und Secrets | `pkg/util/net/http.go` Z. 45–50, `client/api_router.go` | aus dem Code gelesen (Planungs-Agent) |
| Ist der Admin-Port belegt, startet frpc nicht | `client/service.go` Z. 187–192 | aus dem Code gelesen (Planungs-Agent) |
| Kein Reload per Signal | `cmd/frpc/sub/root.go` Z. 116–118 | aus dem Code gelesen (Planungs-Agent) |

Der Builder prüft die mit „aus dem Code gelesen“ markierten Stellen vor T4 und T6 per WebFetch gegen die
gebündelte Version (`FRP_VERSION` in `.github/workflows/*.yml`).

## Trade-offs & Alternativen

- **`hash: null` auch bei 0 Tunneln.** Verworfen (in T8 kurz gebaut, im Review verworfen): Ein alter Agent
  liest `null` als Änderung, bekommt 404 von `/config` und ließe frpc mit dem letzten Tunnel laufen. Gewählt:
  Text ohne Token und ohne Tunnel (fail-closed, siehe API-Vertrag).
- **Agent nur mit Neustart.** Einfacher, aber jede Tunnel- oder `allowUsers`-Änderung trennt alle Sitzungen
  zum Host. Kevin wählt Reload, als letzte Task (T6). Bis dahin startet der Agent bei Änderungen neu wie heute.
- **Ein frpc je Tunnel.** Keine Admin-API nötig, aber N Verbindungen zu frps und eine aufgeteilte TOML.
  Verworfen.
- **Common-Vergleich:** Text vor dem ersten `[[proxies]]`, gestützt durch den Generator-Test in T1. Die
  Alternative wäre eine TOML-Bibliothek als neue Abhängigkeit im Agent. Nicht nötig, solange der Server das
  Layout festhält.
- **Reload-Weg:** `frpc reload -c /etc/frp/frpc.toml` als Kindprozess. Er liest die Zugangsdaten aus der Datei,
  der Agent braucht keinen eigenen HTTP-Client. Die Alternative `GET /api/reload` aus Go wäre mehr Code, ohne
  Nutzen. Scheitert der Reload, folgt ein Neustart.
- **Admin-API auf Agent-Hosts (Kevin: ja, letzte Task).** Ein zusätzlicher Listener auf 127.0.0.1. Ohne Passwort
  käme jeder lokale Prozess an das frps-Token (`GET /api/config`) und könnte frpc stoppen. Deshalb ist ein
  zufälliges Passwort mit 32 Byte (hex) in einer 0600-Datei Pflicht. Wechselt der Port, wechselt auch das
  Passwort; der Reload geht nur an den Listener von root auf diesem Port.

## Risiken & Rollback

- **Neuer Agent gegen alten Server** ohne FRP-Config: dauerhafter Fehler, siehe Kompatibilität.
- **Admin-Port nach Reboot belegt:** frpc startet bis zum nächsten Agent-Lauf (≤ ~5,5 min) nicht. Danach wählt
  der Agent einen neuen Port. Restrisiko: Tunnel des Hosts fehlen in diesem Fenster.
- **Reload trennt doch offene Verbindungen:** Das widerlegt der Szenario-Test in T7, sonst greift der Neustart wie
  heute. Kein Datenverlust.
- **Token-Rotation** (frps übernimmt nach ≤10 s, eigenes Vorhaben): Agents haben bis zum nächsten Timer-Lauf
  keinen Tunnel. Das hat Kevin hingenommen, die Mitteilung nennt es.
- **Rollback:** Revert des Branches. Bestandshosts bleiben funktionsfähig (siehe Kompatibilität), `admin.conf`
  bleibt ungenutzt. Hat der neue Agent frpc deaktiviert und kommt nach dem Rollback ein Tunnel dazu, startet
  der alte Sync frpc nur per `systemctl restart` ohne `enable`; nach einem Reboot bleibt frpc dann aus, bis neu
  provisioniert wird oder ein Paket-Update läuft.

## Doku-Impact

Sichtbar, also DE + EN:
- `admin/agent-deployment.html`: Ein später angelegter Tunnel greift beim nächsten Agent-Lauf. Ohne Tunnel läuft
  kein frpc. Wer vor diesem Release ohne Tunnel provisioniert hat, provisioniert einmal neu.
- `developer/agent.html`: Ablauf des Abgleichs, lokale Admin-API.
- `developer/server.html:99` und `developer/api-reference.html:163`: config-hash mit `null`.
- `CHANGELOG.md`: Fixed und Changed (API).

## Offene Fragen

Keine. Entschieden von Kevin am 2026-10-16:

1. **Reihenfolge zu R-0384** (Status `pr`, `feature/agent-identity-lock`): Beide ändern
   `apps/agent/internal/provision/provision.go` und `provision_test.go`. R-0398 wird nach dem Merge von R-0384
   gebaut.
2. **Multibox-Flags** für den Beweis: `scenario --agents 1 --tunnel --enforce` (`--enforce`, weil der Abgleich
   unter erzwungenem mTLS über die an den Server gebundene Route läuft, R-0315).
3. **Neuer Agent gegen alten Server:** hingenommen. Agents kommen aus dem Paket-Repo des Servers, die Versionen
   kommen gemeinsam; der Agent liest 404 „Keine FRP-Config vorhanden“ nicht über den Meldungstext als `null`.
