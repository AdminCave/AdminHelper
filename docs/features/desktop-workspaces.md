<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Workspaces — mehrere Server, Sync- und Lokal-Arbeitsbereiche gleichzeitig

Roadmap R-0431 (FEAT), dazu R-0524 (Doku) · Phase 2 und 3 des Workspace-Konzepts (Kevin 2026-10-16: ein OS-Prozess
je Workspace, Launcher mit Picker, strikt getrennt; der Spike „zwei Prozesse ohne GTK-App-ID“ ist erledigt und
trägt). Baut auf R-0430 (Session im Rust-Speicher, Portkarte) auf und wird erst nach dessen Merge gebaut.
Entscheidungen zu den offenen Fragen: Kevin 2026-10-19. Zeilenangaben gelten für
`feature/desktop-session-ports@ee47d213` (R-0430 fertig, enthält `main` mit R-0429); die Bau-Session greppt sie neu.

## Problem / Motivation

Der Desktop kennt genau einen Arbeitsbereich: einen Modus (`Settings.mode`, `models.rs:17`, `:89`), eine
Server-URL, eine Geräte-Identität im Keyring (`enroll|key|cert|ca|replaces`, `enrollment.rs:36-42`), einen Satz
Dateien im App-Datenordner (`storage.rs:15-57`, `frpc.rs:640-660`). Wer zwei AdminHelper-Installationen betreut
(etwa zwei Kunden), muss abmelden, die URL umstellen und das Gerät neu registrieren — die Identität der einen
Installation gilt bei der anderen nicht, ein zweiter Login überschreibt den ersten. Sync- und Lokal-Verbindungen
neben einem Server lassen sich nur über den Moduswechsel erreichen, der die Sitzung beendet
(`settings.ts:79-156`). Ein zweiter Programmstart holt heute nur das laufende Fenster nach vorn
(`tauri-plugin-single-instance`, `main.rs:56-68`); zwei Arbeitsbereiche nebeneinander gibt es nicht.

## Ziel & Nicht-Ziele

**Ziel:**
- Mehrere **Workspaces** gleichzeitig aktiv (angemeldet, Tunnel, Benachrichtigungen). Ein Workspace hat eine feste
  **Art** (Server, Sync, Lokal; ersetzt den Moduswechsel), einen Namen und eine Farbe aus einer festen Palette;
  mehrere Workspaces je Art sind erlaubt.
- **Ein Fenster = ein Workspace = ein OS-Prozess:** `adminhelper` ist der **Launcher** (Picker; Anlegen,
  Bearbeiten, Löschen), `adminhelper --workspace <id>` der Workspace-Prozess. Das Single-Instance-Plugin gilt nur
  noch im Launcher; derselbe Workspace läuft nie in zwei Prozessen (Lock je Workspace). Der Launcher schließt sich,
  sobald der geöffnete Workspace läuft; „Workspaces…“ holt ihn zurück.
- **Strikt getrennt:** eigener Datenordner, eigenes Keyring-Präfix (Identität, RDP-Passwörter), eigene Logdatei,
  eigener Besitzer in der Portkarte. Ein Workspace verbindet nie auf einen lokalen Port, den die Portkarte einem
  anderen Workspace zuordnet. Keine workspace-übergreifenden Ansichten; der Picker zeigt nur „geöffnet“.
- **Picker bei jedem Start**, zuletzt genutzter Workspace vorausgewählt, Enter öffnet. **Login beim Öffnen**, kein
  Session-Restore (wie heute). Login und Registrierung nehmen nur die URL des Workspaces; dieselbe Installation mit
  demselben Benutzer in einem zweiten Workspace lehnt der Login ab.
- **Migration** der heutigen Daten in „Standard“ (bisheriger Modus); Standard **behält die Keyring-Schlüssel ohne
  Präfix**. Nicht leere lokale Verbindungen bei Modus ≠ lokal ergeben zusätzlich „Lokal“, eine Sync-URL bei
  Modus ≠ Sync „Sync“, eine Server-URL bei Modus ≠ Server „Server“; alle drei nutzen ebenfalls die Schlüssel ohne
  Präfix (gespeicherte RDP-Passwörter und eine vorhandene Geräte-Identität bleiben nutzbar). Erststart ohne Altdaten:
  „Standard“ (Lokal).
- **Einstellungen getrennt:** global (Sprache, Theme, Passwörter speichern, RDP-Optionen, OS-Benachrichtigungen) und
  je Workspace (self-signed, Pin, Identität, Token, Browser-Zertifikat, Benachrichtigungsregeln, Sync-Intervall).
  Name, Farbe und URL ändert nur der Picker bei geschlossenem Workspace; im Fenster stehen sie als Anzeige.
- **Kenntlich:** Fenstertitel „Kunde A — AdminHelper“ (Launcher „AdminHelper“), Workspace-Chip oben in der Sidebar
  statt Modus-Badge, 4-px-Farbstreifen, OS-Benachrichtigung „[Kunde A] …“, xfreerdp-Titel „[Kunde A] …“,
  Rückfragen nennen den Workspace.
