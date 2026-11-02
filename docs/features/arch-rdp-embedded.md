<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Eingebettetes RDP: Machbarkeit

Architektur-Vorhaben `arch-rdp-embedded` (Roadmap R-1074; die Bau-Zeile R-1075 ist bis zur Entscheidung
zurückgestellt). Stand: `origin/main@b2edbbf8`, Zeilenangaben in T5 auf `origin/main@1c313156` nachgeprüft.

## Problem / Motivation

Der Desktop öffnet RDP heute in einem externen Client. Unter Linux sucht er `xfreerdp`
(`apps/desktop/src-tauri/src/connection/rdp.rs:200` `detect_rdp_binary`), baut die Argumente
(`rdp.rs:213` `build_rdp_args`, Zwischenablage fest an mit `+clipboard` `rdp.rs:277`), prüft Port und Anmeldung vorab
(`rdp.rs:583` `preflight_rdp`, `rdp.rs:605` `check_rdp_auth`) und reicht das Passwort über stdin weiter
(`rdp.rs:488` `spawn_rdp_with_password`). Unter Windows schreibt er eine `.rdp`-Datei für `mstsc`
(`rdp.rs:163` `open_rdp_windows`, `rdp.rs:774` `write_rdp_file`). Fehler meldet das Event `rdp-error`
(`rdp.rs:19` `emit_rdp_error`). Die Optionen (Skalierung, Fenster, Leistungsprofil) stehen in `RdpOptions`
(`apps/desktop/src-tauri/src/models.rs:57`, Enums ab `models.rs:27`). Die Sitzung läuft damit in einem fremden
Fenster: kein Tab, kein Abdocken, keine Statuszeile, und unter Linux muss FreeRDP installiert sein.

Das Mockup (`AdminCave/DesignSystem@244e890`, `ui_kits/adminhelper/rdp.jsx`) zeigt die Sitzung als Tab in
AdminHelper: Skalierung (Auto, 100 %, HiDPI), Fenster (eingepasst mit dynamischer Auflösung, Vollbild,
Multi-Monitor mit zwei Bildschirmen, feste Auflösung mit Zoom 25–200 %), Leistungsprofil, Schalter für
Zwischenablage, Laufwerke und Audio, Strg+Alt+Entf, Screenshot, Verbindungsinfo (Auflösung, Codec „AVC444“, fps,
Mbit/s, RTT), Neu verbinden, Abdocken, Tastatur-Fang („Strg+Alt+Pos1 gibt die Tastatur frei“) und die Phasen
verbinden/verbunden/getrennt. Ob das mit vertretbarem Aufwand und Risiko geht und mit welchem Stack, ist offen.
Kevin 2026-11-02: erst die Machbarkeit, als Architektur-Session.

## Ziel & Nicht-Ziele

**Ziel:** eine belegte Entscheidung, welche Variante R-1075 baut (oder dass keine trägt), dazu ein Bauplan für
R-1075 in dieser Spec: Stufen, Tasks, Abhängigkeiten, Heavy, Lizenzen, CSP und Capabilities, welche Mockup-Funktion
in welcher Stufe kommt und welche entfällt. Belegt heißt: Doku-Zitat mit Quelle oder Messung am Prototyp mit Version,
Kommando und Zahl; was weder das eine noch das andere hat, steht als „nicht verifiziert“ da.

**Nicht-Ziele:**
- Kein Produktcode: nichts unter `apps/`, keine neue Abhängigkeit in `Cargo.toml` oder `package.json`, keine UI.
- macOS (keine Zielplattform, `README.md:445`).
- Den OS-Client ablösen: er bleibt als Einstellung „RDP: OS-Client“ (R-1075).
- VNC, SPICE, RemoteApp, ein serverseitiges RDP-Gateway in AdminHelper.

## Betroffene Komponenten & Dateien

Dieses Vorhaben ändert nur diese Spec und sein Ledger `tasks/arch-rdp-embedded.md`. Bewertet wird für R-1075:
- Desktop-Backend: `connection/rdp.rs`, `connection/rdp_logic.rs`, `connection/mod.rs` (`open_connection` :77,
  Zweig `ConnectionKind::Rdp` :100, `open_rdp_with_stored_password` :247), `commands.rs` (`resolve_connection`
  :568), `tunnel.rs:76` (`resolve_connection`, der FRP-Weg zum Host), `models.rs` (`RdpOptions` :57,
  `RdpErrorPayload` :229; Wire-Vertrag, Risikopfad), `tauri.conf.json:16` (CSP), `capabilities/default.json`.
- Desktop-UI: `SettingsModal.svelte`, `ConnectionEditor.svelte`, `pages/Connections.svelte`,
  `infra/ServerConnectionModal.svelte`, `PasswordPrompt.svelte`, `lib/models/connection.ts`.
- Doku, die R-1075 nachziehen muss: `docs/developer/desktop.html` (EN dito), `README.md`,
  `THIRD_PARTY_LICENSES.md`.

### Prototypen

Prototyp-Code entsteht nicht im öffentlichen Baum: er ist Wegwerf-Code ohne eigene Prüfstufe, und ungetesteter Code
gehört nicht auf `main`. Während der Studie liegt er unter `<worktree>/.ah-out/arch-rdp-embedded/` (gitignored),
am Ende kommen Quellen und Rohdaten ohne Build-Verzeichnisse nach `tasks/private/spikes/arch-rdp-embedded/`. Diese
Spec nennt je Messung Versionen, Kommandos und Zahlen, damit das Ergebnis ohne das Archiv lesbar ist. Prototypen gibt
es nur für Varianten, die T1 nicht schon aus der Doku ausschließt.

## Varianten

| | Variante | Kern | Erste Einschätzung (vor T1) |
|---|---|---|---|
| V1 | IronRDP als WASM im Webview + lokaler Proxy in Rust | Die Web-Komponente `@devolutions/iron-remote-desktop` spricht per WebSocket mit einem lokalen RDCleanPath-Proxy im Tauri-Prozess, der TCP/TLS zum Host hält | Passwort und CredSSP liegen im Webview; die CSP braucht `wasm-unsafe-eval` und `ws://127.0.0.1:*`; Bau der Komponente verlangt Node 24 (Dev-Box: Node 22) |
| V2 | IronRDP nativ in Rust, Bild über IPC | Verbindung, CredSSP, Kanäle und Dekodierung im Tauri-Prozess; geänderte Rechtecke gehen roh über einen Tauri-Channel (oder einen lokalen WS) an ein Canvas, Eingaben zurück | Passwort bleibt in Rust wie heute; native Kanäle (Zwischenablage, Laufwerke, Audio); offen ist der Durchsatz der IPC-Strecke |
| V2b | Netz in Rust, Dekodierung als WASM im Webview | wie V2, aber die Bitmap-Dekodierung läuft im Webview | nur als Rückfall, falls V2 an der IPC-Bandbreite scheitert |
| V3a | libfreerdp3 per FFI | FreeRDP als Bibliothek, Bild wie V2 | H.264/AVC und RD-Gateway vorhanden; C-Abhängigkeit, Paketierung unter Windows, Patentfrage H.264 |
| V3b | externer Client als Kindfenster | xfreerdp `/parent-window`, mstsc als ActiveX | voraussichtlich auszuschließen: nur X11, nicht Wayland; das Fenster liegt über allen DOM-Overlays |
| V3c | Apache Guacamole | guacd übersetzt RDP | nur Linux, eigener Dienst; voraussichtlich auszuschließen |

Der heutige Weg (externer Client) bleibt in jeder Variante als Einstellung bestehen.

## Kriterien

| | Kriterium | Wie belegt |
|---|---|---|
| K1 | Grafik: Codecs (Planar, Interleaved, RemoteFX, RFX Progressive, ClearCodec, AVC420/444), fps, Bandbreite, CPU | Doku; Messung T2 (xrdp), T4 (Windows) |
| K2 | Dynamische Auflösung (MS-RDPEDISP) und Skalierung | Doku; Resize am Prototyp |
| K3 | NLA/CredSSP, Zertifikatsprüfung (heute `trust_cert`), wo das Passwort liegt | Doku; Anmeldung T4 |
| K4 | Zwischenablage (MS-RDPECLIP), Text und Dateien | Doku; Prototyp |
| K5 | Laufwerke (MS-RDPEFS) | Doku; Prototyp soweit der Host es anbietet |
| K6 | Audio (MS-RDPEA) | Doku; Prototyp |
| K7 | Multi-Monitor (Monitor-Layout in MS-RDPBCGR/-RDPEDISP) | Doku; Aushandlung am Prototyp |
| K8 | RD-Gateway (MS-TSGU) | Doku; ohne Gateway im Pool „nicht verifiziert“ |
| K9 | Eingabe: Scancodes, Strg+Alt+Entf, Tastatur-Fang im Webview, Unicode | Doku; T3 (Webview), T2/T4 |
| K10 | Tunnel: Verbindung über den FRP-Weg (`tunnel.rs:76`) statt direkt | Code-Lesen; Prototyp gegen einen lokalen Port |
| K11 | Lizenz und Patente (GPL-3.0-or-later der App, H.264) | Lizenztexte der Abhängigkeiten |
| K12 | Plattform und Bau: Linux WebKitGTK, Windows WebView2, Toolchain, Bundle-Größe | T3; Windows-Seite nach T4-Antwort |
| K13 | Sicherheit: lokaler Port und sein Schutz, Angriffsfläche des Dekoders, CSP | Design-Bewertung; `security`-Blick im Bauplan |
| K14 | Pflege: Releases, Aktivität, API-Stabilität der Abhängigkeit | Repo-Historie |
| K15 | Abdocken (R-1070) und Terminal-Muster (R-1069) | Abgleich mit deren Plänen |

