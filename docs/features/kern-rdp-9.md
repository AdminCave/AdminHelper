# Eingebettetes RDP: Live-Test, OpenH264-Download, Passwort beim Neu verbinden (kern-rdp-9)

Roadmap: R-1258, R-1195, R-1201, R-1207, R-1196 (alle vor dem Release 0.47.0, R-1110).

Nicht im Zug:
- R-1152 (`accept()`-Fehler beendet den Bild-WebSocket) ist auf `main` behoben. Seit kern-rdp-4 T6 (d2879d51a, #420)
  hört `serve` nach einem Fehler von `accept()` weiter zu (`frame_ws.rs:244-253`, `ACCEPT_BACKOFF`). Die Zeile wird
  geschlossen.
- R-1198 (`session_info` löst die Verbindung doppelt auf) überschneidet sich mit `feature/arch-namen`, das die
  `session_info`-Tests in `rdp_embedded/mod.rs` ändert. Die Zeile geht in den nächsten Zug (`tasks/kern-rdp-10.md`).

## Problem / Motivation

- **R-1258:** `rdp_embedded::session::tests::xrdp_live_session` ist im Sammellauf flaky (2026-11-09-0959,
  -1705 und -2117). `next_frame` erwartet ein Bild und lässt nur Ping und Pong durch. Kommt die Statistik
  `{"t":"stats",…}`, die `frame_ws` jede Sekunde als Text schickt, vor dem ersten Bild, panict der Test mit
  „expected a picture, got … Text“.
- **R-1195:** Im Sammellauf 2026-11-08-1600 (main@d37699f5e) meldete der Live-Test nach dem Stopp `Reconnecting`
  statt `Disconnected(Closed)`. Eine automatische Wiederverbindung von IronRDP (`AutoReconnecting`) kam vor dem
  Stopp an und stand vorn in der Phasen-Schlange. Seit 494a067b6 lässt der Test beim Ändern der Größe
  `Reconnecting` und `Connected` zu, aber nur in den Phasen, die bis dahin angekommen sind. Die Prüfungen danach
  sehen eine spätere Wiederverbindung weiter als Fehler.
- **R-1201:** `openh264::ensure` lädt bis zu 15 s. Schaltet der Nutzer H.264 in der Zwischenzeit aus, löscht
  `openh264_remove` den Ordner, und `install` legt ihn danach mit der Bibliothek wieder an. Die Doku sagt dagegen:
  „Aus löscht die Bibliothek beim Speichern wieder.“ Außerdem schreiben zwei gleichzeitige Downloads desselben
  Prozesses (zwei Sitzungen starten zugleich) in dieselbe `.part-<pid>`-Datei.
- **R-1207:** `mod openh264` gilt für `cfg(target_os = "linux")`. Auch auf aarch64 lädt die App deshalb das
  linux64-Binary von Cisco. Der Hash passt, `dlopen` scheitert, und H.264 bleibt ohne Hinweis aus.
- **R-1196:** Scheitert die Anmeldung einer RDP-Sitzung (Phase `failed`, Code `auth`), schickt „Neu verbinden“
  dasselbe Passwort noch einmal, das getippte oder das gespeicherte. Es scheitert erneut.

## Ziel & Nicht-Ziele

Ziel:
- Der Live-Test überspringt Text-Nachrichten, wo er ein Bild erwartet. Wiederverbindungen vor dem Stopp lässt er zu,
  wie schon beim Ändern der Größe; das Ende muss trotzdem `Disconnected(Closed)` sein.
- Nach „aus“ legt kein laufender Download die Bibliothek wieder an. Gleichzeitige Downloads in einem Prozess
  schreiben nacheinander.
- Auf einer anderen Architektur als x86_64 lädt die App nichts. Sie meldet einmal je Sitzung im Log, dass H.264
  dort fehlt. Die Doku nennt die Grenze.
- Nach einem `auth`-Fehler fragt „Neu verbinden“ das Passwort neu ab, mit demselben Dialog wie beim ersten Start.
  Abbrechen startet nichts.

Nicht-Ziele:
- ein eigenes Cisco-Binary für arm64 pinnen: Der Rundlauf-Test kann es auf keiner unserer Maschinen laden.
- eine prozessübergreifende Sperre für zwei App-Instanzen.
- den Schalter im UI auf ARM ausblenden.

## Betroffene Komponenten & Dateien

- **desktop-rs:**
  - `apps/desktop/src-tauri/src/rdp_embedded/session.rs`, nur der Testteil (`next_frame` und das Ende von
    `xrdp_live_session`).
  - `apps/desktop/src-tauri/src/rdp_embedded/openh264.rs`, nämlich:
    - eine prozessweite Sperre mit Generationszähler: `remove` erhöht ihn, `install` schreibt nur bei unveränderter
      Generation;
    - eine Architekturprüfung in `ensure`.
  - `mod.rs` bleibt unverändert (Überschneidung mit `feature/arch-namen`).
- **desktop-ui:**
  - `apps/desktop/ui/src/lib/stores/terminals.ts`: Der Lauf merkt sich, ob die letzte Sitzung mit `auth` endete.
    `reconnectRdp` bekommt optional ein Passwort.
  - `apps/desktop/ui/src/lib/stores/connectFlow.ts`: neu `reconnectRdpTab(key)`. Nach einem `auth`-Fehler zeigt
    es den Passwort-Dialog wie `tabPassword`, aber ohne den gespeicherten Weg; sonst startet es `reconnectRdp(key)`.
  - `apps/desktop/ui/src/components/terminal/RdpSession.svelte`: Beide Knöpfe „Neu verbinden“ rufen
    `reconnectRdpTab`.
  - Tests in `terminals.test.ts`, `connectFlow.test.ts` und `RdpSession.test.ts`.
- **Doku:**
  - `docs/admin/index.html` und EN: H.264 nur auf x86_64, „aus“ gewinnt gegen einen laufenden Download, Passwort
    beim Neu verbinden;
  - `docs/developer/desktop.html` und EN;
  - `changelog.d/kern-rdp-9.md`.

## Datenmodell / API / Migrationen

Keine. Der Tauri-Vertrag bleibt (`rdp_session_start` nimmt schon ein optionales Passwort).

## Externe Integrationen

- Cisco OpenH264 2.7.0: Die gepinnte Datei `libopenh264-2.7.0-linux64.8.so` ist laut Name das x86_64-Binary
  (`linux64`). Ob Cisco für 2.7.0 ein arm64-Binary anbietet, ist nicht verifiziert; dieser Zug pinnt keines.

## Trade-offs & Alternativen

- **R-1207: abschalten oder arm64 pinnen.** Die Zeile lässt beides offen. Ein Pin, den kein Test lädt, verspricht
  mehr, als wir prüfen können. Deshalb: abschalten mit Log-Zeile und Doku; ein arm64-Pin kann als eigene Zeile
  folgen.
- **R-1201: Sperre im Prozess statt Abbruch des Downloads.** Der Download darf zu Ende laufen. Nur das Schreiben
  prüft unter der Sperre die Generation. Das ist einfacher als einen laufenden Request abzubrechen und
  schließt die Lücke ebenso. Zwei App-Instanzen teilen sich die Sperre nicht; das bleibt außerhalb des Zugs.
- **R-1196: Abfrage in `connectFlow` statt in `terminals`.** Der Passwort-Dialog und das Speichern im Keyring
  liegen in `connectFlow`. `terminals` bekommt nur das Ergebnis, so entsteht kein Import-Zyklus.
- **R-1195: Wiederverbindungen zulassen statt Ursache beheben.** IronRDP verbindet auf Server-Wunsch selbst neu
  (`AutoReconnecting`). Das ist gewolltes Verhalten, kein Fehler des Stopps. Der Test prüft weiter, dass der Stopp
  mit `Disconnected(Closed)` endet und danach keine Bilder kommen.

## Risiken & Rollback

- Läuft `openh264::remove` gegen ein Schreiben unter der Sperre, wartet es höchstens so lange, wie das Schreiben
  von 1,7 MB dauert. Rollback: Revert der Task.
- Ein Nutzer auf ARM-Linux verliert nichts, was heute ginge: H.264 lief dort nie.

## Doku-Impact

Admin-Doku DE und EN (H.264-Absatz in `admin/index.html`), Entwickler-Doku DE und EN (`developer/desktop.html`,
OpenH264 und Neu verbinden) und der CHANGELOG.

## Offene Fragen

Keine: Die Zeilen nennen das gewollte Verhalten. Für R-1207 wählt der Plan die Abschaltung, die die Zeile als
Alternative nennt.