- **Löschen** nur im Picker und nur geschlossen; die Bestätigung nennt den Namen. Ein Server-Workspace widerruft
  zuerst sein Gerät (Self-Revoke), dann geht alles Lokale samt RDP-Passwörtern und Portkarten-Einträgen; bei Lokal
  ein deutlicher Datenverlust-Hinweis.
- **Sync-Workspaces** zeigen nie ein Geräte-Zertifikat; wer gegen die eigene Installation unter mTLS synchronisiert,
  nimmt einen Server-Workspace.
- **Tunnel-Laufzeitdateien** (`visitor.toml`, exportierte Identität) liegen je Workspace und nur, solange der Tunnel
  läuft.
- **Windows-RDP-Passwörter** liegen im App-Namensraum je Workspace; `TERMSRV/<adresse>` wird erst unmittelbar vor
  mstsc geschrieben und danach gelöscht. Vorab klärt ein Spike die Details. **Unter Windows nicht verifiziert
  (mstsc):** der Pool hat keine Windows-Vorlage; die Doku bekommt eine Prüfanleitung für eine manuelle Abnahme.
- **Live-Beweis mit zwei Installationen:** zwei Stacks mit zwei PKIs, beide vergeben denselben Visitor-Port; zwei
  Workspace-Prozesse gleichzeitig, jeder erreicht nur sein eigenes Ziel.
- Doku DE + EN; dabei R-0524: die Entwickler-Doku beschreibt das `rdp-error`-Event ohne offenen Versuch so, wie der
  Code es behandelt.

**Nicht-Ziele:**
- Keine Server-Änderung, keine Mandanten im Server.
- Kein Ansatz „ein Prozess, Registry“.
- Kein Fokussieren eines bereits offenen Workspace-Fensters aus dem Picker (plattformabhängig; später).
- Kein Wiederherstellen von Sitzungen, keine Rückfrage beim Schließen mit laufendem Tunnel.
- Kein workspace-eigener TOFU-Pin: Pins bleiben global (`tofu|cert|<host:port>`, known_hosts-Semantik).
- Kein Aufräumen der Altdateien im App-Datenordner in diesem Release (Downgrade bleibt möglich).
- macOS (kein Release-Ziel).
- Bewusst nicht übernommen (YAGNI, Kevin 2026-10-19): Erkennung derselben Installation über den CA-Fingerprint,
  Erneuerung des Zertifikats „beim Öffnen“ (sie hängt am Login, der beim Öffnen Pflicht ist), ACL-Härtung von
  `workspaces/` unter Windows, Rückfrage-Texte je Dialog (generisch über den ConfirmDialog). Installationsname im
  Browser-Zertifikat: eigene Roadmap-Zeile.

## Betroffene Komponenten & Dateien

RS = `apps/desktop/src-tauri/src`, UI = `apps/desktop/ui/src`, E2E = `apps/desktop/e2e`.

- **desktop-rs**
  - neu `RS/workspace.rs`: Startmodus aus argv, Id-Prüfung, Pfade, Keyring-Präfix, Titel, Logname, prozessglobaler
    Kontext, Lock, Registry- und Metadaten-Dateien, Startentscheidung, Login-Bindung, Zuständigkeit der Commands.
  - neu `RS/migration.rs`, neu `RS/launcher.rs` (Liste, Anlegen, Bearbeiten, Öffnen, Löschen, Purge).
  - `RS/main.rs`: Modus vor dem Builder (Plugin `:56-68` nur im Launcher, Logname `:79-80`), `setup` (`:94-115`):
    Migration statt `migrate_legacy_local_store` (`:105`), Lock, Kontext, Fenster per `WebviewWindowBuilder`;
    neue Commands in `generate_handler!` (`:116`).
  - `apps/desktop/src-tauri/tauri.conf.json`: `app.windows` (`:14`) leer; `enableGTKAppId` bleibt `false`.
  - `RS/storage.rs` (`app_data_file :15`, `current_mode :49`, `write_json_pretty :66`, Verbindungen `:108-131`,
    `migrate_legacy_local_store :140`, `migrate_between :152`, `load_settings :169`, `save_settings :174`).
  - `RS/enrollment.rs` (Schlüssel `:36-42`, `load_identity :204`, `is_enrolled :213`, `reset_identity :352`),
    `RS/password.rs` (`rdp_storage_key :17`, `:34`, Keyring `:49-94`, Windows-Credentials `:96-277`,
    `password_state :279`, `save_password :315`, `delete_password :339`).
  - `RS/port_registry.rs` (aus R-0430: `PortRegistry::assign(owner, visitors, recheck)`, `DEFAULT_OWNER`,
    `FALLBACK_PORTS`): Besitzer je Workspace, Obergrenzen, Lesen fremder Ports, Umbenennen, Freigeben, Waisen.
  - `RS/frpc.rs` (`VISITOR_CONFIG :640`, `app_data_dir :642`, `write_visitor_config :654`, `AppSidecar :698`,
    `stop_frpc :819`, `assign_ports :864` mit `DEFAULT_OWNER :872`, `refresh_tunnel :1030-1050`).
  - `RS/tunnel.rs` (`resolve_connection(connection, tunnels, bindings) :69`), `RS/connection/mod.rs`
    (`CredentialConnection :43`, `open_connection_stored :50`, `check_credential_connection :116`,
    `open_rdp_with_stored_password :151`), `RS/connection/rdp.rs` (`open_rdp_windows :158-182`, `/title:` `:265`).
  - `RS/diagnostics.rs` (`:24`), `RS/ansible.rs` (`write_playbook_temp :95`), `RS/commands.rs`
    (`enroll_with_token :120`, `open_connection :212`, `open_connection_stored :240`, `login :295`,
    `resolve_connection :385`), `RS/models.rs` (IPC-Typen).