## Vorgehen

- **T1 — Kriterienmatrix aus der Doku.** Jede Variante gegen K1–K15 aus offiziellen Quellen (Repos, Crate-Doku,
  MS-Spezifikationen, Tauri-Doku); harte Ausschlüsse begründen; festlegen, welche Varianten einen Prototyp bekommen.
- **T2 — Protokoll-Prototyp gegen xrdp.** xrdp im Docker-Container auf der Dev-Box (Image aus Debian-Paketen, nur
  Loopback). Ein kopfloser Probe-Client in Rust auf IronRDP verbindet sich, dekodiert und misst Codec, fps, Mbit/s,
  Dekodierzeit und CPU unter einer festen Bildlast; dazu Resize (Display Control), Zwischenablage und, soweit xrdp sie
  anbietet, Laufwerk und Audio. Gegenmessung mit FreeRDP 3 unter Xvfb im Container. Build-Verzeichnis unter
  `.ah-out/`, vorher `df -h /`.
- **T3 — Bildweg im Webview.** Eine Wegwerf-Tauri-2-App auf der Desktop-VM der Lane (Xvfb) schiebt synthetische
  Rechteck-Last (1920×1080, 10/50/100 % Fläche, 30/60 Hz) über einen Tauri-Channel (rohe Bytes) und über einen lokalen
  WebSocket auf ein Canvas (`putImageData` gegen WebGL `texSubImage2D`) und misst Durchsatz, Latenz und CPU; dazu
  Tastatur-Fang im Webview. Falls V1 nach T1 im Rennen ist, dieselbe Last mit der WASM-Komponente. Software-Rendering
  unter Xvfb ergibt eine untere Schranke, keine Aussage über eine GPU.
- **T4 — Windows-Probe.** Derselbe Probe-Client gegen einen echten Windows-Host: NLA/CredSSP, Codec-Aushandlung
  (mit und ohne AVC), Resize, Zwischenablage, Audio, Laufwerke, Monitor-Layout. Host: ein GitHub-Windows-Runner über
  einen Wegwerf-Branch (Kevin 2026-11-02, Offene Fragen 1).
- **T5 — Entscheidung und Bauplan.** Ergebnis in dieser Spec (Abschnitt „Ergebnis“): gewählte Variante mit
  Begründung und Restrisiken, Bauplan für R-1075, Archiv nach `tasks/private/spikes/`, R-1075 mit Notiz zurück auf
  `neu` zur Triage, Folgezeilen als `neu`.

**Abbruchkriterium:** Die Studie ist fertig, wenn jedes Kriterium je Variante belegt, ausgeschlossen oder begründet
„nicht verifiziert“ ist. Ein Prototyp-Schritt, der nach zwei Anläufen nicht läuft, wird als Befund festgehalten
(nach einmal `advisor`), nicht weiter erzwungen.

## Ergebnis: Matrix

Stand 2026-11-02, nur aus Quellen (Liste unten, `[Qn]`); „n. v.“ heißt nicht verifiziert, „T2“ bis „T4“ heißt, der
Prototyp misst es. Die Haupttabelle führt die drei Varianten, die nach der Doku tragen könnten; V2b, V3b und V3c
stehen in der zweiten Tabelle.

| | V1 IronRDP-WASM im Webview | V2 IronRDP nativ in Rust | V3a libfreerdp3 per FFI |
|---|---|---|---|
| K1 Grafik | Web-Komponente ohne EGFX, also ohne Progressive, ClearCodec und AVC; Ausgabe Canvas2D `putImageData` [Q7] | Raw, Interleaved RLE, RDP 6 (Planar), RemoteFX; EGFX mit ClearCodec, Progressive, AVC420/AVC444 [Q1][Q2]. AVC-Dekoder: Windows Media Foundation, nichts zu bündeln [Q3]; Linux nur OpenH264 (`openh264-libloading`: das Cisco-Binary lädt der Nutzer; `openh264-bundled` baut aus Quellen ohne Patentdeckung) [Q2], und `ironrdp-client` nimmt außerhalb von Windows im Default die aus Quellen gebaute Fassung [Q4]; ohne Dekoder ist EGFX im Default aus und lässt sich nur ohne AVC einschalten [Q4]. fps, Mbit/s, CPU: T2, T4 | `/gfx` mit RFX, Progressive, AVC420, AVC444; H.264 über FFmpeg oder Media Foundation [Q9]; Gegenmessung mit der FreeRDP-CLI in T2 |
| K2 Auflösung | Display Control vorhanden [Q7] | `RdpInputEvent::Resize` über MS-RDPEDISP, Rückfall Neuverbindung (`DisplayResizeFallbackReason`) [Q4]; T2, T4 | `/dynamic-resolution` [Q9] |
| K3 Anmeldung | CredSSP im WASM-Modul, das Passwort liegt im Webview; RDCleanPath prüft das Server-Zertifikat nicht [Q4][Q7] | CredSSP mit NTLM und Kerberos im Rust-Prozess [Q1], Passwort bleibt dort wie heute (`rdp.rs:488`). TLS-Prüfung ist im Default aus (`DangerouslyAcceptInvalidCertificate`), `Strict` und ein Prüf-Callback gibt es nur mit rustls [Q5]: den Dialog „Zertifikat vertrauen“ (heute `trust_cert` → `/cert:ignore`, `rdp.rs:253`) baut R-1075 selbst. NLA am Host: T4 | FreeRDP-eigene NLA und Zertifikatsprüfung wie heute [Q14], aber im App-Prozess |
| K4 Zwischenablage | vorhanden [Q7]; Bilder, Dateien n. v. | `cliprdr-native`: Linux X11 und Wayland (Text, Bilder), Windows auch Dateien (opt-in) [Q6]; T2, T4 | `/clipboard` [Q9], heute `+clipboard` (`rdp.rs:277`) |
| K5 Laufwerke | fehlt: RDPDR nur Drucker [Q7] | `rdpdr-native`: Dateisystem Linux (`openat2`, sichere Pfadauflösung) und Windows [Q6]; T2 soweit xrdp es anbietet, T4 | `/drive` [Q9] |
| K6 Audio | fehlt: `NoopRdpsndBackend` [Q7] | `rdpsnd-native` über CPAL: PCM, G.711, ADPCM, Opus (Feature), AAC unter Windows [Q6]; T2, T4 | `/sound` [Q9] |
| K7 Multi-Monitor | n. v. | `with_monitor_layout`, `RdpInputEvent::MonitorLayout` (MS-RDPEDISP, Rückfall auf die GCC Client Monitor Data) [Q4]; T4. Zwei Bildschirme in AdminHelper heißt zwei Fenster: das hängt an R-1070 | `/multimon`, `/monitors` [Q9] |
| K8 RD-Gateway | n. v. | `ironrdp-mstsgu` 0.1.0 [Q8]; `ironrdp-client` mit Feature `gateway`: MS-TSGU über HTTPS-WebSocket, Rückfall HTTP und RPCH, kein UDP/DTLS; laut README gegen ein echtes RD Gateway getestet [Q4]. Ohne Gateway im Pool n. v. | `/gateway` [Q9]; n. v. |
| K9 Eingabe | in der Web-Komponente; Tastatur-Fang im Webview: T3 | `ironrdp-input`: Scancodes und Unicode (`UnicodeKeyPressed`) [Q1]; welche Systemkürzel (Alt+Tab, Super) der Webview gar nicht sieht: T3; Strg+Alt+Entf als Scancode-Folge: T4 | Eingabe kommt wie bei V2 aus dem Webview: dieselbe Grenze, T3 |
| K10 Tunnel | der lokale Proxy verbindet zu dem Ziel, das `tunnel.rs:76` liefert [Q14] | Verbindung zu beliebigem Host und Port im Prozess; `tunnel.rs:76` liefert den FRP-Weg [Q14]; T2 verbindet gegen einen lokalen Port | `/v:<host>:<port>` wie heute [Q14] |
| K11 Lizenz, Patente | MIT OR Apache-2.0 [Q1][Q7], mit GPL-3.0 verträglich [Q15] | wie V1 [Q1][Q15]; H.264 wie K1 (Windows systemseitig, Linux Cisco-Binary vom Nutzer) [Q2][Q3]. Für alle Varianten mit eigener Implementierung: Microsofts Open Specifications Promise nennt keine RDP-Spezifikation, MS-RDPEDISP verweist auf mögliche Patente [Q12]. AdminHelper verteilte damit erstmals selbst eine RDP-Implementierung: Restrisiko für Kevin (T5) | Apache-2.0 [Q9][Q15]; FFmpeg-Lizenz je Bau und H.264-Patente n. v.; RDP-Patente wie V2 [Q12] |
| K12 Plattform, Bau | WASM-Bau, die Web-Komponente braucht Node 24 [Q1]; CSP bräuchte `wasm-unsafe-eval` und `ws://127.0.0.1:*` (heute nicht, `tauri.conf.json:16`) [Q14]; WebKitGTK und WebView2: T3 | reines Rust, edition 2024 [Q1]; CSP bleibt [Q14]; Bild über einen Tauri-Channel: rohe Nachrichten ab 1024 Byte holt der Webview je Nachricht per `plugin:__TAURI_CHANNEL__\|fetch` [Q11], ein volles Bild 1920×1080×4 Byte sind 8,3 MB: T3 misst, ob das trägt; Linux-Bauabhängigkeiten (ALSA für CPAL, Wayland für cliprdr) n. v. | C-Bibliothek plus FFmpeg, unter Windows selbst bauen und bündeln (n. v.); Rust-Bindings gibt es nur als `freerdp-sys` 0.1.0 (24 Downloads in 90 Tagen) und `freerdp2` für FreeRDP 2 (2022) [Q16]: eigene Bindings |
| K13 Sicherheit | Anmeldedaten und Protokoll im Webview: eine Skript-Lücke im Webview erreicht sie; lokaler WS-Port braucht Token und Origin-Prüfung; keine Zertifikatsprüfung [Q4][Q7] | Parser und Dekoder in Rust im App-Prozess; 0 veröffentlichte Security Advisories im Repo, eigene Fuzzing-Crate [Q1]; Default ohne Zertifikatsprüfung [Q5] muss R-1075 umstellen; ein Channel braucht keinen Port, ein lokaler WS bräuchte Token | C-Dekoder im App-Prozess statt in einem Kindprozess wie heute: 243 veröffentlichte Security Advisories seit 2026-01-01, davon 2 critical und 58 high [Q9]; ein Speicherfehler träfe den ganzen AdminHelper-Prozess |
| K14 Pflege | npm `@devolutions/iron-remote-desktop` 0.11.0 und `-rdp` 0.7.0, zuletzt 2026-05-27; die Rust-Seite `ironrdp-web` wird nicht veröffentlicht [Q7] | sehr aktiv (über 100 Commits seit 2026-08-01), Low-Level-Crates frisch auf crates.io (`ironrdp-connector` 0.12.0, `ironrdp-egfx` 0.5.0, beide 2026-10-27), 0.x mit häufigen Breaking-Bumps [Q1]; `ironrdp-client` mit Event-API nur auf `main`, crates.io 0.1.0 (2026-07-10) ohne EGFX [Q4]: R-1075 hängt an einer Git-Revision oder baut die Schicht selbst über die Low-Level-Crates | FreeRDP 3.33.0 vom 2026-11-02, aktiv [Q9]; Bindings in eigener Pflege [Q16] |
| K15 Abdocken, Terminal | die Sitzung lebt im Webview: Abdocken in ein anderes Fenster heißt neu verbinden, R-1070 verlangt, dass die Sitzung im Backend weiterlebt | Sitzung im Backend, Bild über einen Channel wie R-1069 (PTY → Channel); Wiederanhängen über ein Vollbild (`RdpOutputEvent::Image`) [Q4] | wie V2 (Sitzung im Backend) |

