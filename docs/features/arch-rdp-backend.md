<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Eingebettetes RDP, Stufe 1: Backend

Architektur-Vorhaben `arch-rdp-backend` (Roadmap R-1097), Stufe 1 des Bauplans aus
[`arch-rdp-embedded.md`](arch-rdp-embedded.md) (R-1074, Entscheidung Kevin 2026-11-02: V2 = IronRDP nativ, Bild über
einen lokalen WebSocket). Stand: `origin/main@a3645c00`; IronRDP auf Revision `f96f664a`.

## Problem / Motivation

Der Desktop öffnet RDP heute nur über einen externen Client (`xfreerdp3`, `mstsc`, `connection/rdp.rs`). R-1074 hat
entschieden, RDP zusätzlich im Desktop selbst zu zeigen, mit IronRDP im Rust-Prozess und dem Bild über einen lokalen
WebSocket an den Webview. Stufe 1 baut den Teil ohne Oberfläche: Abhängigkeit, Sitzung, TLS-Prüfung, Bildweg,
Watchdog und einen Integrationstest gegen einen echten xrdp. Die Stufen 2 bis 5 (Tab, Kanäle, Anzeige, Fenster) setzen
darauf auf.

## Ziel & Nicht-Ziele

**Ziel:**
- `ironrdp-client` und `ironrdp-tls` als Git-Abhängigkeit, gepinnt auf eine Revision. Unter Windows kommt
  `ironrdp-egfx-native` (Media Foundation) dazu; es ist dort eine feste Abhängigkeit von `ironrdp-client`.
- Lizenz-Gates als Test im Build: `aws-lc-rs`, `aws-lc-sys` und `openh264-sys2` fehlen im Abhängigkeitsgraphen,
  `ring` ist da (Gegenprobe). Dazu ein neu erzeugter Abschnitt 3 in `THIRD_PARTY_LICENSES.md`.
- Eine Sitzung startet aus einer gespeicherten RDP-Verbindung:
  - Ziel aus `resolve_connection` (direkt oder über den FRP-Tunnel);
  - Passwort aus dem Keyring, mit denselben Prüfungen wie `open_connection_stored` (`reject_foreign_port`,
    `checked_password_source`).
- TLS-Prüfung mit TOFU-Pin je Ziel (Bedingung 5). Ein Befehl übernimmt einen bestätigten Fingerprint.
- Watchdog gegen den Bildstillstand (Bedingung 2).
- Lokaler WebSocket für Bild und Eingabe: nur auf 127.0.0.1, ein Token je Sitzung, Gegendruck über Quittungen
  (Bedingung 3). Die CSP bekommt `ws://127.0.0.1:*`.
- Phasen-Events an den Webview: verbinden, verbunden, neu verbinden, Zertifikat, getrennt, fehlgeschlagen.
- Ein Integrationstest gegen einen xrdp-Container mit GFX. Er läuft als `desktop_e2e_*`-Suite im E2E-Layer.

**Nicht-Ziele (YAGNI):**
- Keine Oberfläche: kein Tab, kein Canvas, kein Zertifikatsdialog, keine Einstellung `rdp_client`. Das ist Stufe 2.
  Bis dahin ruft niemand die neuen Befehle auf, und der OS-Client bleibt der einzige Weg (Bedingung 4).
- Keine Zwischenablage, kein Audio, keine Laufwerke (Stufe 3):
  - Die Features `clipboard` und `rdpdr` sind gebaut, aber die Sitzung schaltet keinen Kanal ein.
  - `sound` bleibt ganz aus, siehe Entscheidung E2.
- Kein Resize, kein Monitor-Layout, kein `ResetGraphics`-Abschluss (Stufe 4, Bedingung 10); die Sitzung hat eine
  feste Größe.
- Kein RD-Gateway und kein H.264 unter Linux (Bedingung 7).
- Kein neuer CI-Job. Der xrdp-Test läuft im E2E-Layer (`run.sh e2e`, Sammellauf). Ein eigener Job ändert
  `.github/workflows/`, das merged Kevin; er wird eine Folgezeile.

## Betroffene Komponenten & Dateien

Nur der Desktop-Rust-Teil und ein neues Testskript; Server, Web, Agent und Desktop-UI bleiben unberührt.

