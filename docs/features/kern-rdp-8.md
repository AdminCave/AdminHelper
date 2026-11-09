# Eingebettetes RDP: Sitzungsende ohne Anzeige, Umleitungen, TLS-Schlüssel (kern-rdp-8)

Roadmap: R-1199, R-1145 (beide vor dem Release 0.47.0, R-1110). Details nur in `tasks/private/`.

## Problem / Motivation

- **R-1199:** Seit R-1101 überlebt eine eingebettete RDP-Sitzung ihren WebSocket-Client; sie endet nur durch
  `rdp_session_stop`, `{"t":"close"}` oder Server bzw. Netz. Startet oder lädt `main` neu, beendet
  `terminal_close_all` alle Sitzungen (kern-rdp-4). Geht ein Stopp aus einem anderen Grund verloren, etwa weil ein
  abgedocktes Fenster ohne `CloseRequested` verschwindet, bleibt die Sitzung angemeldet, ohne dass eine Ansicht
  sie zeigt oder beenden kann.
- **R-1145:** IronRDP folgt Server-Umleitungen selbst. Unsere Sitzung bricht beim Ereignis `ServerRedirected` ab,
  doch die Umstellung auf das neue Ziel ist dann schon angestoßen. Das soll im Client selbst abschaltbar sein,
  belegt durch einen Test. Außerdem schreibt IronRDPs rustls-Konfiguration TLS-Sitzungsschlüssel in die Datei,
  die `SSLKEYLOGFILE` nennt, falls die Variable in der Umgebung der App steht.

## Ziel & Nicht-Ziele

Ziel:
- Eine Sitzung, an der 60 s lang kein Client hängt, endet wie nach `rdp_session_stop`. Abgedockte Fenster und
  verborgene Tabs halten ihren Client: inaktive Tabs bleiben gemountet (`AppShell.svelte`), abdocken übergibt in
  Sekunden.
- Der Client folgt keiner Server-Umleitung: Mit dem neuen Schalter des Forks endet der Verbindungsaufbau mit
  einem Fehler, bevor eine Verbindung zum Umleitungsziel entsteht.
- Die App startet ohne `SSLKEYLOGFILE` in ihrer Umgebung; keine TLS-Verbindung der App schreibt Schlüssel.

Nicht-Ziele: eine Liste bekannter Sitzungen im UI, ein Wiederverbinden-Knopf, TrustAll ändern, Upstream-PR (der
Fork-Commit kann später hochgehen).

## Betroffene Komponenten & Dateien

- **desktop-rs:**
  - `apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs`: `serve` zählt die Zeit ohne Client und endet nach
    `NO_CLIENT_DEADLINE` (60 s), einstellbar für Tests wie `login_deadline`.
  - Fork `AdminCave/IronRDP`, Branch `adminhelper-pin`: ein Commit, der in `ironrdp-client` einen Schalter
    `follow_server_redirection` (Standard an) einführt; aus gibt `follow_server_redirection` einen Fehler zurück,
    ohne `config.destination` zu ändern. Test im Fork.
  - `apps/desktop/src-tauri/Cargo.toml`, `Cargo.lock`: alle `ironrdp-*` auf die neue Fork-Revision.
  - `apps/desktop/src-tauri/src/rdp_embedded/session.rs`: Schalter aus; Test auf die Konfiguration.
  - `apps/desktop/src-tauri/src/main.rs`: `SSLKEYLOGFILE` vor allen Threads aus der Umgebung nehmen.
- **Doku:** `docs/developer/desktop.html` und EN (Sitzung ohne Client, Umleitung, `SSLKEYLOGFILE`),
  `changelog.d/kern-rdp-8.md`.

## Datenmodell / API / Migrationen

Keine. Der Tauri-Vertrag bleibt; eine Sitzung ohne Client meldet ihr Ende wie heute über `rdp-session`.

## Externe Integrationen

- IronRDP (Fork, Revision in `Cargo.toml`): `ironrdp-client/src/rdp.rs` `follow_server_redirection`,
  `ironrdp-tls/src/rustls_verifier.rs` (`config.key_log = KeyLogFile`).
- rustls `KeyLogFile` liest `SSLKEYLOGFILE` beim Anlegen (https://docs.rs/rustls/latest/rustls/struct.KeyLogFile.html).

## Trade-offs & Alternativen

- **Frist statt Liste:** Die Roadmap-Zeile nennt beides. Eine Liste der Sitzungen im UI braucht neue Ansicht und
  Befehle; die Frist schließt alle Wege, auf denen ein Stopp verloren geht, mit wenigen Zeilen. 60 s lassen dem
  Abdocken unter Last genug Zeit.
- **Umgebungsvariable entfernen statt Fork-Schalter für den Schlüssel-Log:** wirkt für jede TLS-Verbindung der
  App und braucht keinen zweiten Fork-Eingriff.
- **Fork-Schalter statt Abbruch beim Ereignis:** Nur der Client selbst kann das Umstellen verhindern; der Abbruch
  beim Ereignis bleibt als zweite Linie.

## Risiken & Rollback

- Eine Sitzung, deren Socket durch einen Fehler schließt, während der Tab bleibt, endet nach 60 s. Heute bleibt
  sie ohne Bild stehen; das Ende ist dort ehrlicher.
- Fork-Revision: alle `ironrdp-*` müssen dieselbe Revision tragen, sonst baut Cargo zwei Kopien.
- Rollback: Revert der Task-Commits; die alte Fork-Revision bleibt im Fork-Branch erreichbar.

## Doku-Impact

`docs/developer/desktop.html` DE+EN: Absatz zum Bild-Server (Sitzung ohne Client) und Liste zum Zertifikats-Callback
(Umleitung, `SSLKEYLOGFILE`); Changelog.

## Offene Fragen

Keine. Die Frist folgt dem Weg aus der Roadmap-Zeile R-1199.