| | V2b Netz in Rust, Dekodierung als WASM | V3b externer Client als Kindfenster | V3c Apache Guacamole |
|---|---|---|---|
| K1 | wie V2; ein WASM-Dekoder-Baustein für EGFX nennt keine Quelle: n. v. | wie der Client [Q9] | FreeRDP darunter [Q13], Bild als Guacamole-Protokoll: n. v. |
| K2 | wie V2 | `/dynamic-resolution` [Q9] | n. v. |
| K3 | wie V2 | wie heute (`rdp.rs:488`) [Q14] | das Passwort geht an einen weiteren Dienst (guacd): n. v. |
| K4–K8 | wie V2 | wie der Client [Q9] | n. v. |
| K9 | wie V2 | Tastatur im fremden Fenster (`/grab-keyboard`) [Q9]; Zusammenspiel mit dem Webview n. v. | n. v. |
| K10 | wie V2 | wie heute [Q14] | guacd muss das Ziel erreichen: n. v. |
| K11 | wie V2 | heutiger Stand, keine neue Verteilung | Apache-2.0 (ASF), FreeRDP Apache-2.0 [Q9][Q15] |
| K12 | WASM-Bau und CSP wie V1 | `/parent-window` nur in `client/X11` und `client/Windows`, nicht Wayland [Q9]; mstsc als ActiveX-Steuerelement braucht einen ActiveX-Host, Tauri hat keinen (n. v.) | das Handbuch nennt keinen Windows-Bau [Q13]: n. v. |
| K13 | wie V2, dazu ein Dekoder im Webview | wie heute (eigener Prozess) | zusätzlicher Dienst mit eigenem Port |
| K14 | wie V1 und V2 zusammen | heutiger Stand | Guacamole 1.6.0 [Q13] |
| K15 | Referenzbilder des Dekoders liegen im Webview: Wiederanhängen nach dem Abdocken braucht ein Vollbild, n. v. | Abdocken heißt, das Kindfenster umzuhängen: n. v. | n. v. |

**Harte Ausschlüsse:**
- **V3b:** `/parent-window` gibt es nur im X11- und im Windows-Client [Q9], unter Wayland trägt es nicht; ein natives
  Kindfenster liegt über jedem DOM-Overlay (Dialoge, Menüs, Toasts) und muss beim Abdocken umgehängt werden. Damit
  ist es kein Tab im Sinne des Mockups, nur ein anders platziertes externes Fenster.
- **V3c:** Unter Guacamole läuft ohnehin FreeRDP [Q13]; was V3c kann, kann V3a direkt, ohne zusätzlichen Dienst und
  ohne den Umweg über das Guacamole-Protokoll. Ein Windows-Betrieb ist nicht belegt [Q13].

**Ohne Prototyp, mit Grund:**
- **V1** fällt gegen das Mockup bei zwei Schaltern aus (Audio, Laufwerke [Q7]), hat kein AVC, legt Passwort und
  Protokoll in den Webview, prüft das Zertifikat nicht und verliert die Sitzung beim Abdocken (K15). Ihr einziger
  Vorteil, die Dekodierung im Webview, steckt auch in V2b, ohne die Anmeldedaten dorthin zu legen.
- **V2b** bekommt nur dann einen Prototyp, wenn T3 zeigt, dass der rohe Bildweg von V2 nicht trägt.
- **V3a** bleibt Rückfall, falls V2 in T2 oder T4 an Protokoll oder Stabilität scheitert. Eigene FFI-Bindings wären
  der größte Posten des Prototyps; T2 misst stattdessen die FreeRDP-CLI als Referenz für Codec und Bandbreite.

**Prototypen:**
- **T2:** V2-Probe auf `ironrdp-client` (Git-Revision `37ce7d1b` von `main`, wegen der Event-API [Q4]) gegen xrdp,
  mit und ohne EGFX; dazu die FreeRDP-3-CLI als Referenz.
- **T3:** V2-Bildweg: Tauri-Channel mit rohen Bytes gegen lokalen WebSocket, Canvas2D gegen WebGL. Schwelle, vorab
  festgelegt: der Weg trägt, wenn 1920×1080 bei 50 % geänderter Fläche und 30 Hz ohne wachsenden Rückstau läuft
  und die Zeit vom Senden in Rust bis zum gezeichneten Bild im 95. Perzentil unter 33 ms bleibt (ein Bild bei
  30 Hz); 100 % und 60 Hz werden mitgemessen, entscheiden aber nicht. Unter Xvfb ohne GPU ist das eine untere
  Schranke.
- **T4:** dieselbe V2-Probe gegen den Windows-Runner, dort mit dem Media-Foundation-Dekoder [Q3], also mit AVC.

**Quellen** (abgerufen 2026-11-02):
- [Q1] IronRDP, <https://github.com/Devolutions/IronRDP> @`37ce7d1b` (2026-11-01): README, `Cargo.toml:21`
  (`license = "MIT OR Apache-2.0"`), Crates unter `crates/` (u. a. `ironrdp-input`, `ironrdp-fuzzing`), Commit-Historie;
  Versionen von crates.io.
- [Q2] `ironrdp-egfx` 0.5.0 (crates.io, 2026-10-27): README „H.264/AVC420 and AVC444 video streaming support“,
  Features `openh264`, `openh264-bundled`, `openh264-libloading` (`Cargo.toml:32–34`).
- [Q3] `ironrdp-egfx-native` 0.2.0 (2026-10-28): Windows `MediaFoundationH264Decoder`; README: „Other platforms
  currently have no native decoder.“
- [Q4] `crates/ironrdp-client` auf `main`: README (mit H.264-Dekoder EGFX-Capabilities 10.7 bis 10, 8.1 und 8, ohne
  Dekoder EGFX aus; Feature `gateway`; „RDCleanPath … does not validate the RDP server's TLS certificate“; „TLS
  peer-certificate validation remains disabled by default“), `src/rdp.rs` (`DisplayResizeFallbackReason` :108,
  `RdpOutputEvent::DesktopUpdate` :167, `RdpInputEvent::Resize` :626, `MonitorLayout` :639); crates.io: 0.1.0
  (2026-07-10) ohne EGFX-, H.264- und Video-Features.
- [Q5] `crates/ironrdp-tls/src/lib.rs:63`: `DangerouslyAcceptInvalidCertificate` ist der Default.
- [Q6] READMEs `ironrdp-cliprdr-native` 0.9.0, `ironrdp-rdpsnd-native` 0.8.0, `ironrdp-rdpdr-native` 0.9.0.
- [Q7] `crates/ironrdp-web` (`publish = false`; Audio `NoopRdpsndBackend` in `src/session.rs`, RDPDR nur Drucker,
  kein EGFX, Canvas2D) und npm `@devolutions/iron-remote-desktop` 0.11.0, `@devolutions/iron-remote-desktop-rdp`
  0.7.0.
- [Q8] `ironrdp-mstsgu` 0.1.0 (crates.io, 2026-10-27).
- [Q9] FreeRDP, <https://github.com/FreeRDP/FreeRDP>: Lizenz Apache-2.0, Release 3.33.0 (2026-11-02);
  `client/common/cmdline.h` @3.33.0 (`/clipboard` :131, `/drive` :154, `/dynamic-resolution` :164, `/gateway` :194,
  `/gfx` :214, `/grab-keyboard` :247, `/monitors` :344, `/multimon` :359, `/parent-window` :394, `/sound` :484);
  `/parent-window` ausgewertet nur in `client/X11` und `client/Windows`; H.264 über FFmpeg oder Media Foundation;
  GitHub Security Advisories des Repos (API-Abfrage).