- **desktop-ui**
  - neu `UI/lib/stores/workspace.ts`, `UI/lib/models/workspace.ts`, `UI/components/Picker.svelte`,
    `UI/components/WorkspaceEditor.svelte`.
  - `UI/App.svelte` (`:20-28`), `UI/lib/stores/session.ts` (`hydrate :70`, `dropSession :131`, `setMode :152`),
    `UI/lib/stores/settings.ts` (`saveSettings :79`, `serverLogout :158`), `UI/components/SettingsModal.svelte`
    (Modus-Radio `:349-383`, `onSave :269`), `UI/components/AppShell.svelte` (`isServerMode :87`,
    `currentId :91`, `modeBadge :101`, `:228`), `UI/components/Login.svelte` (`useLocal :138`, URL-Felder `:264`,
    `:354`, Knopf `:348`), `UI/components/ui/ConfirmDialog.svelte`, `UI/lib/osNotify.ts` (`:33-47`),
    `UI/lib/bridge/index.ts`, `UI/lib/bridge/types.ts`, `UI/lib/i18n/dictionaries.ts`, `UI/styles/app.css`.
- **desktop-e2e:** `E2E/wdio.conf.js` (`tauri:options` `:62-66`), `E2E/test/lib/live.js` (`login :65-89`), Specs
  mit URL-Feld (`login-error.live.js :14-16`, `enroll-form.live.js :27-35`, `enroll-trust-dialog.live.js :25-26`),
  neu `workspace-picker.live.js` (ersetzt `settings-mode.live.js`), neu `workspace-add-server.live.js`, neu
  `E2E/wdio.workspaces.conf.js` (zwei Prozesse gleichzeitig) mit `E2E/test/specs/two-installations.workspaces.js`.
- **scripts (keine Harness-Pfade):** `scripts/tests/lib_e2e_stack.sh` (`:33`, `e2e_init :93`),
  `scripts/tests/lib_e2e_stack_test.sh`, `scripts/tests/box_desktopbox.sh` (`:41-43`),
  `scripts/tests/desktop_e2e_crud.sh` (`:45-84`), neu `scripts/tests/desktop_e2e_workspaces.sh`. `run.sh` findet
  `desktop_e2e_*.sh` per Glob und verlangt sie im e2e-Layer; `run.sh`, `heavy.sh`, `scripts/dev/*`,
  `scripts/vm/*` bleiben unberührt.
- **Compose:** `docker-compose.test.yml` (Gateway-Ports `:55-60`): Bind-Adresse über `ITEST_BIND_IP`.
- **Doku:** `docs/developer/desktop.html` + EN (Architektur `:36-64`, Command-Tabelle `:80`, RDP-Race-Guard `:98`,
  Keyring `:100`, Server-Mode-Flow `:125`, Connect-Flow `:137`), `README.md`, `CHANGELOG.md`, die Admin-Seiten DE +
  EN, die den „Server-Modus“ nennen (`docs/admin/{index,benutzer,betrieb,monitoring,ansible,frp-tunnel,
  troubleshooting,agent-deployment}.html`, `docs/en/admin/{index,users,operations,monitoring,ansible,frp-tunnel,
  troubleshooting,agent-deployment}.html`, `docs/index.html`, `docs/en/index.html`).

## Datenmodell / API / Migrationen

Keine Server-API, keine Alembic-Migration. Die **lokale Datenmigration** ist Teil dieses Plans (Kevins Freigabe).

**Layout im App-Datenordner** (`identifier` bleibt `com.admincave.adminhelper`):
```
prefs.json                 globale Einstellungen; Schreiber: alle Prozesse, unter prefs.lock
workspaces.json            Registry {workspaces:[{id}], lastUsed, migratedNotice}; Schreiber: Migration, Launcher
migrate.lock               Sperre der Migration
port-registry.json (+lock) aus R-0430; Besitzer = Workspace-Id
workspaces/<id>/workspace.json   {kind, name, color, url, intervalMinutes, allowSelfSignedCerts, lastUsername,
                                  legacyKeys}; Schreiber: der Lock-Halter (Workspace-Prozess oder Launcher)
workspaces/<id>/connections.json | connections.local.json   je nach Art
workspaces/<id>/secrets.json     Namen der RDP-Schlüssel im Keyring (keine Geheimnisse)
workspaces/<id>/instance.lock    Lock je Workspace
workspaces/<id>/run/             visitor.toml, identity/ (Unix 0700), nur solange der Tunnel läuft
```
Altdateien (`settings.json`, `connections*.json`) bleiben unverändert liegen.

