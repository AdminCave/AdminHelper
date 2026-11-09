# Eingebettetes RDP Stufe 4 (Anzeige) und Stufe 5 (Fenster)

Zug `kern-rdp-4`, Roadmap R-1100 (Stufe 4) und R-1101 (Stufe 5). Grundlage: Bauplan in
`docs/features/arch-rdp-embedded.md` (Entscheidung V2, Bedingungen 1–12, Stufen 4 und 5); Stufe 2 (Tab) und der
Fork-Pin kamen mit `kern-rdp-1` (PR #419), das Abdocken von Terminals mit R-1070 (PR #409).

## Problem / Motivation

- **R-1100:** Der RDP-Tab zeigt fest 1280×720 (`session.rs:42-43`, Kommentar „Fixed in stage 1“) und passt das
  Bild per `object-fit: contain` ein (`RdpSession.svelte:452`). Ein großes Fenster zeigt so ein unscharfes,
  vergrößertes Bild, ein kleines ein winziges. Die Einstellungen für den Client des Systems kennen schon Skalierung
  (`rdp_scaling_mode`: Auto, 100 %, HiDPI) und Fenster (`rdp_window_mode`: Eingepasst, Vollbild, Multi-Monitor,
  Fest mit `rdp_custom_size`, `models.rs:269-273`); der eingebettete Tab beachtet sie nicht.
- **Bedingung 10:** Mit GFX schließt Windows einen Resize per `ResetGraphics` ab, ohne Deaktivierung und
  Reaktivierung. Die gepinnte `ironrdp-client`-Revision wertet einen Resize aber nur bei Reaktivierung als fertig
  (`ResizeQueue::completed`, `crates/ironrdp-client/src/rdp.rs:1135`, aufgerufen bei `:5750`) und verbindet nach
  `DISPLAY_CONTROL_READY_TIMEOUT` = 3 s (`:1100`) neu. Ein Resize kostet so rund 4 s und eine Neuverbindung.
  `ironrdp-session` meldet den Reset schon (`active_stage.rs:1260`, Feld `reset`).
- **R-1101:** Ein RDP-Tab lässt sich nicht abdocken. Der Bild-WebSocket nimmt genau einen Client und hört nach
  dessen Anmeldung auf zu lauschen (`frame_ws.rs:155`); geht der Webview weg, endet die Sitzung. Ein zweites
  Fenster (Abdocken, zweiter Monitor) kann sich also nicht anmelden.

## Ziel & Nicht-Ziele

Ziel Stufe 4:
- Der Tab startet mit den Einstellungen aus *Einstellungen → RDP* und lässt sie in seiner Kopfleiste für diesen Tab
  umstellen, wie das Leistungsprofil:
  - *Eingepasst* (Standard): Die Auflösung folgt der Größe des Tabs. Ein Resize schickt Display Control
    (MS-RDPEDISP) nach einer Entprellzeit; ohne Display Control verbindet der Tab mit der neuen Größe neu.
  - *Fest*: `rdp_custom_size` (Standard 1280×720) mit Zoom 25–200 %, *1:1* und *Einpassen*; Bildlaufleisten, wenn
    das Bild größer ist als der Tab.
  - *Vollbild*: Das Fenster geht in den Vollbildmodus. Eine Leiste am oberen Rand blendet beim Darüberfahren ein und
    führt zurück; die Auflösung folgt dem Bildschirm.
- Skalierung: *Auto* schickt `devicePixelRatio` als Skalierungsfaktor (100/125/150/175/200 %, MS-RDPEDISP), *100 %*
  immer 100 %, *HiDPI* rechnet mit der physischen Pixelgröße.
- Bedingung 10: `ResetGraphics` mit der angefragten Größe schließt einen Resize ab. Abnahme: ein Resize gegen
  Windows mit GFX ohne Neuverbindung.

Ziel Stufe 5:
- Ein RDP-Tab dockt ab wie ein Terminal (Button, Doppelklick, Ziehen aus der Tableiste), in ein Fenster
  `rdp-<n>`, und dockt zurück. Die Sitzung lebt im Backend weiter. Das neue Fenster bekommt sofort ein ganzes
  Bild, denn der Framebuffer liegt in Rust.
- *Multi-Monitor* (`rdp_window_mode = multimon`): Der Tab schickt ein Monitor-Layout mit zwei Monitoren. Jeder
  Monitor zeigt sich in einem eigenen Fenster mit seinem Ausschnitt des Desktops. Hat das System nur einen
  Bildschirm, gilt *Eingepasst* mit einem Hinweis.
- Fensterrechte je Label: Ein `rdp-*`-Fenster erreicht nur die eigene Sitzung und nur die Befehle, die es braucht
  (Muster `terminal-window.json`, `may_reach`).

Nicht-Ziele: kein H.264 (R-1102, `kern-rdp-5`); keine Fensteranordnung über mehr als zwei Monitore; kein
Wiederherstellen von RDP-Sitzungen beim Start (eine RDP-Sitzung braucht Anmeldung); der Standard bleibt der Client
des Systems, bis R-1090 entscheidet.

## Betroffene Komponenten & Dateien

- IronRDP-Fork `AdminCave/IronRDP`: `crates/ironrdp-client/src/rdp.rs` (ResizeQueue, Verarbeitung der
  Grafikausgabe). Neue Revision in `apps/desktop/src-tauri/Cargo.toml` und `Cargo.lock`.
- Rust: `apps/desktop/src-tauri/src/rdp_embedded/{frame_ws.rs,session.rs,mod.rs}`, neues Modul
  `rdp_embedded/window.rs` (Abdocken, Fensterrechte), `main.rs`, `build.rs`, `capabilities.rs`,
  `capabilities/default.json`, neue `capabilities/rdp-window.json`.
- UI: `ui/src/lib/rdp/{renderer.ts,input.ts,frameSocket.ts}` samt Tests, `components/terminal/RdpSession.svelte`,
  `SessionTabs.svelte`, neue `DetachedRdp.svelte`, `lib/stores/terminals.ts`, `main.ts`, `lib/bridge/`,
  `lib/i18n/dictionaries.ts`.
- E2E: `apps/desktop/e2e/test/specs/rdp-embedded.live.js` gegen den xrdp-Container.
- Doku: `docs/admin/index.html`, `docs/en/admin/index.html`, `docs/developer/desktop.html`,
  `docs/en/developer/desktop.html`, `changelog.d/kern-rdp-4.md`.

## Datenmodell / API / Migrationen

- Keine Migration und keine neuen Einstellungen: Der Tab liest die vorhandenen Felder `rdp_scaling_mode`,
  `rdp_window_mode` und `rdp_custom_size`. Die Wahl in der Kopfleiste gilt nur für den Tab.
- WebSocket (lokal, `frame_ws.rs`), neue Client-Nachricht: `{"t":"size","w":…,"h":…,"scale":…}` mit der
  gewünschten Desktop-Größe. Das Backend begrenzt auf die Grenzen von MS-RDPEDISP (200–8192, Breite gerade) und
  verwirft Wiederholungen. Für Multi-Monitor zusätzlich `{"t":"layout",…}` mit zwei Monitoren. Das Bildformat (Kopf
  mit sieben u16) bleibt; die Desktop-Größe im Kopf trägt schon jede Änderung.
- Wiederanmelden: Der Bild-Server lauscht weiter, solange die Sitzung lebt. `rdp_session_attach(session_id)` gibt
  dem anfragenden Fenster einen frischen Token für einen Port. Es meldet sich immer nur ein Client je Bildschirm an;
  wer sich neu anmeldet, löst den bisherigen Client ab. Der erste Client nach dem Wiederanmelden bekommt ein ganzes
  Bild.
- Tauri-Befehle: `rdp_session_start` nimmt die Startgröße und den Skalierungsfaktor. Neu sind `rdp_session_attach`,
  `rdp_detach` und `rdp_dock`, dazu die Fenster-Events `rdp-docked` und `rdp-window-closed`. Main darf alle, ein
  `rdp-*`-Fenster nur die eigene Sitzung.

## Externe Integrationen

- MS-RDPEDISP, DISPLAYCONTROL_MONITOR_LAYOUT_PDU (Grenzen der Monitorgröße, Skalierungsfaktoren):
  https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpedisp/
- MS-RDPEGFX, RDPGFX_RESET_GRAPHICS_PDU (Abschluss eines Resize unter GFX):
  https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpegfx/
- Tauri v2: `WebviewWindowBuilder`, `Window::set_fullscreen`, `available_monitors`, Capabilities je Fenster-Label:
  https://v2.tauri.app/security/capabilities/

Vor der jeweiligen Task lese ich die Abschnitte nach. Verifiziert ist bis dahin nur, was der Spike T4 gemessen hat
(`arch-rdp-embedded.md`, „Resize und Monitor-Layout“).

## Trade-offs & Alternativen

- **Bedingung 10, Patch auf dem Fork statt eigener Sitzungsschleife:** Laut Kevins Notiz an R-1100 geht Bedingung 10
  „unabhängig von IronRDP-PR #2014“. Der kleinste Weg ist eine Änderung in `ironrdp-client` auf dem Fork, der ohnehin
  der Pin ist (Weg (c)): Ein Grafik-Reset mit der Größe des laufenden Resize ruft `completed()`; der Rückfall nach
  3 s bleibt für Server ohne Reset. Eine eigene Sitzungsschleife hieße, rund 2000 Zeilen der Client-Schleife
  nachzubauen. Empfehlung: Patch auf dem Fork mit Test in der IronRDP-Suite. Einen Upstream-PR gibt es erst auf
  Kevins Wort; seine Frage zum Fork ist noch offen.
- **Entprellen in der UI:** Ein `ResizeObserver` mit 300 ms Ruhe vor dem Senden. Das Backend verwirft dieselbe
  Größe noch einmal und nimmt während eines laufenden Resize nur die letzte Anfrage, wie die `ResizeQueue`.
- **Vollbild:** `Window::set_fullscreen` braucht ein Recht für main (`core:window:allow-set-fullscreen`). Die
  Fullscreen-API des DOM hängt in WebKitGTK an Einstellungen des Webviews und ist nicht verifiziert. Empfehlung:
  das Tauri-Recht.
- **Multi-Monitor:** zwei WebSocket-Clients mit je einem Ausschnitt, nicht ein Fenster über beide Bildschirme: Ein
  Fenster über zwei Bildschirme ist je nach System nicht erlaubt. Kosten: Der Bild-Server kennt einen Ausschnitt je
  Client, und die Bestätigungen laufen je Client.

## Risiken & Rollback

- IronRDP #447 (Leistung bricht nach einem Resize auf RemoteFX ein): Die Live-Spec misst den Bildtakt vor und nach
  einem Resize gegen xrdp. Ein Einbruch wird eine Roadmap-Zeile, kein stilles Hinnehmen.
- Mit dem Wiederanmelden wird die lokale Angriffsfläche größer: Der Port bleibt offen, solange die Sitzung lebt.
  Ausgleich: ein Token je Anmeldung, nur einmal gültig, Anmeldefrist und Begrenzung wie bisher, und `security` prüft
  diese Task.
- Rollback je Task per `git revert`. Die Fork-Revision ist additiv; ein Revert der Pin-Task stellt `c39d48e` wieder
  her.

## Doku-Impact

Admin-Doku DE+EN: Abschnitt „RDP in AdminHelper“ (Anzeige, Vollbild, Abdocken, Multi-Monitor; der Satz „fest
1280×720“ entfällt). Entwickler-Doku Desktop DE+EN: WebSocket-Nachrichten `size`, `layout`, Wiederanmelden,
`rdp-*`-Fenster und ihre Rechte. Dazu `changelog.d/kern-rdp-4.md`.

## Offene Fragen

Keine aus Kevins Bereich: Das Verhalten steht im Bauplan, der Weg zu Bedingung 10 in Kevins Notiz an R-1100. Die
Abnahme gegen Windows läuft wie in kern-rdp-1 T9 als Probe im Wegwerf-Repo (Kevin 2026-11-08); Details nur unter
`tasks/private/`.
