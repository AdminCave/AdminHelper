# kern-desktop-6: Desktop-Zuverlässigkeit (Sitzung, Zertifikat, Tunnel, RDP, SFTP, Ping, Feed)

Roadmap: R-1689, R-1691, R-1707, R-1708, R-1709, R-1710, R-1711 (alle von Kevin am 2026-11-27 angenommen).

## Problem je Zeile

- **R-1709 (BUG):** Jeder Fehlschlag der Sitzungs-Erneuerung beendet die Sitzung, auch ein Verbindungsfehler oder
  ein 502. Desktop: `send_renewing` (`apps/desktop/src-tauri/src/session.rs:276`) leert den Slot bei jedem `Err` aus
  `try_refresh` (`auth.rs:133`). Web: `tryRefresh` (`apps/web/src/lib/api/client.ts:101`) liefert bei `!res.ok` und
  bei jeder Exception `false`, und `request` ruft dann `onAuthFailure` (`client.ts:160`).
- **R-1689 (BUG):** Nach rund 47 Tagen Pause ist das Geräte-Zertifikat abgelaufen. nginx antwortet mit 400 und der
  Seite „The SSL certificate error“ (Fehler 495, `ngx_http_error_495_page` in nginx
  `src/http/ngx_http_special_response.c`). `login_failure` (`auth.rs:48`) kennt nur die Seite zu 496, also zeigt der
  Login „HTTP 400“, und der dokumentierte Ausweg liegt hinter dem Login.
- **R-1691 (BUG):** `tunnel_status` meldet `running = child.is_some()` (`frpc.rs:1095`). Mit `loginFailExit = false`
  (`frpc.rs:622`) läuft frpc weiter, auch wenn frps unerreichbar ist oder den Login ablehnt. `tunnel.ts:246` macht
  daraus „verbunden“.
- **R-1707 (BUG):** Beim RDP-Start über xfreerdp mit Passwort setzt der Timer-Thread `emitted` per `swap`
  (`connection/rdp.rs:553`). Der Exit-Thread liest es nur (`:569`), darum melden beide Threads.
- **R-1708 (BUG):** Der SFTP-Upload (`sftp.rs:404`) schreibt direkt auf den Zielnamen. Bricht die Verbindung ab,
  ist die alte Datei abgeschnitten oder es bleibt eine Teil-Datei unter dem endgültigen Namen liegen.
- **R-1710 (FEAT):** Die Ping-Spalte baut jede Minute für jeden gelisteten Host eine TCP-Verbindung auf
  (`stores/connections.ts:282`, `pages/Connections.svelte:136`), und es gibt keinen Schalter dafür.
- **R-1711 (REF):** Der Feed lädt bei jedem SSE-Frame ungebündelt neu (`stores/notifications.ts:368` → `loadFeed`
  `:69`). Eine ältere Antwort kann dabei die neuere Liste überschreiben.

## Ziel

- **R-1709** (Kevin 2026-11-27):
  - Ein Transportfehler sowie die Antworten 502, 503 und 504 auf `/api/auth/refresh` beenden die Sitzung nicht. Der
    Aufruf scheitert mit einem Verbindungsfehler, und das nächste 401 versucht die Erneuerung erneut.
  - 400, 401, 500 und jede andere Antwort beenden die Sitzung weiter.
  - Die eigene 30-s-Frist der Erneuerung (Desktop) und ein Timeout gelten weiter als Ende, wie es heute
    dokumentiert ist: Der Server kann das Refresh-Token schon rotiert haben, siehe Kommentar in `session.rs`.
    Desktop und Web verhalten sich hier gleich.
- **R-1689:**
  - Vor dem Login prüft der Desktop das Leaf lokal. Ist es abgelaufen, sendet er nichts und liefert den neuen Code
    `ERR_DEVICE_CERT_INVALID`.
  - `login_failure` erkennt die 495-Seite und liefert denselben Code.
  - Der Login-Screen zeigt dazu einen Hinweis mit dem Ausweg, den es schon für `ERR_CERT_REVOKED` gibt: Identität
    zurücksetzen, dann mit Token neu registrieren.
- **R-1691:**
  - `TunnelStatus` bekommt den Login-Zustand von frpc. Er wird aus dessen Logzeilen gelesen (frp v0.72.0,
    `client/service.go`):
    - `login to server success` → angemeldet
    - `try to connect to server...` → verbindet
    - `connect to server error` → kein Kontakt
  - Die UI unterscheidet „verbunden“ von „kein Kontakt zum Tunnel-Server“.
- **R-1707:** Der Exit-Thread entscheidet einmal (`swap`), nach dem Ende der Leser-Threads, wie es
  `wait_interactive` (`rdp.rs:693`) tut. Es gibt höchstens ein Ereignis je Verbindungsversuch.
