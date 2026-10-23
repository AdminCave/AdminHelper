<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: eine Vertrauensquelle je Aufruf, PKI-Bundle-Pfad entfernt, Diagnose-Bericht als neue Datei, Server-Text der frpc.toml in Generator-Form

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/agent-hardening.md`. Härtung des Agents (Kevin 2026-10-22), Komponente `agent`, dazu ein Paritäts-Test im
Server (T9).

## Problem / Motivation

1. **`--insecure` gilt nicht immer nur für den einen Aufruf.** Die Doku verspricht es:
   `docs/admin/agent-deployment.html:188` — „`--insecure` gilt nur fuer den einmaligen `provision`- oder
   `monitor init`-Aufruf: der Agent erfasst dabei das vom Server praesentierte Zertifikat und pinnt es
   (Trust-on-first-use) … Mit `--cacert` wird gar nichts uebersprungen.“ (EN `docs/en/admin/agent-deployment.html:187`).
   Zwei Wege schreiben trotzdem `INSECURE=1` in die Konfiguration, die jeder spätere Lauf liest:
   - `monitor init --insecure` ohne `--cacert`: scheitert das Abrufen oder Speichern des Server-Zertifikats, bleibt es
     bei einer Warnung (`apps/agent/internal/monitor/monitor.go:86-98`), und `monitor.conf` bekommt `INSECURE=1`
     (`:117-119`).
   - `--cacert` zusammen mit `--insecure`: `monitor.Init` pinnt nur ohne `--cacert` (`monitor.go:86`) und schreibt
     `CACERT` und `INSECURE=1` (`:114-119`); `provision` reicht `insecure` in diesem Fall unverändert weiter
     (`apps/agent/internal/provision/provision.go:241-244`) an `monitor.Init` (`:159-166`). Liegen beide Werte vor, gilt
     `insecure` (`apps/agent/internal/httpclient/httpclient.go:52-54`), also gerade nicht „mit `--cacert` wird nichts
     übersprungen“. Für `--ca-fp` lehnt `provision` jede Kombination schon ab (`provision.go:89-94`).
   Der Sync-Teil (`frpc.WriteSyncConfig`) schreibt `INSECURE=1` nur ohne CA (`apps/agent/internal/frpc/apply.go:74-94`);
   `provision` übergibt das heute nur, wenn der Aktivierungsaufruf kein Zertifikat gesehen hat (`provision.go:242`).

2. **Der Pfad für ein PKI-Bundle ist ungenutzt.** Der Server schickt `pkiBundle` seit A7 (0.28.0) immer leer
   (`apps/server/app/modules/provisioning/helpers.py:107`, gepinnt in `apps/server/tests/test_provisioning.py:350`,
   Doku `docs/developer/api-reference.html:156`). Der Agent entpackt ein geliefertes Bundle trotzdem nach `FrpDir`
   (`apply.go:123-133`, `extractPkiBundle` `:161-253`), also neben `adminhelper.conf`, `admin.conf` und `frpc.toml`,
   nicht nach `pki/`; der Kommentar `:123-127` beschreibt noch den alten Weg. Server vor A7 kann dieser Agent ohnehin
   nicht provisionieren: er aktiviert nur über die Enroll-Plane `:8444` (`provision.go:68-70`, `:362-379`), die es seit
   0.39.0 gibt (`CHANGELOG.md:2382-2387`). `config.FrpPkiDir` (`apps/agent/internal/config/paths.go:21`) legt nur noch
   ein leeres Verzeichnis an (`apply.go:53-61`).

3. **Diagnose-Bericht unter festem Namen.** `adminhelper-agent diagnostics` schreibt den Bericht per `os.WriteFile`
   nach `os.TempDir()/adminhelper-agent-diagnostics-<UTC-Sekunde>.txt`
   (`apps/agent/internal/diagnostics/diagnostics.go:70-71`). `os.WriteFile` (Go-Doku, `go doc os.WriteFile`):
   „otherwise WriteFile truncates it before writing, without changing permissions“ — eine vorhandene Datei dieses
   Namens wird gekürzt und überschrieben, ihr Eigentümer und ihre Rechte bleiben, und ein Symlink an der Stelle wird
   verfolgt. Gewollt ist: jeder Lauf legt eine neue Datei an, die nur dem Aufrufer gehört.

4. **Der Server-Text der frpc.toml wird bis auf den lokalen Kopf unverändert übernommen.** `applyConfig`
   (`apps/agent/internal/frpc/sync.go:174-226`) prüft nur, dass der Text keinen Schlüssel des lokalen Kopfs setzt
   (`checkServerHead`, `:300-318`), und schreibt ihn sonst so, wie er kommt. Der Desktop übernimmt die visitor.toml nur
   in der Form, die `generate_visitor_toml` schreibt (`apps/desktop/src-tauri/src/frpc.rs:335-466`,
   `validate_visitor_table`), der frps-Supervisor die frps.toml nur in der Form von `generate_frps_toml`
   (`apps/server/app/modules/frp/extra_config.py:5-14`). Für den Agent fehlt das Gegenstück. Dazu:
   - frp entscheidet am **Rohtext**, ob eine Datei Alt-INI ist (`pkg/config/load.go`, `DetectLegacyINIFormat`: der Text
     lässt sich als INI laden und hat einen Abschnitt `common`), erst danach liest es TOML. TOML und INI lesen denselben
     Text verschieden; nur ein Text aus einzeiligen Werten und den zwei Tabellenköpfen des Generators ist für beide
     eindeutig.
   - Proxy-Plugins (`[proxies.plugin]`, gleichwertig `plugin.<key>` in einer `[[proxies]]`-Tabelle) schreibt der
     Generator nicht (`apps/server/app/modules/frp/config_generator.py:247-311`). Das `extra_config` eines Tunnels nimmt
     aber jeden Schlüssel aus `A-Z a-z 0-9 _ . -` (`apps/server/app/modules/frp/schemas.py:51-76`); Probe 2026-10-22:
     `FrpTunnelCreate` mit `extra_config={"plugin.type": …}` wird angenommen, der Generator schreibt die Zeile in den
     Proxy, und frpc 0.69.1 liest sie als Plugin (`frpc verify` meldet für `plugin.type = "no_such_plugin"` wie für
     `PLUGIN.type = "no_such_plugin"` „unknown plugin type“). In keiner UI und in keiner Doku ist das als Weg
     beschrieben (offene Frage 1).

## Ziel & Nicht-Ziele

Ziel:
- **Eine Vertrauensquelle je Aufruf** (T1, T2): `provision` und `monitor init` lehnen `--cacert` zusammen mit
  `--insecure` ab, bevor sie etwas schreiben oder (bei `provision`) den Token senden. Ein blindes `--insecure`, dessen
  Zertifikat sich nicht pinnen lässt, bricht ab, statt die Prüfung abzuschalten. `monitor.conf` und
  `adminhelper.conf` bekommen nie `INSECURE=1` (T2, T3).
- **Kein PKI-Bundle-Pfad mehr** (T4, T5): `extractPkiBundle`, `ApplyParams.PkiBundleB64`, das Feld `pkiBundle` der
  Aktivierungsantwort im Agent und `config.FrpPkiDir` entfallen; ein mitgeschicktes `pkiBundle` ignoriert der Agent.
- **Diagnose-Bericht als neue Datei** (T6): `os.CreateTemp` in `os.TempDir()` (0600, zufälliger Namensteil, nie eine
  vorhandene Datei); der Pfad wird wie bisher ausgegeben.
- **Server-Text in Generator-Form** (T7, T8): `applyConfig` übernimmt nur einen Text, dessen Zeilen die Formen von
  `generate_frpc_toml` haben und dessen Wurzel- und `transport.tls`-Schlüssel genau die des Generators sind; sonst
  Fehler, nichts geschrieben, nichts gestartet, wie heute bei `checkServerHead`. T8 (offene Frage 1): kein Schlüssel der
  `plugin`-Familie in einem Proxy.
- **Parität Generator ↔ Agent** (T9): eine gemeinsame Fixture; ändert der Generator seine Ausgabe, wird ein
  Server-Test rot, bis die Fixture und damit die Agent-Prüfung nachgezogen sind.

Nicht-Ziele (YAGNI):
- Keine Änderung für vorhandene Konfigurationen mit `INSECURE=1`: der Agent liest sie weiter wie bisher
  (`apps/agent/internal/config/config.go:116`, `:139`), und `httpclient.New` behält seine Reihenfolge (offene Frage 2).
- Keine Änderung an den Paketen: `postinst` (`apps/agent/deb/DEBIAN/postinst:4`, `:7`), `adminhelper-agent.spec`
  (`:37`, `:54`) und `build-rpm.sh:27` legen `/etc/frp/pki` weiter an (leer, harmlos; offene Frage 4).
- Keine Prüfung der Werte über die Schlüssel hinaus (Adressen, Ports, TLS-Pfade); nur `auth.method` muss `"token"`
  sein, wie beim Desktop (`frpc.rs:389-398`). Keine Einschränkung von `type` oder `localIP`.
- Kein TOML-Parser als neue Abhängigkeit (`apps/agent/go.mod` hat keinen): die Zeilenform ist eng genug für eine
  Zeilenprüfung, und frpc bekommt weiter den Text des Servers (Hash und Common-Teil bleiben, `sync.go:286-298`).
- Keine Server-Änderung an `extra_config` (offene Frage 3), kein neues Feld, keine Route.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | agent | `apps/agent/internal/provision/provision.go`, `apps/agent/internal/provision/provision_test.go`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `CHANGELOG.md` |
| T2 | agent | `apps/agent/internal/monitor/monitor.go`, `apps/agent/internal/monitor/init_test.go`, `apps/agent/cmd/adminhelper-agent/main.go`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `CHANGELOG.md` |
| T3 | agent | `apps/agent/internal/frpc/apply.go`, `apps/agent/internal/frpc/apply_test.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html` |
| T4 | agent | `apps/agent/internal/frpc/apply.go`, `apps/agent/internal/frpc/apply_test.go`, `apps/agent/internal/provision/provision.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `CHANGELOG.md` |
| T5 | agent | `apps/agent/internal/config/paths.go`, `apps/agent/internal/frpc/apply.go`, `apps/agent/internal/frpc/apply_test.go`, `apps/agent/internal/config/securedir_windows.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `CHANGELOG.md` |
| T6 | agent | `apps/agent/internal/diagnostics/diagnostics.go`, `apps/agent/internal/diagnostics/diagnostics_test.go`, `CHANGELOG.md` |
| T7 | agent | `apps/agent/internal/frpc/servertoml.go` (neu), `apps/agent/internal/frpc/servertoml_test.go` (neu), `apps/agent/internal/frpc/testdata/server_frpc.toml` (neu), `apps/agent/internal/frpc/sync.go`, `apps/agent/internal/frpc/sync_flow_test.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `CHANGELOG.md` |
| T8 | agent | `apps/agent/internal/frpc/servertoml.go`, `apps/agent/internal/frpc/servertoml_test.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T9 | server | `apps/server/tests/test_config_generator.py`, `apps/agent/internal/frpc/testdata/server_frpc.toml` |

Auf der Risikoliste (`scripts/dev/review-risk.txt`): `apps/agent/internal/provision/*` und `apps/agent/internal/frpc/*`
— T1, T3, T4, T5, T7, T8 bekommen zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine Migration, keine Route, kein Schema. Die Aktivierungsantwort behält `frp.pkiBundle` (der Server schickt `""`,
`docs/developer/api-reference.html:156`); der Agent liest das Feld nur nicht mehr. Kein Vertrags-Drift zu Server, Web
oder Desktop. Sichtbar ändern sich Fehlermeldungen und Abbrüche der CLI (T1, T2), der Dateiname des Diagnose-Berichts
(T6) und dass ein Server-Text außerhalb der Generator-Form nicht angewendet wird (T7, T8).

## Externe Integrationen

- **frp v0.69.1** (Version aus `.github/workflows/ci.yml:24`), Quelle gelesen 2026-10-22 unter
  https://github.com/fatedier/frp/tree/v0.69.1:
  - `pkg/config/load.go`: `DetectLegacyINIFormatFromFile` liest die Datei roh (vor dem Template-Rendern) und gibt sie an
    `DetectLegacyINIFormat`; das lädt sie mit `gopkg.in/ini.v1` (`ini.Load(content)`, ohne Optionen) und gilt als
    Alt-INI, wenn es einen Abschnitt `common` gibt. Sonst rendert frp die Datei als Go-Template (`RenderWithTemplate`,
    `{{` öffnet eine Aktion) und liest sie bei der Endung `.toml` mit `github.com/pelletier/go-toml/v2`; ein
    TOML-Fehler ist dann ein Fehler (kein Rückfall auf YAML). Das Ergebnis geht über JSON in die Structs.
  - `pkg/util/jsonx/json_v1.go`: `encoding/json`, mit `DisallowUnknownFields` im strikten Modus; die Zuordnung von
    Namen ist die von `encoding/json`, also ohne Groß-/Kleinschreibung. `pkg/config/v1/decode.go`: der Proxy holt sein
    Plugin aus dem Member `plugin`.
  - `conf/frpc_full_example.toml`: Wurzel-Schlüssel u. a. `includes`, `log.to`, `auth.tokenSource.*`,
    `webServer.*`, `transport.*`; Proxy-Plugins `unix_domain_socket`, `http_proxy`, `socks5`, `static_file`,
    `https2http`, `https2https`, `http2https`, `http2http`, `tls2raw`, `virtual_net`.
  - Proben mit frpc 0.69.1 (das Desktop-Sidecar-Binary, `frpc verify -c`), je dreimal identisch: siehe Problem 4.
- **Go** (`go doc`, go1.26.9): `os.WriteFile` wie oben; `os.CreateTemp`: „The filename is generated by taking pattern
  and adding a random string to the end … The file is created with mode 0o600 (before umask). If dir is the empty
  string, CreateTemp uses the default directory for temporary files, as returned by TempDir.“

## Trade-offs & Alternativen

1. **`--cacert` mit `--insecure` (T1, T2).** (a) Ablehnen wie `--ca-fp` — **Empfehlung**, eine Regel für alle drei
   Vertrauensquellen, und der Aufruf scheitert, bevor etwas geschrieben oder der Token gesendet ist. (b) `--cacert`
   gewinnt still: ein Flag ohne Wirkung. (c) `httpclient.New` dreht die Reihenfolge: änderte auch vorhandene
   Konfigurationen (offene Frage 2).
2. **Wo die Server-Text-Prüfung sitzt (T7).** In `applyConfig` statt `checkServerHead` (`sync.go:189`) — **Empfehlung**:
   Sync und Provisionierung (`Apply`) laufen beide dort durch, und der Hash bleibt der des Server-Texts. Die Prüfung
   ersetzt `checkServerHead` und `localHeadKeys` (`:300-318`): Kopf-Schlüssel stehen nicht in der Allowlist.
3. **Zeilenprüfung statt TOML-Parser (T7).** (a) Zeilenprüfung gegen die Formen des Generators — **Empfehlung**: keine
   neue Abhängigkeit; eine Zeile hat genau eine Lesart, weil mehrzeilige und Literal-Strings, Escapes, Inline-Tabellen,
   Kommentare und andere Tabellenköpfe abgelehnt sind; der Text bleibt der des Servers. (b) `pelletier/go-toml/v2`
   parsen und neu schreiben (wie der Desktop mit `toml`): neue Abhängigkeit, und der geschriebene Text wiche vom
   Server-Text ab (Common-Teil-Vergleich `sync.go:286-298`, Reload-Entscheidung).
4. **Proxy-Ebene (T8, offene Frage 1).** (a) Die `plugin`-Familie ablehnen (erstes Schlüsselsegment `plugin`, ohne
   Groß-/Kleinschreibung), alle anderen `extra_config`-Schlüssel bleiben — **Empfehlung**. (b) Feste Allowlist der
   Proxy-Schlüssel (Generator plus eine Liste von frp-Optionen): strenger, kann vorhandene `extra_config`-Einträge
   ablehnen und muss mit frp gepflegt werden. (c) Nichts auf Proxy-Ebene.
5. **Parität (T9).** Eine Fixture im Agent (`testdata/server_frpc.toml`), die T7 gegen die Prüfung testet und T9 gegen
   `generate_frpc_toml` — **Empfehlung**: ein Generator-Umbau ohne Agent-Nachzug wird im Server-Test rot statt erst im
   Sammellauf. Ein Server-Test liest schon Dateien anderer Komponenten (`apps/server/tests/test_certificate_check.py:219`).
   Alternative: nur ein Kommentar wie beim Desktop (`frpc.rs:341-344`).

## Risiken & Rollback

- **T7 lehnt eine echte Server-Ausgabe ab** → Tunnel-Änderungen kommen auf dem Host nicht mehr an (frpc läuft auf dem
  alten Stand weiter, Fehler bei jedem Lauf im Agent-Log). Abgefangen durch T9 (Fixture = Generator-Ausgabe für beide
  Tunnelarten und `extra_config` mit Zeichenkette, Bool und Ganzzahl; Gleitzahlen prüft T7 eigens), die bestehenden
  Sync-Tests und den Sammellauf
  (`desktop_e2e_connect_tunnel`, `upgrade_path`). Der Generator schreibt seit 0.25.0 dieselben Wurzel-Schlüssel
  (`git show 5c9608aa:apps/server/app/modules/frp/config_generator.py`).
- **T1/T2 brechen bisher erfolgreiche Aufrufe ab**: `--cacert` mit `--insecure` und ein blindes `--insecure`, dessen
  Zertifikat sich nicht holen lässt. Die Meldung nennt den Ausweg (`--cacert` allein bzw. `--ca-fp`). Die
  Install-Skripte rufen `provision` nie mit beiden (`scripts/agent-install.sh:318-334`), die Desktop-Befehle ebenso
  wenig (`apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte:80-82`).
- **T4/T5**: ein Agent gegen einen Server vor 0.28.0 bekäme kein Bundle mehr — solche Server kann er schon heute nicht
  provisionieren (Problem 2).
- **T6**: der Dateiname enthält einen Zufallsteil; wer den Namen aus dem Zeitstempel ableitet, findet ihn nicht. Die
  Ausgabe nennt den Pfad.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T1, T2: `docs/admin/agent-deployment.html:188` (EN `:187`), der Absatz zu `--insecure`: nicht mit `--cacert`
kombinierbar; lässt sich das Zertifikat nicht pinnen, bricht der Aufruf ab. T3: `docs/developer/agent.html:81` (DE+EN),
`INSECURE` wird nur noch gelesen. T4, T5: `docs/developer/agent.html:46`, `:78`, `:79` (DE+EN), ohne Bundle und ohne
`frp\pki`. T7, T8: `docs/developer/agent.html:97` (DE+EN), welche Form der Agent übernimmt; T8 dazu
`docs/developer/api-reference.html:141` (DE+EN). CHANGELOG (umlautfrei) für T1, T2, T4 (mit T5), T6, T7, T8.

## Offene Fragen

1. **T8: Proxy-Plugins aus `extra_config` ablehnen?** Heute kommen sie über die API durch (Problem 4). Empfehlung:
   ja, die ganze `plugin`-Familie (Trade-off 4a); kein anderer `extra_config`-Schlüssel ist betroffen. Wer ein Plugin
   über `extra_config` nutzt, bekommt auf dem Host keine Tunnel-Änderung mehr, bis der Eintrag weg ist. T8 steht auf
   `[?]`; T7 und T9 hängen nicht daran.
2. **Vorhandene Konfigurationen mit `INSECURE=1`** (aus Versionen vor 0.25.0 oder aus den Wegen in Problem 1)?
   Empfehlung: weiter lesen wie bisher; nach dem Enrollment nutzt der Agent ohnehin mTLS mit gepinnter CA
   (`apps/agent/internal/enroll/client.go:35-50`). Alternativen: beim Lesen ignorieren (Hosts ohne Enrollment mit
   selbstsigniertem Zertifikat verlieren Push und Sync bis zur Neu-Provisionierung) oder eine Warnung je Lauf. Keine
   Task hängt daran.
3. **Server: `plugin`-Schlüssel in `extra_config` mit `422` ablehnen?** Empfehlung: nach Antwort auf 1 als eigene
   Roadmap-Zeile (Server, `schemas.py`), nicht in diesem Paket — der Agent prüft unabhängig vom Server, und
   `schemas.py` ist eine Contract-Datei paralleler Server-Vorhaben.
4. **`/etc/frp/pki` aus den Paketen nehmen?** Empfehlung: nein, das leere Verzeichnis stört nicht, und eine Änderung an
   `postinst`/Spec/`build-rpm.sh` bräuchte einen Paket-Lauf.