**Ids:** migriert `standard`, `lokal`, `sync`, `server`; neu `w-<8 hex>`. An jeder Grenze (argv, IPC) gegen
`^[a-z0-9-]{1,32}$` geprüft (Zeichenklasse ausgeschrieben, unabhängig von der Locale).

**Keyring:** `legacyKeys: true` (alle migrierten Workspaces) → Schlüssel ohne Präfix wie heute; sonst
`ws:<id>|<schlüssel>`, unter Windows `com.admincave.adminhelper/ws:<id>|<schlüssel>` als TargetName. Betroffen sind
`enroll|*` und `rdp|*` (unter Windows neu auch die RDP-Passwörter, siehe unten); `tofu|cert|*` bleibt global,
`auth|*` gibt es seit R-0430 nicht mehr. Löschen nimmt bei `legacyKeys` keine RDP-Schlüssel mit (sie können einem
anderen migrierten Workspace gehören).

**Portkarte je Workspace** (`port_registry.rs`): der Besitzer ist die Workspace-Id statt `DEFAULT_OWNER`; das muss
gelten, bevor das Single-Instance-Plugin auf den Launcher beschränkt wird (sonst teilen zwei Prozesse mit gleichem
Visitor-Namen einen lokalen Port). Neu: höchstens 500 Visitors und höchstens 250 Ausweichports je Besitzer
(`assign` lehnt darüber ab; die 1000 Ausweichports reichen damit für mindestens vier Workspaces, auch wenn ein Server
viele Visitors schickt); Lesen der lokalen Ports anderer Besitzer; Umbenennen und Freigeben eines Besitzers;
Einträge von Besitzern ohne Workspace räumt der Launcher beim Start ab. Die Migration gibt Einträge von
`DEFAULT_OWNER` an den migrierten Server-Workspace (`standard` oder `server`), sonst gehen sie.

**Bindings und fremde Ports:** `FrpcState` ist je Prozess verwaltet; `resolve_connection` und
`open_connection_stored` (R-0430 T13) sehen nur die Bindings des eigenen frpc, also des eigenen Workspace. Offen
bleibt der Fall ohne eigenen Tunnel: `127.0.0.1:<port>` landete dann beim frpc eines anderen Workspace. Deshalb
weisen `resolve_connection`, `open_connection` und `open_connection_stored` ein Loopback-Ziel (`127.0.0.0/8`,
`::1`, `localhost`, auch in Web-URLs) ab, dessen Port die Portkarte einem anderen Besitzer zuordnet und den kein
eigenes Binding hält.

**Migration** (bei jedem Prozessstart, idempotent unter `migrate.lock`): `workspaces.json` vorhanden → fertig.
Sonst aus `settings.json` (fehlt sie: Vorgaben, also lokal) Standard bauen, Dateien in `<id>.partial/` kopieren und
umbenennen, ggf. „Lokal“, „Sync“, „Server“, dann `prefs.json`, dann die Portkarte, zuletzt `workspaces.json`
atomar als Commit-Marker. Ein Abbruch an beliebiger Stelle wird beim nächsten Start neu aufgebaut, weil die
Altdateien die Quelle bleiben.

**Tauri-IPC (intern, UI ↔ Rust):**
- `Settings` behält Form und Feldnamen (`types.ts`, Parität unverändert): `load_settings` setzt sie aus
  `prefs.json` und `workspace.json` zusammen, `mode` ist die Art. `save_settings` schreibt `mode` nie, `serverUrl`
  bzw. `url` nur, solange der Workspace keine hat; eine andere URL ist ein Fehler (Server-URL: eine andere
  Origin; Sync-Quelle: jede andere Schreibweise), ebenso eine erste Server-URL, solange der Workspace eine
  Geräte-Identität hält.
- Neu: `workspace_context` → `{launcher, workspace?: WorkspaceInfo}`; Launcher-only `list_workspaces` →
  `WorkspaceList{workspaces: WorkspaceInfo[], lastUsed, migratedNotice}`, `save_workspace(draft: WorkspaceDraft)`,
  `delete_workspace(id)` → `ResetOutcome`, `open_workspace(id)`; Workspace-only `open_launcher`.
  `WorkspaceInfo{id, name, color, kind, host, open}`, `WorkspaceDraft{id?, kind, name, color, url?}`; `kind` ist
  `SyncMode`. Launcher-Commands lehnen im Workspace-Prozess ab und umgekehrt; ohne Workspace-Kontext liefern
  Datenpfade und Keyring-Präfixe einen Fehler (fail closed).
- `login` und `enroll_with_token` nehmen nur die URL des Workspaces an (oder die übergebene, solange er keine hat);
  eine erfolgreiche Registrierung macht die übergebene sofort zur URL des Workspace (kann er sie nicht behalten,
  etwa weil er währenddessen einen anderen Server bekam, wird die neue Identität sofort beim ausstellenden Server
  widerrufen und die Registrierung schlägt fehl). Ebenso binden
  `reset_device_identity`, `check_server_cert` und `reset_server_cert_pin` (dieser auch an die Sync-Quelle) an die
  URL des Workspace; der Widerruf der Geräte-Identität geht nur über HTTPS, sonst bleibt es bei `localOnly`.
  `login` lehnt dieselbe normierte Origin mit demselben Benutzernamen eines anderen Workspace ab.