- [Q10] xrdp 0.10.1-3.1+deb13u2 (Debian 13), Paketabhängigkeiten ohne `libx264` (Codec-Angebot belegt T2).
- [Q11] Tauri 2, <https://v2.tauri.app/develop/calling-frontend/>: Channels „are designed to be fast and deliver
  ordered data“, das Event-System „is not designed for low latency or high throughput situations“; `tauri` 2.11.5
  (Version im Lockfile), `src/ipc/channel.rs:39` (`MAX_RAW_DIRECT_EXECUTE_THRESHOLD` = 1024).
- [Q12] Microsoft Open Specifications Promise (Liste der erfassten Spezifikationen ohne MS-RDP*); MS-RDPEDISP
  Rev. 10.0 (2024-04-23), Hinweis zu geistigem Eigentum: „Microsoft has patents that might cover your
  implementations“.
- [Q13] Apache Guacamole Manual v1.6.0, „Installing Guacamole natively“: „FreeRDP 2.0.0 or later is required for RDP
  support.“
- [Q14] AdminHelper `origin/main`: `apps/desktop/src-tauri/src/connection/rdp.rs`, `tauri.conf.json:16`,
  `src/tunnel.rs:76`.
- [Q15] FSF, <https://www.gnu.org/licenses/license-list.html>: Apache-2.0 „compatible with version 3 of the GNU GPL“,
  Expat „compatible with the GNU GPL“.
- [Q16] crates.io-Suche „freerdp“: `freerdp-sys` 0.1.0 (2026-07-24), `freerdp2` und `freerdp2-sys` 0.2.0
  (2022-11-02, FreeRDP 2).
- [Q17] IronRDP-Issue #447 „Devilish resize bug“ (offen seit 2024-04-24): nach einem Resize über Display Control
  sinkt der Bildtakt auf dem RemoteFX-Pfad, FreeRDP ist nicht betroffen; dazu `FIXME(#447)` in
  `crates/ironrdp-connector/src/connection_activation.rs:685` @`37ce7d1b`.
- [Q18] @`37ce7d1b`: `crates/ironrdp-tls/Cargo.toml` `rustls = ["rustls-aws-lc-rs"]`, `rustls-ring` getrennt
  wählbar; `crates/ironrdp-client/Cargo.toml` `rustls = ["ironrdp-tls/rustls", …]` und
  `udp = [… "ironrdp-rdpeudp-tokio/rustls-aws-lc-rs"]`.

## Ergebnis: xrdp

Stand 2026-11-02 (T2). **Aufbau:**
- **Server:** xrdp 0.10.1 mit xorgxrdp 0.10.2 (Debian 13) in einem Docker-Container auf der Dev-Box (8 Kerne). Der
  Port liegt nur auf Loopback, angemeldet wird ein Wegwerf-Benutzer mit Zufallspasswort.
- **Bildlast:** ffplay spielt im Container ein Testvideo auf 10 %, 50 % oder 100 % von 1920×1080 („tenth“, „half“,
  „full“); bei „idle“ bewegt sich nichts.
- **Clients:** V2-Probe, also `ironrdp-client` auf Git-Revision `37ce7d1b`, kopflos; sie zählt dekodierte
  Bildänderungen und ihre CPU-Zeit. Ein lokaler Patch fügt nur eine trace-Zeile für den Codec hinzu. Als Referenz
  läuft FreeRDP 3.15 (`xfreerdp3`) unter Xvfb.
- **Messung:** 20 s nach 12 s Anlauf, jeder Lauf mit einem frischen Container. Gemessen werden die gesendeten Bytes
  des Containers und die CPU je Prozess aus `/proc`, für beide Clients gleich.
- **Unschärfe:** Die Host-Last lag zeitweise bei 11–15. Die Zahlen sind deshalb Größenordnungen, keine Benchmarks.

**Bandbreite und Client-CPU** (Mbit/s vom Server / % eines Kerns; FreeRDP ohne die 2–7 % für Xvfb):

| Last | IronRDP, GFX an | IronRDP, GFX aus | FreeRDP, Default (GFX) | FreeRDP, GFX aus (`/network:lan +rfx`) |
|---|---|---|---|---|
| idle | 0 / < 1 % | 0 / < 1 % | 0 / < 1 % | 0 / < 1 % |
| tenth | 5,6 / 26 % | 7,2 / 13 % | 6,1 / 23 % | 7,2 / 19 % |
| half | 16,5 / 59 % | 17,0 / 31 % | 15,8 / 57 % | 18,2 / 36 % |
| full | 19,3 / 65 % | 16,8 / 37 % | 18,1 / 71 % | 19,5 / 44 % |

**Befunde:**
- **Codec.** Mit GFX handelt xrdp für die Sitzung RemoteFX Progressive aus (nur `WireToSurface2`, unter Last 19–24
  EGFX-Frames/s), den Anmeldebildschirm überträgt es planar. Ohne GFX kommt klassisches RemoteFX als Fast-Path-Update,
  bulk-komprimiert. Diese xrdp-Fassung hat keinen H.264-Encoder [Q10]: den AVC-Pfad von IronRDP misst erst T4. Ohne
  H.264-Dekoder (`--avc off`) bleibt die Sitzung auf Progressive, half 14,5 Mbit/s, die Probe bei 51 %.
- **Leistung.** Bei der Bandbreite liegen IronRDP und FreeRDP gleichauf. Bei der CPU gilt: mit GFX gleichauf, ohne
  GFX braucht die Probe weniger, zeichnet aber auch nicht, FreeRDP schreibt zusätzlich in Xvfb. Progressive kostet
  den Client etwa das Doppelte von klassischem RemoteFX. 1080p bei 50–100 % bewegter Fläche dekodiert die Probe mit
  rund 0,6 Kernen. Die Pixel-Zählung der Probe ist mit GFX nicht mit der ohne GFX vergleichbar; maßgeblich sind
  dort die EGFX-Frames/s.
- **Anlauf.** Die Verbindung steht nach 0,2–0,4 s. Das erste Bild kommt mit GFX nach 0,4–0,7 s, ohne GFX nach
  1,5–1,9 s.
- **Stillstand.** In einem von acht GFX-Läufen unter Last blieb das Bild nach dem ersten Frame stehen: der Server
  sendete danach nichts mehr (0,01 Mbit/s), die Probe meldete keinen Fehler. Die Ursache ist nicht verifiziert
  (Kandidat: die Frame-Bestätigung, MS-RDPEGFX `FrameAcknowledge`). R-1075 braucht einen Watchdog, der eine stehende
  Sitzung erkennt und neu aufbaut.
- **Resize und Monitor-Layout.** Im Default scheitern beide immer, mit und ohne GFX. Die Probe kündigt per Default
  Bulk-Kompression an (MPPC 64K, `INFO_COMPRESSION`). xrdp schickt daraufhin in der Reaktivierung nach dem Resize die
  Font-Map-PDU komprimiert. Die `connection_finalization` von `ironrdp-connector` dekomprimiert nicht (das tut nur
  `ironrdp-session` im laufenden Betrieb) und bricht mit „unexpected server message“ ab. Ohne GFX meldete xrdp dabei
  zusätzlich einen SIGSEGV seines Sitzungsprozesses. Gegenprobe mit abgeschalteter Bulk-Kompression
  (`ConfigBuilder::with_compression(false)`):
  - Resize 1920×1080 → 1280×720 fertig nach 299 ms (GFX an) bzw. 135 ms (GFX aus), ohne Neuverbindung und ohne
    SIGSEGV;
  - das Zwei-Monitor-Layout (2× 1280×720) kommt als `MonitorLayout` mit 2560×720 an;
  - die Bandbreite ohne Bulk-Kompression: half, GFX an, 12,6 Mbit/s bei 18 EGFX-Frames/s, also je Frame so viel wie
    im Default (0,69 Mbit). Die Host-Last lag dabei bei 14–17.

  Das ist ein Fehler in IronRDP, kein Grund gegen V2: R-1075 schaltet die Bulk-Kompression ab, bis er upstream behoben
  ist, und meldet ihn dort (Folgezeile).
- **Kanäle.**
  - Zwischenablage: Fähigkeiten und Formatliste werden ausgetauscht; mit der nativen Zwischenablage (`enable`) bricht
    die kopflose Probe unter Linux nicht ab, Inhalte prüft erst T4.
  - Audio: RDPSND handelt aus, die Probe wählt 2 von 3 angebotenen Formaten. Ob Ton ankommt, misst erst T4.
  - Laufwerk: RDPDR meldet das Laufwerk an (`ServerDeviceAnnounceResponse` mit `STATUS_SUCCESS`). xrdp hängt es per
    FUSE unter `thinclient_drives` ein, und das geht im Container nicht: der Ordner blieb leer, Lesen und Schreiben
    prüft erst T4.
- **Nicht gemessen:**
  - H.264 und NLA: xrdp bietet beides nicht, also T4.
  - FreeRDP mit Ton, Zwischenablage und Resize.
  - Die reine Dekodierzeit je Frame: die CPU-Zeit des Prozesses ist eine Näherung.

## Ergebnis: Webview