| Datei | Änderung |
|---|---|
| `apps/desktop/src-tauri/Cargo.toml`, `Cargo.lock` | `ironrdp-client` (ohne Default-Features, `clipboard`, `rdpdr`), `ironrdp-tls` (`rustls-ring`), `tokio-tungstenite` (Server-Handshake), `tokio` um `rt` |
| `apps/desktop/src-tauri/src/rdp_embedded/` (neu) | `mod.rs` (Sitzungstabelle, Tauri-Befehle, Phasen-Events), `tofu.rs` (Pin-Identität, Entscheidung, Callback, Befehl `rdp_trust_certificate`), `session.rs` (IronRDP-Konfiguration, Sitzungs-Thread, Neuverbindung), `watchdog.rs` (reine Zustandsmaschine), `frame_ws.rs` (WebSocket, Token, Bildpuffer, Gegendruck, Eingabe), `license_gate.rs` (Test) |
| `apps/desktop/src-tauri/src/tofu.rs` (Risikopfad) | `fingerprint` ist `pub(crate)`. `PinStore`, `KeyringPinStore::production`, `decide` und `PinDecision` werden `pub(crate)`, damit RDP denselben Keyring-Speicher nutzt. Keine Verhaltensänderung für den Server-Pin. |
| `apps/desktop/src-tauri/src/main.rs` | `mod rdp_embedded;`, `.manage(RdpSessions)` (`main.rs:127`–`130`), die drei Befehle im `generate_handler!` (`main.rs:220`) |
| `apps/desktop/src-tauri/tauri.conf.json` | CSP `connect-src` um `ws://127.0.0.1:*` (`tauri.conf.json:16`) |
| `scripts/tests/desktop_e2e_rdp_embedded.sh` (neu) | startet den xrdp-Container, fährt den ignorierten Rust-Integrationstest, räumt auf |
| `scripts/tests/xrdp-gfx/Dockerfile`, `entrypoint.sh` (neu) | xrdp 0.10 mit GFX auf Debian trixie (Digest-Pin), Testnutzer `e2e`, selbstsigniertes Zertifikat |
| `THIRD_PARTY_LICENSES.md` | Abschnitt 3 (Rust) neu erzeugt (`scripts/gen-third-party-licenses.sh`), dazu Apache-NOTICE, falls neue Pakete eine tragen |
| `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `changelog.d/arch-rdp-backend.md` | Doku (T7) |

**Wiederverwendet:**
- `commands.rs:421` `open_connection_stored` als Muster für den Start-Befehl. Er übernimmt:
  - den Sitzungs-Schnappschuss (Tunnel, Verbindungen, frpc-Bindungen);
  - `run_with_deadline` (`commands.rs:347`);
  - `reject_foreign_port` (`commands.rs:370`).
- `connection/mod.rs:121` `CredentialConnection` mit `checked_password_source` (`connection/mod.rs:182`) und
  `check_credential_connection` (`connection/mod.rs:209`): gleiche ID, Art, Nutzer, Domäne, kein breiteres Vertrauen.
- `password.rs:121` `load_password_keyring`. Nie der TERMSRV-Weg für `mstsc`.
- `tunnel.rs:76` `resolve_connection` für Ziel-Host und -Port, dazu Tunnelname und Tunnelart.
- `tofu.rs:40` `fingerprint` (SHA-256 des Leaf-DER, hex), `tofu.rs:95` `PinStore`, `tofu.rs:134` `KeyringPinStore`
  (Cache, Sperre je Identität, Fail-closed-Lesen), `tofu.rs:272` Keyring-Schlüssel `tofu|cert|<identität>`.

## Datenmodell / API / Migrationen

Keine Migration, kein Server-Vertrag, keine Änderung an `models.rs`. Neu sind drei Tauri-Befehle und ein Event. Der
Webview ruft sie erst in Stufe 2 auf; bis dahin sind sie interner Vertrag zwischen Backend und UI.

**Befehle:**
- `rdp_session_start(connection: Connection) -> { session_id, ws_port, token }`. Er:
  - prüft wie `open_connection_stored` (Art `rdp`, Port, Passwortquelle);
  - löst das Ziel auf und liest das Passwort aus dem Keyring;
  - liest den Pin der Ziel-Identität vor dem Verbindungsaufbau;
  - startet die Sitzung und kehrt zurück, sobald der WebSocket lauscht. Der Verbindungsaufbau läuft dann im
    Hintergrund weiter und meldet sich über Phasen-Events.

  Ein Fehler vor dem Start kommt als `AppError` zurück (gleiche Codes wie `open_connection_stored`).
- `rdp_session_stop(session_id)` beendet die Sitzung und den WebSocket; unbekannte IDs sind kein Fehler.
- `rdp_trust_certificate(identity, fingerprint)` speichert genau den Fingerprint, den der Nutzer bestätigt hat (Dialog
  in Stufe 2), als Pin der Identität. Der Webview startet danach neu. Der Befehl prüft Form und Länge beider Werte
  (64 Hex-Zeichen; Identität mit Präfix `rdp/<workspace>/` des eigenen Prozesses, im Launcher keine).

**Event** `rdp-session`:

```json
{ "session_id": "…", "phase": "connecting|connected|reconnecting|certificate|disconnected|failed",
  "code": "…", "identity": "…", "fingerprint": "…", "reason": "unknown|changed" }
