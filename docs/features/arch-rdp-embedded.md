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
- **T4 — Windows-Probe** `[?]`. Derselbe Probe-Client gegen einen echten Windows-Host: NLA/CredSSP, Codec-Aushandlung
  (welcher Codec ohne AVC kommt), Resize, Zwischenablage, Audio, Laufwerke, Monitor-Layout. Woher der Host kommt,
  entscheidet Kevin (Offene Fragen 1).
- **T5 — Entscheidung und Bauplan.** Ergebnis in dieser Spec (Abschnitt „Ergebnis“): gewählte Variante mit
  Begründung und Restrisiken, Bauplan für R-1075, Archiv nach `tasks/private/spikes/`, R-1075 mit Notiz zurück auf
  `neu` zur Triage, Folgezeilen als `neu`.

**Abbruchkriterium:** Die Studie ist fertig, wenn jedes Kriterium je Variante belegt, ausgeschlossen oder begründet
„nicht verifiziert“ ist. Ein Prototyp-Schritt, der nach zwei Anläufen nicht läuft, wird als Befund festgehalten
(nach einmal `advisor`), nicht weiter erzwungen.

## Datenmodell / API / Migrationen

Keine in diesem Vorhaben. Für R-1075 bewertet T5: Erweiterung von `RdpOptions` (`models.rs:57`, Wire-Vertrag
Desktop-UI ↔ Backend), neue Tauri-Commands und ein Channel für den Bildweg, die globale Einstellung „RDP: AdminHelper
| OS-Client“ und wo sie liegt, die CSP (`tauri.conf.json:16`) und die Capabilities. Server, Web, Agent und Datenbank
sind nach heutigem Stand nicht betroffen (keine Migration).

## Externe Integrationen

- IronRDP: <https://github.com/Devolutions/IronRDP> (README gelesen 2026-11-02: MIT OR Apache-2.0; Client-Dekodierung
  roh, Interleaved RLE, RDP 6, RemoteFX; Bausteine ClearCodec, RFX Progressive, ZGFX, EGFX-PDUs; H.264 nennt das
  README nicht; NLA über CredSSP mit NTLM und Kerberos; MS-TSGU-Transport; KDC-Proxy und RDCleanPath; Kanäle CLIPRDR,
  RDPSND, RDPDR, Display Control; WASM-Bindings und Web-Komponente, deren Bau Node 24 braucht).
- FreeRDP: <https://github.com/FreeRDP/FreeRDP> (Lizenz und Codec-Stand in T1 zu belegen).
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
Browser geht, verlagert aber Anmeldedaten und Protokoll in den Webview. V3a bringt AVC und RD-Gateway, kostet aber
eine C-Abhängigkeit mit eigener Paketierung und die H.264-Frage. V3b und V3c scheitern voraussichtlich an Wayland
bzw. Windows.

## Risiken & Rollback

- **Kein AVC:** Nennt IronRDP kein H.264, entfällt „AVC444“ aus dem Mockup, und Windows-Hosts fallen auf RemoteFX,
  Progressive oder Planar zurück: mehr Bandbreite. T2/T4 messen, wie viel.
- **Kein Windows-Host im Pool:** T4 hängt an Kevins Antwort; ohne Host bleibt die Windows-Seite „nicht verifiziert“
  und wird die erste Task von R-1075.
- **Ressourcen:** `/` hat rund 38 GiB frei, ein Desktop-Build braucht 4–6 GiB, die Dev-Box ist oft über der
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

1. **Woher kommt der Windows-Host für T4?** (Kevin; T4 steht auf `[?]`.) Empfehlung: ein GitHub-Windows-Runner über
   einen temporären Workflow auf einem eigenen Wegwerf-Branch, der nie gemergt und danach gelöscht wird: RDP
   aktivieren, Wegwerf-Benutzer mit zufälligem Passwort, Probe-Client gegen den eigenen Loopback, Logs ohne Geheimnisse
   (sie sind öffentlich). Kostet keine Infrastruktur; dass Windows RDP auf Loopback annimmt, ist nicht verifiziert.
   Alternativen: eine Windows-Server-Eval-Vorlage im Pool `adminhelper-ci` backen (dient auch R-0541, Bake nur auf
   Zuruf), Kevins eigener Host (Zugang privat), oder ohne Windows („nicht verifiziert“, Probe wird erste Task von
   R-1075).
2. **Nach T5 (Kevin):** die gewählte Variante, das Restrisiko (z. B. Passwort im Webview bei V1), die Mockup-Funktionen,
   die entfallen oder später kommen (AVC444, RD-Gateway, Multi-Monitor), und der Standard der Einstellung
   „RDP: AdminHelper | OS-Client“. Diese Fragen stellt T5 mit Empfehlung; R-1075 wird danach neu triagiert.