Stand 2026-11-02 (T3). **Aufbau:**
- **Umgebung:** die Desktop-VM der Lane, 6 vCPU und 6 GB RAM, Ubuntu 24.04 mit WebKitGTK 2.52.6 und Mesa 25.2.8.
  Sie hat keine GPU. Xvfb läuft mit 1920×1080×24 ohne Fenstermanager, WebGL rendert also in Software (WebKit meldet
  den Renderer maskiert).
- **App:** eine Wegwerf-Tauri-App auf `tauri` 2.11.5 wie der Desktop, Fenster 1920×1080 ohne Rahmen. Rust erzeugt
  je Takt ein RGBA-Rechteck über die volle Breite und 10, 50 oder 100 % der Höhe, mit einem 32-Byte-Kopf aus
  Nummer und Sendezeit. Zwei Wege bringen es zum Webview:
  - roh über einen Tauri-Channel (`InvokeResponseBody::Raw`);
  - über einen lokalen WebSocket (`tokio-tungstenite` auf 127.0.0.1, Token in der URL).

  Der Webview zeichnet mit Canvas2D `putImageData` oder mit WebGL `texSubImage2D`.
- **Datenrate:** Der Bildweg trägt dekodierte Pixel, also ein Vielfaches der RDP-Bandbreite aus T2. Bei 10 % und
  30 Hz sind es 25 MB/s, bei 50 % 125 MB/s, bei 100 % 250 MB/s; bei 60 Hz das Doppelte. Zum Vergleich: half aus T2
  mit 24 Bildern/s wären rund 100 MB/s.
- **Messung:** je Fall 10 s, mit derselben Wanduhr in Rust und im Webview.
  - Ankunft: vom Senden in Rust bis zur Ankunft im Webview.
  - Bild: bis zum ersten `requestAnimationFrame` nach dem Zeichnen; daran hängt die Schwelle.
  - Rückstau: Anstieg der Ankunftszeit vom ersten zum letzten Viertel des Laufs; er „wächst“, wenn der Anstieg
    über einer Taktlänge liegt.
  - CPU je Prozess aus `/proc`.
- **Tastatur:** Nach der Matrix sendet `xdotool` 24 Tastenkombinationen an das Fenster. Der Webview hört `keydown`
  in der Capture-Phase und ruft `preventDefault`.

**Bildweg** (Ankunft p50/p95 · Bild p50/p95 in ms · Bilder/s im Webview · Rückstau; „Stau“ heißt: der Rückstau
wächst um Sekunden):

| Weg, Zeichnen | 10 %, 30 Hz | 10 %, 60 Hz | 50 %, 30 Hz | 50 %, 60 Hz | 100 %, 30 Hz | 100 %, 60 Hz |
|---|---|---|---|---|---|---|
| Channel, 2d | 47/100 · 79/148 · 17 · stabil | 65/122 · 106/178 · 13 · stabil | Stau | übersprungen | übersprungen | übersprungen |
| Channel, WebGL | 52/115 · 90/177 · 15 · stabil | 355/475 · 411/548 · 10 · wächst | Stau | übersprungen | übersprungen | übersprungen |
| WS, 2d | 11/22 · 33/59 · 23 · stabil | 12/30 · 40/71 · 23 · stabil | 48/109 · 75/158 · 18 · stabil | 143/354 · 175/391 · 15 · wächst leicht | 121/380 · 144/420 · 15 · wächst leicht | Stau, 128 von 600 Bildern nicht zugestellt |
| WS, WebGL | verfälscht (s. u.) | 247/852 · 297/897 · 12 · wächst | 39/96 · 79/171 · 15 · stabil | Stau | 147/269 · 196/337 · 11 · stabil | übersprungen |

„Übersprungen“ heißt: dieselbe Kombination hatte bei kleinerer Last schon gestaut. In allen anderen Fällen kam jedes
Bild in Reihenfolge an. Die CPU des `WebKitWebProcess` lag in jedem Fall bei 1,8–4,1 Kernen, Xvfb bei bis zu 0,8 Kernen.

**Befunde:**
- **Schwelle verfehlt.** Kein Fall bleibt bis zum Bild unter p95 33 ms, auch nicht bei 10 %.
- **Engpass ist das Zeichnen ohne GPU, nicht der Transport.** Über den WebSocket kommt ein 10-%-Bild nach p95 22 ms
  an. Die Bildschleife des Webviews läuft unter Last aber nur mit 10–23 Bildern/s, und der `WebKitWebProcess`
  belegt schon bei 10 % rund drei der sechs Kerne. `putImageData` selbst kostet 1–12 ms (p50), `texSubImage2D`
  10–16 ms.
- **Der Channel taugt nicht.** Er ist schon bei 10 % langsamer als der WebSocket (Ankunft p95 bei 30 Hz 100–115 ms gegen
  22 ms) und staut ab 50 %/30 Hz; der Rust-Teil braucht dabei 1,3 Kerne, beim WebSocket 0,4. Ohne Gegendruck puffert
  er unbegrenzt: der erste Lauf endete im OOM der VM. Rohe Nachrichten ab 1024 Byte holt der Webview je Nachricht
  mit einem eigenen IPC-Abruf [Q11].
- **Der WebSocket trägt** 50 %/30 Hz mit beiden Zeichenwegen und 100 %/30 Hz mit WebGL ohne wachsenden Rückstau.
  Bei 60 Hz staut er ab 50 % (WebGL) bzw. 100 % (2d). Unter Xvfb ohne GPU ist das eine untere Schranke.
- **Verfälscht:** WebGL 10 %/30 Hz über den WebSocket. Reste des gestauten Vorlaufs (2d, 100 %/60 Hz) kamen in
  diesem Lauf an: 402 Bilder empfangen bei 300 gesendeten. Auch WebGL 10 %/60 Hz liegt schlechter als 50 %/30 Hz;
  die Ursache ist nicht verifiziert.
- **Folgerung für V2:**
  - Das Bild läuft über einen lokalen WebSocket statt über einen Channel.
  - Gegendruck: Rust hält das aktuelle Bild und schickt die geänderten Bereiche erst, wenn der Webview das vorige
    Bild quittiert hat. Bereiche, die sich inzwischen geändert haben, fasst es zusammen statt sie zu puffern. So wird
    aus Überlast ein niedrigerer Bildtakt statt wachsender Verzögerung.
  - Der Port braucht ein Token je Sitzung. Die CSP braucht `connect-src ws://127.0.0.1:<port>`; heute erlaubt sie
    nur `ipc:` und `http://ipc.localhost` (`tauri.conf.json:16`).
- **V2b bekommt keinen Prototyp**, obwohl die Schwelle verfehlt ist. V2b spart Bytes auf dem Transport, und der ist
  hier nicht der Engpass. Das Zeichnen derselben Pixel bliebe, dazu käme die Dekodierung im Webview.
- **GPU:** Ob der Weg mit GPU die Schwelle hält, ist nicht verifiziert, denn der Pool hat keine GPU. R-1075 bekommt
  dafür ein Gate: eine Messung auf echter Hardware unter Linux (WebKitGTK) und Windows (WebView2), bevor der
  eingebettete Weg zum Standard wird.
- **V1** hat keinen Prototyp (T1).
- **Tastatur.**
  - 23 von 24 Kombinationen kommen als `keydown` im Webview an, darunter Strg+W, Strg+Q, Strg+R, F5, F11, F12,
    Strg+Umschalt+I, Alt+F4, Alt+Tab, Super und Strg+Alt+Entf. Mit `preventDefault` lud die Seite nie neu, und das
    Fenster blieb offen.
  - Bei Strg+Alt+F2 kamen nur Strg und Alt an. Vermutlich belegt die Xvfb-Tastaturbelegung diese Kombination mit dem
    Konsolenwechsel; nicht verifiziert.
  - Ohne Fenstermanager sagt das nur etwas über den Webview selbst. Mit Fenstermanager oder unter Windows fängt das
    System Alt+Tab, Super und Strg+Alt+Entf vorher ab. R-1075 braucht deshalb einen Tastatur-Fang für die
    fokussierte Sitzung und für Strg+Alt+Entf einen Ersatz (Menüpunkt). Welche Wege Tauri unter X11, Wayland und
    Windows dafür bietet, ist nicht verifiziert.

## Ergebnis: Windows

Stand 2026-11-02 (T4). **Aufbau:**
- **Host:** ein GitHub-Runner `windows-latest` mit Windows Server 2025 Datacenter (Build 26100) und 4 vCPU. Die
  Grafik ist Hyper-V Video, eine GPU gibt es nicht. Der Workflow lag auf einem Wegwerf-Branch, der nie gemergt wurde.
  Branch und Läufe sind nach der Auswertung gelöscht, die Rohdaten liegen im Archiv (T5).
- **Server:** die Remotedesktopdienste des Runners, verbunden wird über Loopback. Der Server verlangt TLS mit NLA
  (`SecurityLayer` 2, `UserAuthentication` 1). Angemeldet wird ein Wegwerf-Benutzer mit Zufallspasswort; in den
  öffentlichen Logs ist das Passwort maskiert, und im Artefakt liegt es nicht.
- **Bildlast:** Ein Skript in der Sitzung zeichnet 50 % oder 100 % der Fläche im 33-ms-Takt neu, einen Verlauf plus
  Zufallsrechtecke. Es läuft in PowerShell und kommt dort auf 16–20 Bilder/s (Server-Zähler `Input Frames/Second`).
- **Clients:** dieselbe Probe wie in T2, zweimal gebaut: einmal mit gebündeltem OpenH264, einmal mit dem
  H.264-Dekoder von Media Foundation. Einen Gegenclient gibt es nicht, denn `mstsc` misst nicht kopflos.