- Neue Fehlertexte aus Rust sind englisch (bestehende deutsche bleiben).

**Startargumente:** `adminhelper` (Launcher), `adminhelper --workspace <id>` (unbekannte Id → Exit 2, belegter Lock
→ Exit 3, jeweils mit Logzeile), `adminhelper --workspace <id> --purge` (nur vom Launcher, ohne Fenster; Exit-Code =
Ergebnis des Self-Revoke).

**Windows-RDP-Passwörter:** Speichern legt das Passwort im App-Namensraum unter dem RDP-Schlüssel des Workspace ab
(aus der Verbindung wie gelistet, wie heute unter Unix) und trägt ihn in `secrets.json` ein. Beim Öffnen mit
gespeichertem Passwort schreibt Rust nach der Prüfung `check_credential_connection` ein `TERMSRV/<aufgelöste
Adresse>` mit Benutzer und Passwort, startet mstsc und löscht den Eintrag wieder (Zeitpunkt, Credential-Typ und
Persistenz legt der Spike fest). Vor einem Start auf ein Loopback-Ziel löscht Rust ein vorhandenes
`TERMSRV/<loopback-adresse>` immer, auch ohne gespeichertes Passwort; Einträge für andere Ziele lässt es stehen (sie
können vom Nutzer selbst stammen). In migrierten Workspaces meldet `password_state` zusätzlich ein vorhandenes
`TERMSRV/<gelistete Adresse>` als gespeichert (Stand vor R-0431), Löschen entfernt beides.

## Externe Integrationen

