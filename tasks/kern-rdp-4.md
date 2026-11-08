# Eingebettetes RDP: Stufe 4 Anzeige, Stufe 5 Fenster — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-4 · Review: pro Task
Spec: docs/features/kern-rdp-4.md (Roadmap R-1100, R-1101)
Heavy: linux-full — Desktop-Journeys: Resize, Abdocken und Multi-Monitor des RDP-Tabs gegen den xrdp-Container (Live-Spec) laufen im Sammellauf; neue Fensterrechte und die IronRDP-Revision; Windows über die Windows-CI-Jobs
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1100: ResetGraphics schließt einen Resize ab (Fork-Revision)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @61b4781ce 2026-11-08T20:37:53+01:00
Review: approve (.ah-out/review/kern-rdp-4/T1.verdict.json)
Änderung: Auf dem Fork `AdminCave/IronRDP` ein Commit über `c39d48e`: Meldet `ironrdp-session` einen Grafik-Reset (`reset`) mit der Größe des laufenden Resize, ruft `ironrdp-client` `ResizeQueue::completed()` auf. Ohne Reset bleibt der Rückfall nach 3 s. Test in der IronRDP-Suite: Reset mit passender Größe → keine Neuverbindung; abweichende Größe → weiter wartend; Gegenprobe ohne den Patch rot. Der Desktop pinnt die neue Revision für alle `ironrdp-*`, `cargo tree -i aws-lc-rs` bleibt leer. Kein Upstream-PR ohne Kevins Wort.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T12

### T2 — R-1100: Startgröße, Skalierung und Resize im Backend  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @05f1a4065 2026-11-08T20:56:07+01:00
Review: approve (.ah-out/review/kern-rdp-4/T2.verdict.json)
Änderung: `rdp_session_start` nimmt Breite, Höhe und Skalierungsfaktor, statt fest 1280×720 (`session.rs:42-43`) zu verbinden. Die WebSocket-Nachricht `{"t":"size",…}` wird zu `Input::Size`, auf die Grenzen von MS-RDPEDISP begrenzt (200–8192, Breite gerade, Faktor 100–500), Wiederholungen werden verworfen, dann geht `RdpInputEvent::Resize` an den Client. `DisplayResizeFallback` verbindet mit der neuen Größe neu, ohne `failed` zu melden. Tests: Begrenzung, Verwerfen, Weitergabe; die Bildgröße im Kopf folgt dem Reset.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T12
Abhängt von: T1

### T3 — R-1100: Anzeige-Modi im Tab (Eingepasst, Fest mit Zoom, Skalierung)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/rdp/renderer.ts, apps/desktop/ui/src/lib/rdp/renderer.test.ts, apps/desktop/ui/src/lib/rdp/input.ts, apps/desktop/ui/src/lib/rdp/input.test.ts, apps/desktop/ui/src/lib/rdp/frameSocket.ts, apps/desktop/ui/src/lib/rdp/frameSocket.test.ts, apps/desktop/ui/src/components/terminal/RdpSession.svelte, apps/desktop/ui/src/components/terminal/RdpSession.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Der Tab startet mit `rdp_window_mode`, `rdp_scaling_mode` und `rdp_custom_size` und lässt sie in der Kopfleiste für diesen Tab wechseln. *Eingepasst* misst den Tab mit einem `ResizeObserver` und schickt nach 300 ms Ruhe `size`. *Fest* zeigt die feste Größe mit Zoom 25–200 %, *1:1* und *Einpassen*, mit Bildlauf. Die Skalierung bestimmt Faktor und physische Größe aus `devicePixelRatio`. Die Abbildung der Zeigerkoordinaten folgt Zoom und Bildlauf. Tests: Entprellen, Zoomgrenzen, Koordinaten bei Zoom und Bildlauf, Startwerte aus den Einstellungen. Zwölf Dateien, weil Bild, Eingabe und Tab zusammen eine Ansicht bilden.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T2