- **Messung:** 20 s je Lauf nach 25 s Anlauf, für jeden Lauf eine frische Anmeldung. Die Bandbreite kommt aus dem
  Server-Zähler `Total Sent Bytes` (RemoteFX Network), die CPU je Prozess aus zwei Schnappschüssen, der Codec aus
  den Traces der Probe.

**Leistung** (1920×1080; Bilder/s und Qualität laut Server-Zählern `Output Frames/Second` und `Frame Quality`):

| Lauf | Codec | Mbit/s | Bilder/s | Qualität | Probe, % eines Kerns |
|---|---|---|---|---|---|
| idle | — | 0 | 0 | — | < 1 % |
| 50 %, AVC, OpenH264 | AVC420, dazu ClearCodec | 4,1 | 20,1 | 100 % | 40 % |
| 50 %, AVC, Media Foundation | AVC420, dazu ClearCodec | 3,8 | 19,6 | 100 % | 53 % |
| 100 %, AVC, OpenH264 | AVC420, dazu ClearCodec | 4,5 | 16,3 | 100 % | 42 % |
| 50 %, ohne AVC | RemoteFX Progressive, dazu ClearCodec | 4,5 | 16,3 | 65 % | 67 % |
| 100 %, ohne AVC | RemoteFX Progressive, dazu ClearCodec | 4,9 | 9,5 | 36 % | 79 % |
| 50 %, ohne GFX | 16-bpp-RLE-Bitmaps | 0,2 | 0,7 | — | 3 % |

**Befunde:**
- **Codec.** Mit AVC wählt Windows AVC420, obwohl die Probe auch AVC444 anbietet. Ohne AVC kommt RemoteFX
  Progressive. Text und Kanten gehen in beiden Fällen zusätzlich über ClearCodec.
- **AVC ist gegen Windows der bessere Weg.** Bei gleicher Bandbreite liefert AVC volle Qualität, und die Probe
  braucht rund 40 % eines Kerns. Ohne AVC braucht sie 67–79 %. Windows senkt dabei die Qualität auf 36–65 % und
  überspringt Bilder (Zähler „Insufficient Network Resources“).
  - Der Server-Zähler `Current TCP Bandwidth` stand in allen Läufen auf 10 000, `Base TCP RTT` auf 5 ms. Ob Windows
    die Netzerkennung (Auto-Detect) gegen die Probe überhaupt gefahren hat, ist nicht verifiziert.
  - Media Foundation dekodiert hier ohne GPU und braucht mehr CPU als OpenH264 (53 % gegen 40 %). Wie es mit GPU
    aussieht, ist nicht verifiziert.
- **Ohne GFX ist der Weg unbrauchbar.** Windows schickt dann nur 16-bpp-RLE-Bitmaps statt klassischem RemoteFX wie
  xrdp. Laut eigenem Zähler überspringt es 20 Bilder/s („Insufficient Client Resources“), in der Probe kommen 0,7
  Bilder/s an. Die Ursache ist nicht verifiziert. Gegen Windows fährt R-1075 nur mit GFX.
- **Anmeldung.**
  - NLA: CredSSP (`HYBRID_EX`) mit einem lokalen Konto gelingt. Die Verbindung steht nach 0,1–0,4 s. Das erste Bild
    kam in den Aufwärmläufen nach 0,5–0,9 s, in den Messläufen nach 4,3–5,5 s; den Unterschied habe ich nicht
    geklärt. Die allererste Anmeldung eines Profils dauerte 20 s.
  - Windows meldet während der Anmeldung `LOGON_MSG_SESSION_CONTINUE` (Logon Errors Info, MS-RDPBCGR). Das ist eine
    Information, kein Fehler. Der Treiber hielt die Meldung für einen Fehlschlag und fuhr die Messläufe deshalb mit
    TLS ohne NLA. Die Messwerte betrifft das nicht, R-1075 darf die Meldung aber nicht als Fehler werten.
- **Resize und Monitor-Layout.**
  - Windows setzt beide live um. Nach dem `MonitorLayout` (Display Control) kommt binnen 0,1 s ein EGFX-`ResetGraphics`
    mit 1280×720 bzw. 2560×720. Beim Zwei-Monitor-Layout sind es zwei Surfaces, die zweite bei x = 1280. Die Sitzung
    sieht spätestens 1,5 s später zwei Monitore (2560×720 virtuell).
  - `ironrdp-client` wertet einen Resize aber erst nach einer Deaktivierung und Reaktivierung als fertig
    (`src/rdp.rs:5746`). Die schickt Windows mit GFX nicht. Nach 3 s (`DISPLAY_CONTROL_READY_TIMEOUT`,
    `src/rdp.rs:1100`) fällt der Client deshalb auf eine Neuverbindung mit der neuen Größe zurück
    (`ReactivationTimedOut`). Ein Resize kostet so rund 4 s statt 0,1 s, und am Ende hat die Sitzung die angefragte
    Größe.
  - Mit und ohne Bulk-Kompression verhält sich das gleich. Der Fehler aus T2, eine komprimierte PDU in der
    Reaktivierung, tritt gegen Windows nicht auf, weil Windows nicht reaktiviert.
- **Kanäle.** Ein Lauf mit nativer Zwischenablage, Laufwerk und Audio:
  - **Audio:** RDPSND läuft über den dynamischen Kanal. Windows bietet AAC an (44,1 kHz, Stereo), die Probe dekodiert
    mit dem AAC-Dekoder von Media Foundation, und die Sitzung spielte drei Töne ab. Ob sie hörbar waren, ist nicht
    verifiziert, denn der Runner hat kein Audiogerät (CPAL: „device not found“).
  - **Absturz:** Im selben Lauf endete die Probe mit einem Absturz des Prozesses, der Server protokollierte in
    derselben Sekunde den Verbindungsabbruch. Ein Abfangen von Panics hätte das nicht verhindert; im Desktop endet so
    die ganze App. Die Ursache ist nicht verifiziert. Die Einzelheiten bleiben im privaten Archiv, bis sie geklärt
    und, wo nötig, gemeldet sind.
  - **Zwischenablage:** In keiner Richtung kam Inhalt an, die Probe protokollierte nur den Start des nativen Backends.
    Die Ursache ist nicht verifiziert; ein Kandidat ist, dass der Runner-Prozess keinen interaktiven Desktop hat.
  - **Laufwerk:** Es ist angemeldet und in der Sitzung sichtbar. Windows fragte Attribute ab, und die Probe antwortete
    mit `STATUS_SUCCESS`.
    - Der Name kommt verkürzt an: aus „spike“ wird `\\TSCLIENT\s`. Die Ursache ist nicht verifiziert (Kandidat: die
      Kodierung des Gerätenamens).
    - Das Sitzungsskript suchte deshalb unter dem vollen Namen, Lesen und Schreiben sind nicht verifiziert.
  - Ein Gegenlauf mit Stub-Zwischenablage startete wegen eines Fehlers im Wegwerf-Treiber nicht. Einen dritten
    Anlauf gab es nicht (Abbruchkriterium).
- **RTT.** Ein `NetworkCharacteristics`-Ereignis kam in keinem Lauf an.
- **Nicht gemessen:**
  - Strg+Alt+Entf als Scancode-Folge;
  - NLA mit Domänenkonto oder Kerberos;
  - eine GPU;
  - ein Gegenclient;
  - Lesen und Schreiben auf dem Laufwerk;
  - Zwischenablage-Inhalte.

## Ergebnis: Entscheidung

Stand 2026-11-02 (T5). Empfehlung an Kevin, der über Variante, Restrisiko und Umfang entscheidet (Offene Fragen 2).

**Variante: V2.** IronRDP läuft nativ im Rust-Prozess des Desktops. Das Bild geht über einen lokalen WebSocket mit
Gegendruck an den Webview, gezeichnet wird mit WebGL, Rückfall Canvas2D. V3a bleibt Rückfall, falls V2 im Bau an
Protokoll oder Stabilität scheitert. V1, V2b, V3b und V3c entfallen.

**Begründung:**
- **Protokoll trägt.** Gegen xrdp liegt die Probe bei Bandbreite und Client-CPU gleichauf mit FreeRDP 3 (T2).
  Gegen Windows (T4) meldet sie sich mit NLA an, bekommt AVC420 in voller Qualität bei rund 4 Mbit/s und braucht
  dafür 40 % eines Kerns; Resize und Monitor-Layout setzt Windows live um.
- **Sicherheit.** Passwort und CredSSP bleiben im Rust-Prozess wie heute (`rdp.rs:488`, Keyring). Die CSP braucht kein
  `wasm-unsafe-eval`. Der Dekoder ist Rust mit eigener Fuzzing-Crate und ohne veröffentlichte Advisories; V3a holte
  einen C-Dekoder mit 243 Advisories seit 2026-01-01 in den App-Prozess (K13).
- **Kanäle nativ.** Zwischenablage, Audio und Laufwerke gibt es als native Crates für Linux und Windows (K4–K6); V1
  fehlen Audio und Laufwerke.
- **Sitzung im Backend.** Sie überlebt das Abdocken (R-1070) und folgt dem Muster von R-1069 (Prozess in Rust, Daten
  an den Webview).
- **Bildweg.** Der Transport über einen lokalen WebSocket trägt 50 % Fläche bei 30 Hz ohne wachsenden Rückstau (T3).
  Engpass ist das Zeichnen ohne GPU; ob der Weg mit GPU unter 33 ms bleibt, ist nicht verifiziert (GPU-Gate,
  Bedingung 4).