```

- `code` nur bei `failed` und `disconnected`, etwa `tls`, `auth`, `logon`, `watchdog`, `closed`.
- `identity`, `fingerprint` und `reason` nur bei `certificate`.

**WebSocket-Protokoll** (nur 127.0.0.1, Port vom System gewählt):
1. **Anmeldung:** Der Client schickt als erste Textnachricht das Token. Der Vergleich läuft in konstanter Zeit, mit
   Frist von 5 s. Ein falsches Token schließt die Verbindung, ein zweiter Client wird abgewiesen.
2. **Bild:** eine Binärnachricht je Bild. Kopf: Version, x, y, Breite, Höhe, Desktop-Breite, Desktop-Höhe, je u16
   little-endian. Danach die RGBA-Pixel des Rechtecks.
3. **Gegendruck:** Das nächste Bild geht erst nach der Quittung `{"t":"ack"}`. Was sich bis dahin ändert, fasst der
   Server zum umschließenden Rechteck zusammen, statt Bilder zu puffern. So wächst kein Rückstau, das Muster ist aus T3
   der R-1074-Probe.
4. **Eingabe** als Text-JSON:
   - `{"t":"key","code":<scancode>,"ext":bool,"down":bool}`
   - `{"t":"mouse","x":…,"y":…,"buttons":…,"wheel":…}`
   - `{"t":"close"}`

   Unbekannte oder fehlerhafte Nachrichten verwirft der Server, ohne die Sitzung zu beenden.

## Externe Integrationen

- **IronRDP** (Devolutions, MIT oder Apache-2.0): <https://github.com/Devolutions/IronRDP>, Revision
  `f96f664abf0bdfe547f222bcd37e09899f00f310`. Genutzte API:
  - `ironrdp_client::rdp::RdpClient::new(config, tx)`, `with_desktop_updates()`, `input_sender()`, `run()`;
  - `RdpOutputEvent`: `Connected`, `LoginComplete`, `DesktopUpdate`, `ConnectionFailure`, `AutoReconnecting`,
    `AutoReconnected`, `LogonError`, `Terminated`, die Zeiger-Events;
  - `ConfigBuilder`: `with_compression(false)`, `with_graphics_pipeline(true)`, `with_tls(true)`,
    `with_credssp(true)`, `with_certificate_validation(Strict)`, `with_certificate_validation_callback`.
- **rustls / ring** wie heute im Desktop (`Cargo.toml`: `rustls-no-provider`, rustls mit `ring`).
- **xrdp 0.10** mit GFX im Testcontainer. Debian trixie liefert xrdp 0.10 aus den Paketquellen.
- **WebSocket** RFC 6455 über `tokio-tungstenite` 0.29, das `ironrdp-client` schon zieht.

Das Verhalten von `RdpClient` (Events, Prüf-Callback, Sicherheitsprotokolle) ist aus den Quellen der gepinnten
Revision gelesen. Eine Doku-Seite dafür gibt es nicht; die Crates sind 0.x.

## Trade-offs & Alternativen

**TLS-Prüfung über den Callback statt eines eigenen `ServerCertVerifier`.**
- Bedingung 5 verlangt einen eigenen rustls-Prüfer nach dem Muster von `TofuVerifier` (`tofu.rs:314`).
- `RdpClient` nimmt aber keinen eigenen Prüfer an, nur:
  - `CertificateValidation::Strict` (Plattform-Wurzeln und Servername, `ironrdp-tls/src/rustls_verifier.rs`);
  - einen Callback, den IronRDP **nur dann** fragt, wenn die strenge Prüfung scheitert.
- Folge: Selbstsignierte Zertifikate, der Normalfall bei RDP und bei xrdp, laufen immer über unseren Pin. Über den
  Tunnel gilt das ebenso, denn der Servername ist dort `127.0.0.1`.
- Ein Zertifikat, das eine Plattform-CA für den Hostnamen ausgestellt hat, nimmt IronRDP dagegen ohne Pin an.
  - Das entspricht dem heutigen OS-Client: `xfreerdp3` und `mstsc` nehmen CA-gültige Zertifikate ebenfalls ohne
    Rückfrage an.
  - Es weicht aber vom „Pin immer“ des `TofuVerifier` ab.
- Alternativen:
  - (b) `ironrdp-tls` per `[patch]` lokal ändern, damit der Callback immer gefragt wird. Das heißt Fremdcode im Repo,
    der bei jedem Revisionswechsel nachgezogen werden muss.
  - (c) Eine Upstream-Option in IronRDP, die den Callback immer fragt. Das ist ein öffentlicher PR, und es ist offen,
    wann er gemergt wird.
- **Empfehlung (a)** für Stufe 1, (c) als Folgezeile: Stufe 1 hat keine Oberfläche, also erreicht niemand den Weg vor
  Stufe 2. Offene Frage 1.

**Erster Kontakt mit Dialog statt automatischem Pin.**
- Der Server-Pin (`TofuVerifier`) pinnt beim ersten Kontakt still.
- Bedingung 5 verlangt für RDP einen Fingerprint-Dialog. Ohne Pin lehnt die Sitzung deshalb ab und meldet `certificate`
  mit Fingerprint.
- `rdp_trust_certificate` speichert genau diesen Wert, und erst der Neustart verbindet.
- Den Pin schreibt also nie der Callback selbst. So kann keine Prüfung ein Zertifikat pinnen, das der Nutzer nicht
  gesehen hat.

**`trust_cert` (`models.rs:80`) heißt „ohne Dialog annehmen“** (Bedingung 5): Der Callback nimmt jedes Zertifikat an
und lässt Pins unberührt, wie heute `/cert:ignore`. `CertificateValidation::DangerouslyAcceptInvalidCertificate`
nehmen wir dafür nicht: Dann fragt IronRDP keinen Callback mehr, und das Event bekäme keinen Fingerprint für die
Statuszeile in Stufe 2.

**Pin-Identität mit Workspace und Tunnelname.**
- Direkt: `rdp/<workspace>/<host>:<port>` der gespeicherten Verbindung.
- Über einen Tunnel (`via_tunnel` aus `resolve_connection`): `rdp/<workspace>/<tunnel>/<host>:<port>`, mit Host und
  Port der gespeicherten Verbindung, nicht des lokalen Visitor-Endpunkts.
- Private Adressen wiederholen sich zwischen Standorten: dieselbe Adresse an zwei Standorten sind zwei Server, und ein
  gemeinsamer Pin wiese den zweiten fälschlich als geändert ab.
- Die Workspace-ID steht vorn, weil Tunnelnamen nur je Server eindeutig sind und die Server zweier Workspaces Tunnel
  und Adressen gleich benennen können; ein Pin gilt nur im Workspace, der ihn gesetzt hat. `rdp_trust_certificate`
  nimmt nur Identitäten des eigenen Workspaces an.
- `%` und `/` in Tunnelname und Host werden als `%25` und `%2F` geschrieben, damit `/` nur die Teile trennt.
- Der Präfix `rdp/` trennt die RDP-Pins von den Server-Pins (`host:port`) im selben Keyring-Namensraum.
- Der Callback gilt nur für das Ziel, zu dem die Sitzung aufgebaut wird (Endpoint `host:port` der IronRDP-Destination).
  Für jedes andere Ziel lehnt er ab, ohne einen Fingerprint zur Bestätigung zu melden.

**Pin vorab lesen statt im Callback.**
- Der Callback läuft im TLS-Handshake auf dem Sitzungs-Thread.
- Der Start-Befehl liest den Pin deshalb vorher, auf dem Thread mit Keyring-Zugriff; der Callback vergleicht nur
  Werte.
- Schlägt das Lesen fehl, startet die Sitzung nicht (fail closed, wie `PinDecision::Unavailable`).
- Nebeneffekt: Im Test genügt der Speicher-Keyring (`keyring_store.rs`), der nur im eigenen Thread gilt.

**Sitzung auf eigenem Thread.**
- `RdpClient` ist nicht `Send`. Jede Sitzung bekommt deshalb einen eigenen Thread mit einer `current_thread`-Laufzeit
  und einem `LocalSet`.
- Den WebSocket bedient dieselbe Laufzeit.
- Panics fängt die Sitzungsaufgabe ab und meldet sie als `failed`/`panic`, statt den Desktop zu beenden.
  Restrisiko FFI siehe R-1074.

**Watchdog als reine Zustandsmaschine** mit eingespeister Zeit:
- Nach `LoginComplete` muss binnen N s ein erstes Bild kommen.
- Ging eine Eingabe raus und kommt binnen N s kein Bild, gilt die Sitzung als stillstehend; das Backend baut sie
  neu auf, höchstens M-mal.
- Ein ruhiger Desktop ohne Eingabe löst nie aus, denn ohne Änderung schickt der Server kein Bild.
- N und M sind Konstanten im Code, mit Begründung aus T2 der Probe (Stillstand in einem von acht GFX-Läufen).

**xrdp-Test im E2E-Layer statt als CI-Job.**
- `run.sh` globt `scripts/tests/desktop_e2e_*.sh` in den E2E-Layer. Unter `--strict` ist jeder dieser Schritte
  Pflicht (`AH_HEAVY_E2E`).
- Den Vertrag prüft `desktop_e2e_skip_test.sh`: Fehlt `cargo tauri`, endet das Skript mit Exit 75 und
  „SKIP: tauri-cli“. Das neue Skript braucht nur `cargo` und Docker, prüft aber `cargo tauri` wie die anderen Suiten.
- Die GUI-Box, auf der die Suite läuft, hat beides.
- Ein eigener CI-Job wäre schneller sichtbar, ändert aber `.github/workflows/` (Merge durch Kevin) und braucht
  Docker-Images im CI. Er wird eine Folgezeile.

## Risiken & Rollback

- **CA-gültige Zertifikate ohne Pin** (Trade-off oben, Offene Frage 1). Erreichbar erst mit Stufe 2.
- **`SSLKEYLOGFILE`:**
  - `ironrdp-tls` setzt `KeyLogFile`. Ist die Variable gesetzt, schreibt rustls die TLS-Schlüssel der RDP-Sitzung in
    diese Datei.
  - Wer die Umgebung des Desktop-Prozesses setzen kann, hat das Konto ohnehin.
  - Curl und Browser verhalten sich gleich. Erwähnt in der Doku, keine Gegenmaßnahme.
- **Keine Plattform-Wurzeln:** Ist der Wurzelspeicher leer, scheitert jede strenge Prüfung, bevor der Callback kommt.
  IronRDP bricht dann mit „no usable roots“ ab. Die Sitzung meldet `failed`/`tls`. Unter Linux mit `ca-certificates`
  und unter Windows tritt das nicht auf.
- **Sicherheitsprotokoll:**
  - Die Sitzung setzt TLS und CredSSP ausdrücklich (`with_tls(true)`, `with_credssp(true)`); Standard-RDP-Sicherheit
    ohne TLS bleibt aus.
  - Ein Server, der nur Standard-RDP-Sicherheit anbietet, wird abgewiesen. Der Test belegt das nicht, xrdp bietet TLS.
- **`aws-lc-sys` im Lockfile:**
  - `Cargo.lock` führt `aws-lc-rs` und `aws-lc-sys` als optionale Pakete von IronRDP, gebaut werden sie nicht. Das
    Gate prüft deshalb `cargo tree`, nicht das Lockfile.
  - `cargo audit` (`audit.yml`) liest das Lockfile und könnte ein Advisory dieser Pakete melden, obwohl sie nicht im
    Build sind. Bei einem Treffer ist das eine Ausnahme mit Begründung, keine Code-Änderung.
- **Systembibliotheken in der CI:** Der `rust`-Job installiert GTK, WebKit und OpenSSL. Ob IronRDP ohne `sound`
  weitere `-dev`-Pakete braucht, zeigt der erste CI-Lauf von T1. Bräuchte es welche, ist das eine Workflow-Änderung:
  dann STOPP und Frage an Kevin.
- **Binärgröße:**
  - Die Probe-Binary war 26 MB groß.
  - Wie stark der Desktop wächst, misst T7 an einem Release-Build vor und nach dem Vorhaben.
  - Die Zahl kommt in die Doku und in den PR.
- **Abhängigkeit vor 1.0 auf Git-Revision:** Ein Wechsel der Revision ist eine eigene Zeile mit Lizenz-Gate und
  xrdp-Test.
- **Rollback:**
  - Die Befehle hat noch kein Aufrufer.
  - Ein Revert des Merge-Commits entfernt Abhängigkeit, Modul, CSP-Eintrag und Testskript vollständig.
  - Die RDP-Pins im Keyring (`tofu|cert|rdp/…`) bleiben dann liegen; sie sind harmlos und ohne Leser.

## Doku-Impact

- `docs/developer/desktop.html` und `docs/en/developer/desktop.html`, jeweils:
  - neuer Abschnitt „Eingebettetes RDP (Backend)“ mit Sitzung, Befehlen, Event, WebSocket-Protokoll, Watchdog und
    Testweg;
  - Ergänzung im Abschnitt „TLS-Zertifikat-Pinning (TOFU)“ um die RDP-Pins und die CA-Regel;
  - die neuen Befehle in der Befehlsliste.
- `THIRD_PARTY_LICENSES.md` Abschnitt 3, dazu `changelog.d/arch-rdp-backend.md`.
- Nutzer-Doku ändert sich nicht, denn es gibt noch keine Oberfläche.

## Offene Fragen

1. **CA-gültige RDP-Zertifikate ohne Pin** (Kevins Bereich: hingenommenes Restrisiko, Abweichung von Bedingung 5).
   - Empfehlung (a): Stufe 1 pinnt jedes Zertifikat, das die Plattform-CA-Prüfung nicht besteht. CA-gültige nimmt sie
     wie `xfreerdp3` und `mstsc` an.
   - Dazu eine Folgezeile (c): Upstream-Option in IronRDP, damit der Callback immer gefragt wird, und danach
     „Pin immer“. Sie gehört vor Stufe 2.
   - Trade-off: (b) erfüllt Bedingung 5 sofort, kostet aber gepatchten Fremdcode im Repo.
   - Stufe 1 baut (a) ohne Zusatzcode; (b) oder (c) kämen als eigene Task hinzu. Deshalb wartet keine Task auf die
     Antwort.
2. **CI-Job für den xrdp-Test** (Workflow-Änderung, Merge durch Kevin): Empfehlung als Folgezeile `neu`. Bis dahin
   läuft der Test im Sammellauf (`run.sh e2e`, GUI-Teil), dazu einmal vor dem Merge dieses Vorhabens (T6).

## Entscheidungen (Session, im Rahmen von R-1097)

- E1: TOFU über den IronRDP-Callback mit vorab gelesenem Pin; Identität `rdp/<workspace>/[<tunnel>/]<host>:<port>`
  der gespeicherten Verbindung, der Callback an den Endpoint der Sitzung gebunden. Erster
  Kontakt meldet `certificate` und pinnt erst über `rdp_trust_certificate`; `trust_cert` nimmt ohne Dialog an.
- E2: Feature `sound` bleibt in Stufe 1 aus. Die Roadmap-Zeile nennt es, aber CPAL braucht unter Linux
  `libasound2-dev` in `ci.yml` und `release.yml`, eine Workflow-Änderung. Der Bauplan (R-1074) legt Audio ohnehin in
  Stufe 3, mit dem Merge durch Kevin. `clipboard` und `rdpdr` sind gebaut, aber noch nicht eingeschaltet.
- E3: `openh264` bleibt aus. Unter Windows dekodiert Media Foundation (`ironrdp-egfx-native`, feste Abhängigkeit von
  `ironrdp-client` dort); unter Linux fällt GFX auf RemoteFX Progressive zurück (Bedingung 7).
- E4: Bulk-Kompression aus, GFX immer an (Bedingungen 1 und 9). Logon-Infos wie `LOGON_MSG_SESSION_CONTINUE` sind
  keine Fehler (Bedingung 11).
- E5: Lizenz-Gate als Rust-Test, der `cargo tree --locked --offline -e normal,build -i <paket>` im Manifest-Verzeichnis
  ruft. Bestanden heißt „kein Treffer“; `ring` muss gefunden werden (Gegenprobe). So läuft das Gate in `rust` und
  `rust-windows`, ohne Workflow-Änderung.