- **Tauri v2 Single-Instance** (<https://v2.tauri.app/plugin/single-instance/>): muss als erstes Plugin registriert
  werden; unter Linux D-Bus-Name aus dem `identifier`. Bleibt im Launcher.
- **Tauri `WebviewWindowBuilder`** (<https://docs.rs/tauri/latest/tauri/webview/struct.WebviewWindowBuilder.html>):
  `new`, `title`, `inner_size`, `build`; unter Windows Deadlock in synchronen Commands und Event-Handlern, daher in
  `setup`. Ob `AppHandle::exit` aus `setup` den Exit-Code durchreicht, ist nicht verifiziert (Alternative
  `std::process::exit` nach der Logzeile).
- **tauri-driver** (Quelle <https://docs.rs/crate/tauri-driver/latest/source/src/server.rs> und `src/cli.rs`):
  `tauri:options.args` geht unter Linux nach `webkitgtk:browserOptions.args`; `--port` (4444) und `--native-port`
  (4445) sind einstellbar, also zwei Treiber nebeneinander möglich. Aus dem Quellcode gelesen, nicht gefahren; ob
  zwei WebKitWebDriver-Sitzungen unter einem Xvfb gleichzeitig laufen, ist nicht verifiziert.
- **WebdriverIO Multiremote** (<https://webdriver.io/docs/multiremote/>): zwei benannte Sitzungen in einem Spec.
  Nicht nachgelesen.
- **Rust std `File::try_lock`** (seit 1.89, <https://doc.rust-lang.org/std/fs/struct.File.html#method.try_lock>):
  `TryLockError::WouldBlock`, frei beim Schließen; Unix `flock`, Windows `LockFileEx` (kann verbindlich sein, Datei
  mit `read`/`write` öffnen) — daher immer eigene Sperrdateien.
- **Rust std `CommandExt::process_group`** (Unix, seit 1.64,
  <https://doc.rust-lang.org/std/os/unix/process/trait.CommandExt.html>); unter Windows `creation_flags` mit
  `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
  (<https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags>, nicht nachgelesen).
- **Windows Credential Manager** (`CredWriteW`/`CredDeleteW`,
  <https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew>) und mstsc, das
  `TERMSRV/<adresse>` selbst liest: Typ, Persistenz und Lesezeitpunkt klärt der Spike; **unter Windows nicht
  verifiziert (mstsc)**, nur die Credential-Aufrufe laufen im CI-Job `rust-windows`.
- **Docker Compose:** Port-Veröffentlichung mit Host-Adresse (`"<ip>:<host>:<container>"`); `127.0.0.2` als
  zweite Loopback-Adresse unter Linux. Nicht gefahren.
- **keyring 3**: keine Aufzählung von Einträgen (nicht verifiziert), daher der Index `secrets.json`.

## Trade-offs & Alternativen

- **Prozess je Workspace (gewählt, Kevin)** statt ein Prozess mit Registry: die Singletons (`FrpcState`,
  `StreamState`, `CLIENT_CACHE`, `SessionState`) bleiben, die Trennung macht das Betriebssystem. Preis: etwa
  370 MiB je Fenster, ein Launcher-Prozess, Lock-Logik.
- **`Settings` als zusammengesetzte Sicht** statt getrennter Commands: die Leser von `$settings` bleiben
  unverändert; der Schnitt liegt nur in `storage.rs`.
- **Globale Einstellungen per Drei-Wege-Abgleich:** unter `prefs.lock` neu lesen und nur die Felder schreiben, die
  dieser Prozess geändert hat; ganzes Überschreiben verlöre die Änderung eines zweiten Fensters.
- **Fenster in `setup`:** Titel ab dem ersten Bild; ein Prozess mit unbekannter Id oder belegtem Lock zeigt nie ein
  Fenster; der Launcher kann kleiner sein.
- **Löschen über ein Purge-Kind** statt im Launcher: Self-Revoke, Identität und Keyring-Präfix hängen am
  prozessglobalen Kontext; das Kind nutzt den Code des Workspace-Prozesses, der Launcher bekommt nie ein fremdes
  Präfix.
- **Portkarten-Einträge eines Workspace ohne Tunnel bleiben (gewählt).** Aufräumen beim Abmelden oder Schließen
  würde die lokalen Ports beim nächsten Öffnen neu verteilen; SSH-`known_hosts`, der Zertifikats-Cache von FreeRDP
  und Browser-Cookies hängen an `[127.0.0.1]:<port>`, jede Neuverteilung brächte Host-Key-Warnungen. Ein anderer
  Workspace bekommt dann einen Ausweichport und erreicht sein Ziel über die Auflösung; die Obergrenzen halten den
  Ausweichbereich frei, `recheck` (R-0430) holt einen Port zurück, den inzwischen jemand anders belegt. Einträge
  verfallen mit dem Löschen des Workspace und als Waisen beim Launcher-Start.
- **Fremde Ports abweisen statt umleiten:** ohne eigenen Tunnel gibt es kein richtiges Ziel; eine Umleitung auf
  irgendeinen Port wäre geraten. Die Meldung nennt den Grund (Tunnel dieses Workspace starten).
- **TERMSRV just-in-time (Kevin 2026-10-19)** statt kein Speichern für Tunnelziele: das Geheimnis liegt im
  App-Namensraum je Workspace, der globale `TERMSRV`-Namensraum trägt es nur für die Dauer eines Starts. Preis: ein
  Spike, Windows-Code ohne Windows-Box.
- **Zwei Prozesse gleichzeitig im Live-Beweis** (Multiremote mit zwei tauri-drivern) statt nacheinander: nur
  gleichzeitig zeigt sich, dass zwei frpc mit demselben Server-Port nebeneinander laufen. Gelingen zwei
  WebDriver-Sitzungen nicht, fragt die Bau-Session Kevin (Rückfall: nacheinander, der Port des ersten hält ein
  Listener).
- **Migration kopiert statt verschiebt; deterministische Ids:** Downgrade und Abbruch ohne Verlust, keine
  verwaisten Verzeichnisse.

## Risiken & Rollback

- **Datenverlust bei der Migration:** Altdateien bleiben byte-gleich; Tests mit Abbruch nach jedem Schritt; zwei
  gleichzeitige Starts laufen hintereinander unter `migrate.lock`.
- **Keyring:** ein falsches Präfix macht die Identität eines migrierten Workspace unsichtbar (Neu-Registrierung
  nötig). Tests lesen die Altschlüssel über den Standard-Kontext.
- **Risikopfade** (Enrollment, Keyring, FRP, Tunnel-Auflösung, Wire-Typen, Compose) und die Windows-Credentials:
  `security`-Prüfer, im Ledger je Task genannt.
- **Windows:** mstsc, abgekoppelter Prozessstart, Lock und Keyring-TargetName sind ohne Windows-Box nur über den
  CI-Job `rust-windows` (Unit-Tests) und die manuelle Prüfanleitung abgedeckt. WebView2 teilt den Browser-Prozess
  je Benutzerdatenordner; zwei verschiedene App-Versionen gleichzeitig laufen womöglich nicht.
- **Launcher beendet sich vor dem Workspace:** er wartet, bis der neue Prozess seinen Lock hält (höchstens 10 s);
  endet der vorher, zeigt der Picker einen Fehler.
- **Live-Beweis:** zwei Stacks, zwei WebDriver-Sitzungen und `127.0.0.2` sind neu; der Lauf ist lang und kann
  zunächst flaky sein.
- **E2E-Reihenfolge:** nach dem ersten erfolgreichen Login ist die URL fest; `live.js` und die Specs mit URL-Feld
  arbeiten mit und ohne Feld.
- **Rollback:** Revert des Merges. Die ältere Version liest wieder `settings.json` und die Altdateien (Stand vor der
  Migration); Änderungen aus der Workspace-Zeit sieht sie nicht. Keyring-Einträge mit Präfix bleiben ungenutzt
  liegen; Windows-RDP-Passwörter im App-Namensraum kennt die ältere Version nicht.

## Doku-Impact

`docs/developer/desktop.html` DE+EN: Abschnitt Workspaces (Launcher, Prozess je Workspace, Startargumente, Lock,
Datenlayout, Migration, Keyring-Präfix, Portkarte je Workspace und fremde Ports, Einstellungs-Schnitt, Logname,
Laufzeitdateien), Single-Instance nur im Launcher, Command-Tabelle, Windows-RDP-Passwörter mit Prüfanleitung für
eine manuelle Abnahme unter Windows, und (R-0524) das `rdp-error`-Event ohne offenen Versuch: es wird gemeldet,
markiert aber keinen anderen Versuch. `README.md`: Desktop-Abschnitt. Admin-Seiten DE+EN: „Server-Modus“ →
„Server-Workspace“, ein Absatz Workspaces. `CHANGELOG.md`: Added, Changed.

## Entscheidungen (Kevin 2026-10-19)

Launcher schließt sich nach dem Öffnen · Erststart „Standard“ (Lokal) · Name und Farbe nur im Picker ·
migrierte Zusatz-Workspaces nutzen die Schlüssel ohne Präfix · zusätzlicher Workspace „Server“ bei gespeicherter
Server-URL · doppelte Anmeldung (gleiche Origin, gleicher Benutzer) abgelehnt · Windows-RDP über TERMSRV
just-in-time mit Spike vorab · Sync nie mit Geräte-Zertifikat · Live-Beweis mit zwei Installationen jetzt · die
YAGNI-Punkte bleiben draußen · Löschbestätigung nennt den Namen.

## Windows-RDP: Ergebnis des Spikes

Spike T16 (2026-10-20), aus der Microsoft-Doku (Quellen unten). Die Credential-Aufrufe prüft `termsrv_probe_*` im
CI-Job `rust-windows`. **Unter Windows nicht verifiziert (mstsc):** dass mstsc einen solchen Eintrag liest, belegt
keine Microsoft-Quelle.

- **Typ `CRED_TYPE_GENERIC`** (wie bisher): Einen generischen Eintrag nutzt kein Authentifizierungspaket, alle
  Prozesse des Nutzers lesen und schreiben ihn [2][6], also auch mstsc. `CRED_TYPE_DOMAIN_PASSWORD` nutzen NTLM,
  Kerberos und Negotiate selbst, das Passwort lesen nur sie [2][6]. Dagegen sprechen zwei dokumentierte Sperren: Mit
  Credential Guard (ab Windows 11 22H2 auf Domänengeräten Standard [8]) scheitern vom Remotedesktop-Client
  gespeicherte Windows-Anmeldeinformationen mit „Logon attempt failed“, CredSSP nimmt dann nur noch übergebene
  Anmeldeinformationen; generische schützt Credential Guard nicht [7]. Und gespeicherte Anmeldeinformationen
  delegiert CredSSP an ein Ziel, das sich nur per NTLM ausweist (IP-Adresse, Loopback-Port), auf einem Domänengerät
  standardmäßig nicht [9]. Lesbar für andere Prozesse des Nutzers ist das Passwort ohnehin: auch der App-Namensraum
  liegt unter Windows in generischen Einträgen (`keyring_store`). Just-in-time schützt davor, dass mstsc
  `TERMSRV/<adresse>` für jede Verbindung zu dieser Adresse nimmt, auch aus einem anderen Workspace oder von Hand.
- **Persistenz `CRED_PERSIST_SESSION`** statt `CRED_PERSIST_LOCAL_MACHINE`: Der Eintrag gilt nur in der
  Anmeldesitzung, andere Sitzungen desselben Nutzers sehen ihn nicht, nach Ab- und Anmelden ist er weg [2]. Ein
  Eintrag, den die App nicht mehr löschen konnte (beendet oder abgestürzt), endet so spätestens mit der Abmeldung. Es
  ist die geringste Persistenz, die überhaupt speichert; beschränkt eine Richtlinie einen Typ auf Sitzungs-Einträge,
  gelingt sie noch [5]. mstsc läuft als Kind der App in derselben Anmeldesitzung, `CredReadW` liest deren
  Credential-Set [3].
- **Name** wie bisher `rdp_windows_target`: `TERMSRV/<host>`, bei Port ≠ 3389 `TERMSRV/<host>:<port>`, hier für die
  aufgelöste Adresse. Name und Typ bestimmen den Eintrag, `CredWriteW` ersetzt einen gleichen Namens und Typs
  [1][2], `CredDeleteW` löscht je Typ [4].
- **Löschen nach fester Frist** (`TERMSRV_HOLD`, 60 s nach dem Start von mstsc; scheitert der Start, sofort), nicht
  am Ende von mstsc: `TERMSRV` trägt das Geheimnis nur für den Start (Kevin 2026-10-19), das Ende von mstsc hielte es
  die ganze Sitzung im globalen Namensraum, und ob der gestartete Prozess so lange lebt, ist nicht dokumentiert [10].
  Die Frist ist doppelt so lang wie die der `.rdp`-Datei (30 s), weil mstsc vor dem Verbinden nach Herausgeber oder
  Zertifikat fragen kann und nicht belegt ist, ob es den Eintrag vorher oder danach liest. Zu früh gelöscht heißt:
  mstsc fragt nach dem Passwort, kein Leck.
- **Loopback-Ziele:** Vor jedem Start auf diese Maschine löscht Rust `TERMSRV/<adresse>` in beiden Typen, auch ohne
  gespeichertes Passwort. Der Remotedesktop-Client speichert selbst Windows-Anmeldeinformationen [7], also
  Domänen-Einträge; einer für `127.0.0.1:<port>` ginge sonst an den Server, der jetzt hinter dem Port liegt.
  Einträge anderer Ziele bleiben in beiden Typen stehen.
- **Wiederverbindung:** Nach einem Netzabbruch verbindet der Client mit dem Auto-Reconnect-Cookie aus seinem
  Speicher, ohne die Anmeldeinformationen erneut zu senden; scheitert das, holt er sie neu [11][12]. Woher mstsc sie
  dann nimmt, ist nicht dokumentiert: findet es den Eintrag nach der Frist nicht mehr, fragt es nach dem Passwort.

Plan (`termsrv_plan` in `password.rs`, Tests `termsrv_plan_*`; T17 führt ihn aus):

| Ziel | gespeichertes Passwort | Schritte |
|---|---|---|
| anderes | nein | Starten |
| anderes | ja | Schreiben, Starten, nach 60 s Löschen |
| diese Maschine | nein | Löschen (beide Typen), Starten |
| diese Maschine | ja | Löschen (beide Typen), Schreiben, Starten, nach 60 s Löschen |

Probe (`termsrv_probe_*`, nur im CI-Job `rust-windows`): schreibt `TERMSRV/adminhelper-probe-<pid>-<ns>.invalid:3390`
generisch mit `CRED_PERSIST_SESSION`, liest Typ, Persistenz, Benutzer und Passwort zurück und löscht den Eintrag.

**Unverifiziert, für die Prüfanleitung (T33):** (1) dass mstsc einen generischen `TERMSRV/…`-Eintrag liest und
nutzt: Microsoft dokumentiert es weder bei `mstsc` [10] noch bei `cmdkey` [13], `cmdkey /generic:TERMSRV/<ziel>`
steht nur in Forenantworten; auch mit Credential Guard und auf einem Domänengerät gegen ein NTLM-Ziel; (2) dass es
Einträge mit `CRED_PERSIST_SESSION` findet; (3) wann es den Eintrag liest und ob 60 s reichen; (4) welchen Namen es
bei Port ≠ 3389 nachschlägt (`TERMSRV/<host>:<port>` oder `TERMSRV/<host>`), auch bei IPv6; (5) welcher Eintrag
gilt, wenn ein generischer und ein Domänen-Eintrag gleichen Namens bestehen; (6) Wiederverbindung nach Ablauf der
Frist ohne Rückfrage.

**Entscheidung Kevin 2026-10-20 (Fund aus dem Spike):** `CredWriteW` ersetzt einen generischen Eintrag gleichen
Namens. Deshalb tragen eigene Einträge einen festen Marker im Feld `Comment`, und `Remove` löscht nur einen
eigenen. Besteht für ein Ziel ohne Loopback schon ein generischer Eintrag ohne Marker (eigener `cmdkey`-Eintrag
oder Alt-Eintrag von vor R-0431), schreibt und löscht die App nichts; mstsc nimmt den vorhandenen, die Tabelle
oben gilt dann als „Starten“ (T17). Bei Loopback-Zielen löscht die App vor jedem Start beide Typen in beiden
Namensformen (`TERMSRV/<host>:<port>` und `TERMSRV/<host>`), bis Punkt (4) unten belegt ist. Ein zweiter Start
einer anderen Verbindung auf dasselbe Ziel, solange ein Eintrag in seiner Frist liegt, wird abgelehnt (T39).
Alt-Einträge `TERMSRV/<gelistete Adresse>` übernimmt der migrierte Workspace beim ersten Start in seinen
App-Namensraum und löscht sie danach (T40).

Quellen (abgerufen 2026-10-20):

- [1] CredWriteW, <https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew>
- [2] CREDENTIALW, <https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw>
- [3] CredReadW, <https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw>
- [4] CredDeleteW, <https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-creddeletew>
- [5] CredGetSessionTypes,
  <https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credgetsessiontypes>
- [6] Kinds of Credentials, <https://learn.microsoft.com/en-us/windows/win32/secauthn/kinds-of-credentials>
- [7] Credential Guard, Considerations and known issues,
  <https://learn.microsoft.com/en-us/windows/security/identity-protection/credential-guard/considerations-known-issues>
- [8] Credential Guard overview, <https://learn.microsoft.com/en-us/windows/security/identity-protection/credential-guard/>
- [9] Policy CSP ADMX_CredSsp (AllowSavedCredentials, AllowSavedCredentialsWhenNTLMOnly),
  <https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-admx-credssp>
- [10] mstsc, <https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mstsc>
- [11] MS-RDPBCGR 1.3.1.5 Automatic Reconnection,
  <https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/15b0d1c9-2891-4adb-a45e-deb4aeeeab7c>
- [12] MS-RDPBCGR 5.5 Automatic Reconnection,
  <https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/e729948a-3f4e-4568-9aef-d355e30b5389>
- [13] cmdkey, <https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmdkey>

## Offene Fragen

Keine Produktfragen offen. Grenzwerte 500 Visitors und 250 Ausweichports je Workspace sind Konstanten in
`port_registry.rs` und lassen sich ändern.