**Bedingungen für R-1075** (aus T2 bis T4; jede wird eine Task oder ein Abnahmekriterium):
1. **Bulk-Kompression aus** (`ConfigBuilder::with_compression(false)`), bis IronRDP die Verbindungs-Finalisierung
   dekomprimiert. Sonst scheitern Resize und Monitor-Layout gegen xrdp (T2). Gegen Windows ändert die Kompression
   nichts, weil Windows nicht reaktiviert (T4).
2. **Watchdog.** Eine Sitzung, die bei offener Verbindung keine Bilder mehr bekommt, erkennt das Backend und baut sie
   neu auf (Stillstand in einem von acht GFX-Läufen, T2).
3. **Bildweg.** Lokaler WebSocket statt Tauri-Channel, nur auf 127.0.0.1, mit einem zufälligen Token je Sitzung;
   Gegendruck wie in „Ergebnis: Webview“ beschrieben. Die CSP bekommt `connect-src … ws://127.0.0.1:*`, denn der Port
   wird zur Laufzeit gewählt. Eingaben gehen über denselben Socket zurück.
4. **GPU-Gate.** Bevor „AdminHelper“ der Standard der Einstellung wird, misst R-1090 den Bildweg auf echter Hardware
   unter Linux (WebKitGTK) und Windows (WebView2) gegen die Schwelle aus T3. Bis dahin bleibt der OS-Client der
   Standard.
5. **Zertifikat.** Eigener rustls-Prüfer mit TOFU-Pin je Host und Port nach dem Muster von `tofu.rs:314`
   (`TofuVerifier`, Pin im Keyring) und einem Fingerprint-Dialog beim ersten Kontakt. `trust_cert`
   (`models.rs:80`) bedeutet danach: ohne Dialog annehmen. IronRDP prüft im Default nicht (K3, [Q5]).
6. **Tastatur.** Ein Tastatur-Fang für die fokussierte Sitzung, Strg+Alt+Pos1 gibt frei; Strg+Alt+Entf als Menüpunkt,
   weil das System es vor dem Webview abfängt (T3). Ob Windows die Scancode-Folge als Secure Attention Sequence
   annimmt, ist nicht verifiziert (T4 hat es nicht gemessen); Stufe 2 prüft es.
7. **H.264 unter Linux aus.** Kein gebündeltes OpenH264 (aus Quellen gebaut, ohne Patentdeckung, [Q2]); AVC nur unter
   Windows über Media Foundation (`ironrdp-egfx-native`, [Q3]). Linux fällt auf RemoteFX Progressive zurück (T2);
   gegen Windows kostet das bei 50 % Fläche Qualität und CPU (65 statt 100 %, 67 statt 40 % eines Kerns, T4).
8. **TLS-Provider ring.** Der Desktop hält `aws-lc-rs` heute heraus (`Cargo.toml`: reqwest `rustls-no-provider`,
   rustls mit `ring`). Das Feature `rustls` von `ironrdp-client` zieht es über `ironrdp-tls/rustls`
   (= `rustls-aws-lc-rs`), `udp` ebenso. R-1075 nimmt `ironrdp-client` ohne beide und wählt `ironrdp-tls` direkt mit
   `rustls-ring` [Q18]. Ob `ironrdp-client` so baut, ist nicht verifiziert: Stufe 1 prüft es zuerst. Gate im Build:
   `cargo tree -i aws-lc-rs` bleibt leer.
9. **GFX gegen Windows.** Ohne EGFX schickt Windows nur 16-bpp-Bitmaps mit unter einem Bild/s (T4). Der Desktop
   bietet EGFX immer an.
10. **Resize-Abschluss über `ResetGraphics`.** Mit GFX schließt Windows einen Resize per `ResetGraphics` ab, ohne
    Reaktivierung. `ironrdp-client` wartet auf eine Reaktivierung und verbindet nach 3 s neu (T4). R-1075 wertet
    `ResetGraphics` als Abschluss (Patch upstream oder eigene Sitzungsschleife); Abnahme: ein Resize gegen Windows
    ohne Neuverbindung.
11. **Anmelde-Infos sind keine Fehler.** `LOGON_MSG_SESSION_CONTINUE` und andere Logon-Infos (MS-RDPBCGR) brechen die
    Sitzung nicht ab (T4).
12. **Audio unter Windows erst nach Klärung des Absturzes** (T4, Restrisiken). Bis dahin bleibt Audio dort aus; jeder
    Kanal hat ohnehin einen eigenen Schalter (Mockup). Abnahme auf einem Windows mit Audiogerät.

**Restrisiken** (für Kevin, Offene Fragen 2):
- **Patente.** AdminHelper verteilte erstmals eine eigene RDP-Implementierung. Microsofts Open Specifications Promise
  nennt keine RDP-Spezifikation, MS-RDPEDISP verweist auf mögliche Patente [Q12]. Nicht juristisch geprüft.
- **Abhängigkeit vor 1.0.** `ironrdp-client` mit EGFX gibt es nur auf `main` [Q4]; R-1075 pinnt eine Git-Revision und
  wechselt auf crates.io, sobald eine Version mit EGFX erscheint. Die Low-Level-Crates sind 0.x mit häufigen
  Breaking-Bumps [Q1].
- **Dekoder im App-Prozess.** Ein Fehler im Dekoder trifft den ganzen Desktop-Prozess, nicht wie heute einen
  Kindprozess. Im sicheren Rust bleibt das bei Panics und Logikfehlern, und Panics fängt die Sitzungsaufgabe ab
  (Bauplan Stufe 1). Code hinter FFI (Media Foundation, Audio über CPAL) kann den Prozess aber auch ohne Panic
  beenden.
- **Resize-Leistung.** IronRDP-Issue #447 [Q17]: nach einem Resize bricht die Leistung auf dem RemoteFX-Pfad ein,
  FreeRDP ist nicht betroffen; bei uns nicht verifiziert.
- **Stillstand.** Ursache nicht verifiziert (T2); der Watchdog macht ihn zur Neuverbindung, nicht zum Fehler.
- **Absturz mit Audio unter Windows.** Im Kanal-Lauf endete die Probe mit einem Absturz, den kein Abfangen von Panics
  verhindert hätte (T4). Im Desktop beendete so ein Fehler die App mit allen offenen Tabs. Die Ursache ist nicht
  verifiziert (Bedingung 12).
- **Kanäle unter Windows.** Die Zwischenablage brachte keinen Inhalt, der Laufwerksname kam verkürzt an, Lesen und
  Schreiben sind nicht geprüft (T4). Stufe 3 klärt das und nimmt es auf einem interaktiven Windows ab.
- **Erstes Bild.** In den Messläufen gegen Windows kam es erst nach 4–5 s, in den Aufwärmläufen nach unter 1 s; nicht
  geklärt (T4).

**Bauplan für R-1075.** Empfehlung: R-1075 bei der Triage je Stufe in eigene Zeilen teilen; jede Stufe ist für sich
nutzbar und einzeln zurücknehmbar.

| Stufe | Inhalt | Hängt ab von | Heavy | Merger |
|---|---|---|---|---|
| 1 Backend | Abhängigkeit (Git-Revision, Features nur `clipboard`, `sound`, `rdpdr`, TLS ring; Windows dazu Media Foundation), Lizenz-Gates; Sitzung über `resolve_connection` (`commands.rs:568`, `tunnel.rs:76`) mit dem Passwort aus dem Keyring (`connection/mod.rs:247`); TLS-Prüfer mit TOFU (Risikopfad, `security`); Watchdog; WebSocket-Server mit Token und Gegendruck; Phasen-Events; Integrationstest gegen einen xrdp-Container | — | linux-full | Session; ein neuer CI-Job für den xrdp-Test ändert `.github/workflows/` und geht an Kevin |
| 2 Tab | Canvas mit WebGL, Rückfall 2d; Scancodes und Tastatur-Fang; Statuszeile (Auflösung, Codec, fps, Mbit/s); Phasen verbinden/verbunden/getrennt; Neu verbinden; Screenshot (`dialog:allow-save` ist schon erlaubt); Leistungsprofil; Einstellung `rdp_client` in `Settings` (`models.rs:91`, `#[serde(default)]`, Wire-Vertrag, Risikopfad) und Split-Button | Stufe 1; die Tab-Leiste aus R-1069 | linux-full | Session |
| 3 Kanäle | Zwischenablage Text; Audio (CPAL braucht unter Linux `libasound2-dev` in `ci.yml` und `release.yml`; unter Windows nach Bedingung 12); Laufwerke (Freigabe eines Ordners, `security`) | Stufe 1 | linux-full, windows | Kevin (Workflows) |
| 4 Anzeige | dynamische Auflösung mit Entprellen und Resize-Abschluss über `ResetGraphics` (Bedingung 10), Fest mit Zoom/1:1/Einpassen, Vollbild, HiDPI-Skalierung | Stufe 2 | linux-full | Session |
| 5 Fenster | Abdocken, Multi-Monitor als zwei Fenster | Stufe 2; R-1070 | linux-full, windows | Session |
| später | RD-Gateway (`gateway`, ohne Gateway im Pool nicht prüfbar), H.264 unter Linux, Dateien über die Zwischenablage | — | — | — |

**Mockup-Funktionen je Stufe:**
- Stufe 2: Tab, Phasen, Neu verbinden, Strg+Alt+Entf (Menü), Screenshot, Verbindungsinfo, Leistungsprofil,
  Tastatur-Fang mit Strg+Alt+Pos1. Die RTT meldet `ironrdp-client` als `RdpOutputEvent::NetworkCharacteristics`
  (`src/rdp.rs:245`), wenn der Server Auto-Detect-Ergebnisse schickt (MS-RDPBCGR 2.2.14.1.5) [Q4]; die Probe hat es
  weder gegen xrdp (T2) noch gegen Windows (T4) bekommen. Die Statuszeile zeigt die RTT deshalb nur, wenn das
  Ereignis kommt, sonst „—“.