- **R-1708:**
  - Der Upload schreibt nach `.<name>.ah-part` im Zielordner, benennt danach um und entfernt die Teil-Datei bei einem
    Fehler.
  - Für das Überschreiben nimmt er `posix-rename@openssh.com`, falls russh-sftp das kann. Sonst entfernt er zuerst
    das Ziel und benennt dann um. Das ist nicht atomar, aber der alte Inhalt bleibt bis nach dem vollständigen
    Upload erhalten.
- **R-1710** (Kevin 2026-11-27): Die Einstellung „Erreichbarkeit prüfen“ gilt je Workspace (`workspace.json`) und
  steht standardmäßig auf an. Ist sie aus, startet die Seite Verbindungen keine Probe, und die Spalte bleibt leer.
- **R-1711:** Es läuft höchstens ein Feed-Abruf zur Zeit, mit höchstens einem Nachlauf, wie `refreshNow()` in
  `tunnel.ts`.

**Nicht-Ziele:**
- Ein Schalter je Verbindung (R-1710).
- Automatische Erneuerung des Zertifikats vor dem Login (R-1689): Ein abgelaufenes Leaf kann sich nicht selbst
  erneuern.
- Die Auswertung von `/api/status` in frpc: Diese Antwort zeigt Proxies, aber keinen Login-Zustand.

## Komponenten und Dateien

| Bereich | Dateien |
|---|---|
| desktop-rs | `session.rs`, `auth.rs`, `enrollment.rs`, `error.rs`, `frpc.rs`, `connection/rdp.rs`, `sftp.rs`, `models.rs`, `storage.rs` |
| desktop-ui | `components/Login.svelte`, `lib/i18n/dictionaries.ts`, `lib/stores/tunnel.ts`, die Tunnel-Anzeige, `lib/stores/connections.ts`, `pages/Connections.svelte`, `components/settings/WorkspaceSection.svelte`, `lib/stores/notifications.ts`, `lib/bridge/types.ts` |
| web | `src/lib/api/client.ts`, `client.test.ts` |

## API und Datenmodell

- Neuer Fehlercode `ERR_DEVICE_CERT_INVALID` (Tauri-IPC, `error.rs`).
- `TunnelStatus` bekommt ein Feld für den Login-Zustand. Der IPC-Typ in `bridge/types.ts` zieht mit.
- In `Settings` und im Meta von `workspace.json` kommt `probeReachability: bool` dazu, mit Default `true`. Ältere
  Dateien ohne das Feld lesen sich als an.
- Keine Server-API und keine Migration.

## Externe Formate

- frp v0.72.0, `client/service.go:369-389`: die Logzeilen des Login-Loops. Gelesen an der Quelle (Tag v0.72.0).
  Die Zeilen sind kein dokumentierter Vertrag, deshalb pinnt ein Test die Zeilen.
- nginx `ngx_http_special_response.c`: die Seiten zu 495 und 496, gelesen am master-Stand.
- SFTP: Rename aus v3 überschreibt bei OpenSSH kein bestehendes Ziel; `posix-rename@openssh.com` ist die Extension
  von OpenSSH (PROTOCOL). Ob russh-sftp 3.0.1 sie anbietet, prüft T8.

## Trade-offs

- **R-1691:** Logzeilen gegenüber einer Bind-Probe am Visitor-Port. Die Probe sagt nichts über den Login; die
  Logzeilen hängen an der frp-Version. Empfehlung: Logzeilen. Die Version ist gepinnt (CI-Job `frp-consistency`),
  und ein Test hält die Zeilen fest.
- **R-1709:** Ein Transportfehler nach dem Senden kann ein schon rotiertes Token zurücklassen. Dann scheitert die
  nächste Erneuerung mit 401, und die Sitzung endet dort. Dieses Restrisiko hat Kevin hingenommen.

## Risiken und Rollback

- Jede Task ist ein eigener Commit und lässt sich einzeln zurücknehmen.
- Auth-Pfade (`auth.rs`, `session.rs`, `enrollment.rs`, `client.ts`) sind Risikopfade, deshalb prüft `security` je
  Task.

## Doku-Impact

- `docs/developer/desktop.html` und das EN-Gegenstück: Erneuerung, Tunnel-Zustand, Upload, Erreichbarkeit.
- `docs/admin/troubleshooting.html` und das EN-Gegenstück: abgelaufenes Geräte-Zertifikat, Tunnel ohne Kontakt.
- Die Doku-Seite zur Ping-Spalte.
- `changelog.d/kern-desktop-6.md`.

## Offene Fragen

Keine. Kevins Antworten vom 2026-11-27 stehen in den Notizen der Zeilen.
