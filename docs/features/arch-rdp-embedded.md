<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Eingebettetes RDP: Machbarkeit

Architektur-Vorhaben `arch-rdp-embedded` (Roadmap R-1074; die Bau-Zeile R-1075 ist bis zur Entscheidung
zurückgestellt). Stand: `origin/main@b2edbbf8`.

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

## Datenmodell / API / Migrationen

Keine in diesem Vorhaben. Für R-1075 bewertet T5: Erweiterung von `RdpOptions` (`models.rs:57`, Wire-Vertrag
Desktop-UI ↔ Backend), neue Tauri-Commands und ein Channel für den Bildweg, die globale Einstellung „RDP: AdminHelper
| OS-Client“ und wo sie liegt, die CSP (`tauri.conf.json:16`) und die Capabilities. Server, Web, Agent und Datenbank
sind nach heutigem Stand nicht betroffen (keine Migration).

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

Vorläufige Empfehlung (Hypothese, T5 entscheidet): **V2**. Das Passwort bleibt im Rust-Prozess wie heute
(`spawn_rdp_with_password`, Keyring), die CSP bleibt ohne `wasm-unsafe-eval`, die Kanäle laufen nativ, Linux und
Windows teilen einen Code-Weg, und das Muster passt zu R-1069 (PTY in Rust, Daten über einen Tauri-Channel). Das
Risiko liegt in der Bildstrecke Rust → Webview; T3 misst genau das. V1 ist der Weg, den Devolutions selbst für den
Browser geht, verlagert aber Anmeldedaten und Protokoll in den Webview. V3a ist am reifsten, kostet aber eine
C-Abhängigkeit mit eigener Paketierung, eigene Bindings und einen C-Dekoder im App-Prozess. V3b und V3c sind
ausgeschlossen (Wayland bzw. ein Dienst mehr über FreeRDP). Stand nach T1: „Ergebnis: Matrix“.

## Risiken & Rollback

- **AVC unter Linux:** IronRDP dekodiert H.264 unter Windows über Media Foundation, unter Linux nur mit OpenH264
  (Cisco-Binary vom Nutzer oder aus Quellen gebaut, Patentfrage) [Q2][Q3]. Ohne OpenH264 fällt die Linux-Seite auf
  RemoteFX, Progressive oder Planar zurück: mehr Bandbreite. T2/T4 messen, wie viel.
- **Windows-Host:** T4 läuft auf einem GitHub-Windows-Runner (Kevin 2026-11-02); dass Windows RDP auf Loopback
  annimmt, ist nicht verifiziert. Scheitert das, bleibt die Windows-Seite „nicht verifiziert“ und wird die erste
  Task von R-1075.
- **Ressourcen:** `/` hat rund 32 GiB frei, ein Desktop-Build braucht 4–6 GiB, die Dev-Box ist oft über der
  Lastgrenze. T3 läuft deshalb auf der Desktop-VM der Lane, Läufe starten erst bei Last unter ~10, Build-Verzeichnisse
  werden nach der Messung gelöscht.
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
2. **Nach T5 (Kevin):** die gewählte Variante, das Restrisiko (z. B. Passwort im Webview bei V1), die Mockup-Funktionen,
   die entfallen oder später kommen (AVC444, RD-Gateway, Multi-Monitor), und der Standard der Einstellung
   „RDP: AdminHelper | OS-Client“. Diese Fragen stellt T5 mit Empfehlung; R-1075 wird danach neu triagiert.