- Stufe 3: Schalter Zwischenablage, Laufwerke, Audio.
- Stufe 4: Skalierung (Auto, 100 %, HiDPI), Eingepasst mit dynamischer Auflösung, Vollbild, Fest mit Zoom 25–200 %.
- Stufe 5: Abdocken, Multi-Monitor.
- Entfällt bis auf Weiteres: Codec-Anzeige „AVC444“ unter Linux (dort kein H.264, Bedingung 7); unter Windows zeigt
  die Statuszeile den ausgehandelten Codec.

**Lizenzen.** Die Probe zieht unter Linux 362 Pakete, alle mit permissiven Lizenzen (MIT, Apache-2.0, BSD, ISC,
Zlib, Unicode); 166 davon fehlen heute im Desktop-Lock, darunter 31 `ironrdp-*`. OpenH264 (BSD-2-Clause) entfällt
unter Linux (Bedingung 7). Stufe 1 erzeugt `THIRD_PARTY_LICENSES.md` neu (`scripts/gen-third-party-licenses.sh`)
und setzt Gates in den Build: `cargo tree -i aws-lc-rs` und `cargo tree -i openh264-sys2` leer unter Linux,
`cargo audit` läuft schon (`audit.yml`). Das Release-Binary der Probe ist 26 MB groß; um wie viel der Desktop
wächst, misst Stufe 1.

**CSP und Capabilities.**
- CSP (`tauri.conf.json:16`): `connect-src` um `ws://127.0.0.1:*` erweitern; `script-src` bleibt ohne
  `wasm-unsafe-eval`.
- Capabilities (`capabilities/default.json`): Stufe 1 bis 4 brauchen nichts Neues (`dialog:allow-save` für den
  Screenshot ist da). Stufe 5 legt Fensterrechte je Label fest, nach dem Plan von R-1070.

**Folgezeilen** (als `neu`, Triage durch Kevin; R-1075 geht zurück auf `neu`):
- R-1090: Abnahme auf echter Hardware als Gate vor dem Standardwechsel: der Bildweg mit GPU unter Linux
  (WebKitGTK) und Windows (WebView2) gegen p95 33 ms, dazu unter Windows mit Audiogerät und interaktivem Desktop
  Audio, Zwischenablage und Laufwerk.
- R-1091: IronRDP upstream melden (nach außen, Kevins Wort): komprimierte PDU in der Verbindungs-Finalisierung (T2),
  Resize gegen Windows mit GFX ohne `ResetGraphics`-Abschluss (T4), verkürzter RDPDR-Gerätename (T4, Ursache
  offen).
- R-1092: den Absturz mit Audio unter Windows klären (T4, Bedingung 12).

## Datenmodell / API / Migrationen

Keine in diesem Vorhaben. Für R-1075 (Bauplan in „Ergebnis: Entscheidung“): `RdpOptions` (`models.rs:57`,
Wire-Vertrag Desktop-UI ↔ Backend) bekommt voraussichtlich die Kanal-Schalter und das Leistungsprofil, `Settings`
(`models.rs:91`) die Einstellung `rdp_client` mit `#[serde(default)]`. Dazu kommen Tauri-Commands zum Starten und
Trennen einer Sitzung, ein lokaler WebSocket für Bild und Eingaben, die CSP (`tauri.conf.json:16`) und ab Stufe 5
Fensterrechte je Label. Server, Web, Agent und Datenbank sind nicht betroffen (keine Migration).

## Externe Integrationen

- IronRDP: <https://github.com/Devolutions/IronRDP> (MIT OR Apache-2.0; Client-Dekodierung roh, Interleaved RLE,
  RDP 6, RemoteFX; EGFX mit ClearCodec, RFX Progressive und H.264 AVC420/AVC444 in `ironrdp-egfx`; NLA über CredSSP
  mit NTLM und Kerberos; MS-TSGU-Transport; KDC-Proxy und RDCleanPath; Kanäle CLIPRDR, RDPSND, RDPDR, Display
  Control; WASM-Bindings und Web-Komponente, deren Bau Node 24 braucht). Einzelheiten und Versionen: „Ergebnis:
  Matrix“, [Q1] bis [Q8].
- FreeRDP: <https://github.com/FreeRDP/FreeRDP> (Apache-2.0, 3.33.0; [Q9]).
- xrdp: <https://github.com/neutrinolabs/xrdp>.
- MS-Spezifikationen auf learn.microsoft.com: MS-RDPBCGR (Kern), MS-RDPEGFX (Grafik-Pipeline), MS-RDPEDISP
  (Display Control), MS-RDPECLIP (Zwischenablage), MS-RDPEFS (Laufwerke), MS-RDPEA (Audio), MS-TSGU (Gateway),
  MS-CSSP (CredSSP).
- Tauri 2, Frontend aufrufen und Channels: <https://v2.tauri.app/develop/calling-frontend/>.

## Trade-offs & Alternativen

Empfehlung nach T1–T4: **V2**; Begründung, Bedingungen und Restrisiken stehen in „Ergebnis: Entscheidung“. Das
Passwort bleibt im Rust-Prozess wie heute (`spawn_rdp_with_password`, Keyring), die CSP bleibt ohne
`wasm-unsafe-eval`, die Kanäle laufen nativ, Linux und Windows teilen einen Code-Weg, und die Sitzung lebt im Backend
wie das PTY von R-1069. Das Bild geht über einen lokalen WebSocket statt über einen Tauri-Channel (T3). V1 ist der
Weg, den Devolutions selbst für den Browser geht, verlagert aber Anmeldedaten und Protokoll in den Webview. V3a ist am
reifsten, kostet aber eine C-Abhängigkeit mit eigener Paketierung, eigene Bindings und einen C-Dekoder im
App-Prozess; es bleibt Rückfall. V3b und V3c sind ausgeschlossen (Wayland bzw. ein Dienst mehr über FreeRDP).

## Risiken & Rollback

- **AVC unter Linux:** IronRDP dekodiert H.264 unter Windows über Media Foundation, unter Linux nur mit OpenH264
  (Cisco-Binary vom Nutzer oder aus Quellen gebaut, Patentfrage) [Q2][Q3]. Ohne OpenH264 fällt die Linux-Seite auf
  RemoteFX, Progressive oder Planar zurück. Gegen Windows kostet das bei 50 % Fläche kaum Bandbreite (4,5 statt
  4,1 Mbit/s), aber Qualität (65 statt 100 %), Bildtakt (16 statt 20 Bilder/s) und Client-CPU (67 statt 40 % eines
  Kerns, T4). xrdp sendet ohnehin kein H.264 (T2).
- **Windows-Host:** T4 lief auf einem GitHub-Windows-Runner (Kevin 2026-11-02), Windows nahm RDP über Loopback an.
  Was dort nicht prüfbar war (Zwischenablage, Laufwerk, Audio hörbar, GPU), steht in „Ergebnis: Windows“ unter
  „Nicht gemessen“ und wird R-1090.
- **Ressourcen:** Ein Desktop-Build braucht 4–6 GiB, die Dev-Box ist oft über der Lastgrenze. T3 lief deshalb auf
  der Desktop-VM der Lane, T4 auf dem Runner; die Build-Verzeichnisse der Probe gehen mit dem Worktree beim Teardown.
- **Fremdcode:** Prototyp-Abhängigkeiten aus crates.io und npm laufen nur in der Wegwerf-Umgebung, nie im Produkt.
- **Öffentlichkeit:** Diese Spec nennt keine Lab-Adressen, Hostnamen, VM-IDs oder Zugangsdaten; Rohdaten mit solchen
  Angaben bleiben unter `tasks/private/`.
- **Rollback:** reine Doku, Revert des Merge-Commits.

## Doku-Impact

Keine Produkt-Doku: kein Verhalten ändert sich. Das Ergebnis steht in dieser Spec; R-1075 zieht
`docs/developer/desktop.html` (DE+EN), `README.md` und `THIRD_PARTY_LICENSES.md` nach. Kein CHANGELOG-Fragment.

## Offene Fragen

1. **Woher kommt der Windows-Host für T4?** Entschieden (Kevin 2026-11-02): ein GitHub-Windows-Runner über einen
   temporären Workflow auf einem eigenen Wegwerf-Branch, der nie gemergt und danach gelöscht wird: RDP aktivieren,
   Wegwerf-Benutzer mit zufälligem Passwort, Probe-Client gegen den eigenen Loopback, Logs ohne Geheimnisse (sie sind
   öffentlich).
2. **Nach T5 (Kevin), je mit Empfehlung** (Grundlage „Ergebnis: Entscheidung“); R-1075 wird danach neu triagiert:
   - Variante: **V2**, V3a als Rückfall.
   - Restrisiko Patente einer eigenen RDP-Implementierung: hinnehmen (nicht juristisch geprüft); der OS-Client
     bleibt wählbar.
   - H.264 unter Linux: aus, kein gebündeltes OpenH264; unter Windows über Media Foundation.
   - Standard der Einstellung „RDP: AdminHelper | OS-Client“: OS-Client, bis die Abnahme auf echter Hardware
     (R-1090) grün ist.
   - Mockup-Funktionen: nach den Bauplan-Stufen, R-1075 je Stufe in eigene Zeilen geteilt; RD-Gateway, H.264 unter
     Linux und Dateien über die Zwischenablage später.
   - IronRDP-Fehler upstream melden (nach außen): ja (R-1091).