### T4 — R-1100: Vollbild mit Leiste  [ ]
Komponente: desktop · Dateien: apps/desktop/src-tauri/capabilities/default.json, apps/desktop/src-tauri/src/capabilities.rs, apps/desktop/ui/src/components/terminal/RdpSession.svelte, apps/desktop/ui/src/components/terminal/RdpSession.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: *Vollbild* setzt das Fenster per `setFullscreen` in den Vollbildmodus (Recht `core:window:allow-set-fullscreen` für main, Test in `capabilities.rs`). Eine Leiste blendet am oberen Rand beim Darüberfahren ein und führt mit Trennen, Strg+Alt+Entf und *Vollbild verlassen* zurück. Die Auflösung folgt dem Bildschirm, wie bei *Eingepasst*. Esc bleibt beim Server; zurück geht es über die Leiste oder Strg+Alt+Pos1 und dann F11. Tests: Ein- und Ausstieg, die Leiste, das Recht.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T12
Abhängt von: T3

### T5 — R-1100: Live-Spec Resize und Abnahme gegen Windows  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/rdp-embedded.live.js
Änderung: Die Live-Spec ändert die Fenstergröße gegen den xrdp-Container. Erwartet: Die Fußzeile meldet die neue Auflösung, eine Phase `reconnecting` kommt nicht, und der Bildtakt vor und nach dem Resize wird festgehalten (IronRDP #447). *Fest* mit 50 % und 1:1 trifft mit einem Klick dieselbe Desktop-Koordinate. Die Abnahme von Bedingung 10 gegen Windows mit GFX läuft als Probe im Wegwerf-Repo, wie kern-rdp-1 T9. Befund unter `tasks/private/spikes/arch-rdp-embedded/`, im Ledger nur das Ergebnis.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T12
Abhängt von: T4

### T6 — R-1101: Wiederanmelden am Bild-Server  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Änderung: Der Bild-Server lauscht weiter, solange die Sitzung lebt (`frame_ws.rs:155`). Geht ein Client weg, endet die Sitzung nicht mehr, nur `close` oder `rdp_session_stop` beenden sie. `rdp_session_attach(session_id)` gibt einen frischen, einmal gültigen Token aus, der alte verfällt. Eine neue Anmeldung löst den bisherigen Client ab, und der neue Client bekommt zuerst ein ganzes Bild. Anmeldefrist und `MAX_PENDING_LOGINS` bleiben. Tests: Anmelden, Weggehen, wieder Anmelden mit ganzem Bild; ein alter Token wird abgewiesen; Ablösung; die Sitzung lebt ohne Client weiter. Risikopfad lokale Authentisierung: dazu `security`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T12

### T7 — R-1101: Abdocken im Backend, Fensterrechte je Label  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/window.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/src/capabilities.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/src-tauri/capabilities/rdp-window.json
Änderung: Das neue Modul `window.rs` (SPDX-Header) baut `rdp_detach(session_id, title)` und `rdp_dock` nach dem Muster von `terminal_detach` und `terminal_dock` (`commands.rs:861`). Das Fenster `rdp-<n>` öffnet die Route `#/detached-rdp/<id>`; Schließen über die Titelleiste meldet `rdp-window-closed` an main. Ein `may_reach` für RDP lässt ein `rdp-*`-Fenster nur die eigene Sitzung erreichen. `rdp-window.json` (neu, kein SPDX in JSON) erlaubt nur `rdp_session_attach`, `rdp_session_stop`, `rdp_dock`, Einstellungen lesen und Events. Tests: Label-Abbildung, `may_reach`, Rechte-Inventar in `capabilities.rs`. Risikopfad Rechte: dazu `security`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- capabilities rdp_embedded
Doku: → T12
Abhängt von: T6

### T8 — R-1101: Abdocken in der UI  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/DetachedRdp.svelte, apps/desktop/ui/src/components/terminal/DetachedRdp.test.ts, apps/desktop/ui/src/components/terminal/SessionTabs.svelte, apps/desktop/ui/src/components/terminal/SessionTabs.test.ts, apps/desktop/ui/src/components/terminal/RdpSession.svelte, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/main.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Ein RDP-Tab dockt ab wie ein Terminal (Button, Doppelklick, Ziehen). Main hält den Tab als abgedockt und trennt seinen WebSocket. `DetachedRdp.svelte` (neu, SPDX) holt per `rdp_session_attach` Port und Token und zeigt `RdpSession` ohne Tableiste. *Andocken* und das Schließen des Fensters bringen den Tab zurück, der sich neu anmeldet. Tests: Abdocken, Andocken, Fenster geschlossen, die Route, das IPC-Inventar. Elf Dateien: Muster und Umfang wie bei R-1070.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T7

### T9 — R-1101: Multi-Monitor im Backend (Layout, Ausschnitt je Client)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/rdp_embedded/window.rs
Änderung: Die Nachricht `{"t":"layout",…}` mit zwei Monitoren (je Größe, Lage, Faktor, begrenzt wie `size`) wird zu `RdpInputEvent::MonitorLayout`. Der Bild-Server nimmt je Bildschirm einen Client (Bildschirm 0 und 1, je ein Token aus `rdp_session_attach`) und schickt jedem nur seinen Ausschnitt, mit eigener Bestätigung. Die Mauskoordinaten eines Clients werden um die Lage seines Monitors verschoben. `rdp_detach` öffnet für Bildschirm 1 das zweite Fenster auf dem zweiten Monitor des Systems. Tests: Ausschnitt, Bestätigungen je Client, Verschiebung, Begrenzung.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T12
Abhängt von: T7

### T10 — R-1101: Multi-Monitor in der UI  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/RdpSession.svelte, apps/desktop/ui/src/components/terminal/RdpSession.test.ts, apps/desktop/ui/src/components/terminal/DetachedRdp.svelte, apps/desktop/ui/src/components/terminal/DetachedRdp.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: *Multi-Monitor* liest die Bildschirme des Systems. Bei zwei oder mehr zeigt der Tab Monitor 0, ein zweites Fenster Monitor 1, und das Layout folgt deren Größe und Skalierung. Bei einem Bildschirm gilt *Eingepasst* mit dem Hinweis „nur ein Bildschirm“. Schließen des zweiten Fensters schaltet auf einen Monitor zurück. Tests: zwei Bildschirme, einer, Schließen des zweiten.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T12
Abhängt von: T8, T9

### T11 — R-1101: Live-Spec Abdocken und Multi-Monitor  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/rdp-embedded.live.js
Änderung: Gegen den xrdp-Container: Abdocken zeigt das Bild im neuen Fenster ohne `reconnecting`, Andocken holt es zurück, die Sitzung ist dieselbe (Verbindungsinfo). Multi-Monitor nur, wenn der Webdriver-Treiber zwei Bildschirme sieht, sonst meldet der Test den Hinweis-Pfad. Zwei Monitore auf der VM sind nicht verifiziert; das Ergebnis steht im Ledger.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T12
Abhängt von: T8, T10

### T12 — Doku Stufe 4 und 5 (DE+EN), Changelog  [ ]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-4.md
Änderung: Admin-Doku „RDP in AdminHelper“: Anzeige-Modi, Skalierung, Vollbild, Abdocken, Multi-Monitor; der Satz „fest 1280×720“ entfällt. Entwickler-Doku: Nachrichten `size` und `layout`, Wiederanmelden, `rdp-*`-Fenster und ihre Rechte, die Fork-Revision. `changelog.d/kern-rdp-4.md` ohne Umlaute.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-4.md
Task-Review: am Ende

## Entscheidungen
- 2026-11-08: Bedingung 10 per Commit auf dem Fork statt eigener Sitzungsschleife (Kevins Notiz an R-1100: „unabhängig von IronRDP-PR #2014“; Fork = Pin nach Weg (c)); kein Upstream-PR ohne Kevins Wort.
- 2026-11-08: Keine neuen Einstellungen: Der Tab nimmt `rdp_window_mode`, `rdp_scaling_mode` und `rdp_custom_size` als Startwerte, die Kopfleiste ändert sie nur für den Tab (wie das Leistungsprofil).
- 2026-11-08: Multi-Monitor als zwei WebSocket-Clients mit Ausschnitt, nicht ein Fenster über beide Bildschirme.
- 2026-11-08: Ein Resize, der nur den Skalierungsfaktor ändert, gilt im Fork sofort als abgeschlossen (die Bildgröße bleibt); angenommen (Prüfer-Nit T1).
- 2026-11-08 (T2): Der Live-Test `xrdp_live_session` überspringt in der Ruhefrist QUIET Textnachrichten (Stats, jede Sekunde); nur ein Bild ohne Quittung ist ein Fehler. Vorher fiel er, sobald Stats in die 2 s fielen (lokal rot, passt zu R-1195); die Prüfung bleibt für Bilder gleich streng.
