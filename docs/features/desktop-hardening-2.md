<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Härtung 2: Provisionierungsbefehl, Passwortübergabe, Sync-Quelle, Ansible-Commands

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/desktop-hardening-2.md`. Härtungspaket (Kevin 2026-10-22).

## Problem / Motivation

1. **Provisionierungsbefehl (T1).** Der Tab *Infrastruktur → Server → Provisionierung* baut beide Befehle per
   Template-Literal (`apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte:70-87`) aus `s.serverUrl`, dem
   Token aus der Antwort von `createToken` (`:67`), `server.id` und `caFp`, ohne Quoting und ohne Formatprüfung. Der
   Befehl wird auf dem Zielhost als root ausgeführt (`| sudo bash -s --`, `sudo adminhelper-agent provision`). Jeder
   Wert soll genau ein Shell-Wort mit seinem wörtlichen Wert sein, und Token und Server-ID sollen die Form haben, die
   der Server erzeugt: das Token `adminhelper_prov_` + `secrets.token_urlsafe(32)`
   (`apps/server/app/modules/provisioning/router.py:70`, Zeichen `[A-Za-z0-9_-]`), die Server-ID `str(uuid.uuid4())`
   (`apps/server/app/modules/servers/router.py:110`, der einzige Weg, auf dem ein Server entsteht).

2. **RDP-Passwort an xfreerdp (T2).** `feed_password_stdin` (`apps/desktop/src-tauri/src/connection/rdp.rs:446-470`)
   schreibt das Passwort per stdin und überschreibt danach seine eigene `format!`-Kopie mit Nullen (`unsafe`,
   `as_bytes_mut`, `:455-461`); unter Windows tut `windows_write_credential` dasselbe mit seiner UTF-16-Kopie
   (`apps/desktop/src-tauri/src/password.rs:1137`, `:1151-1153`). Alle anderen Kopien bleiben unberührt: das Argument
   der Commands (`apps/desktop/src-tauri/src/commands.rs:325`, `:406`, `:424`), der Text der IPC und der Webview, die
   Strings aus dem Schlüsselbund (`password.rs:121-153`) und die Tokens der Sitzung, die `current()` bei jedem Aufruf
   klont (`apps/desktop/src-tauri/src/session.rs:27-47`, `:119-121`). Die zwei Schleifen sagen mehr zu, als der Desktop
   hält. Gewünscht (Kevin 2026-10-22): keine Teil-Überschreibung, ein Kommentar und die Doku sagen, was gilt.

3. **Sync-Quelle (T3).** `sync_connections` (`commands.rs:263-271`, `apps/desktop/src-tauri/src/sync.rs:11-37`) lädt
   die URL, die die Oberfläche übergibt, in jedem Prozess und in jeder Art von Workspace, und schreibt das Ergebnis in
   den Cache des Workspace. Anmeldung, Registrierung und Pin-Reset binden ihre URL dagegen an den Workspace
   (`sign_in_target`, `commands.rs:162-169`; `workspace::own_url`, `apps/desktop/src-tauri/src/workspace.rs:729-744`;
   `reset_server_cert_pin_in`, `commands.rs:91-94`). Die Doku sagt, aller Server-Verkehr laufe über `api_proxy`
   (`docs/developer/desktop.html:247`). Der Zweig mit Geräte-Identität (`sync_uses_identity`, `sync.rs:24-28`,
   `:41-44`) greift seit den Workspaces nur noch außerhalb eines Sync-Workspace: ein Sync-Workspace hat keine
   Server-URL (`apps/desktop/src-tauri/src/storage.rs:394`; Doku `desktop.html:245`: „ein Sync-Workspace hat keine,
   also lädt ein Sync nie mit dem Geräte-Zertifikat“). Gewünscht: ein Sync lädt nur im Sync-Workspace und nur dessen
   gespeicherte Quelle, nie mit Geräte-Identität.

4. **Ansible-Commands (T4, T5).** Der Kommentar an `is_confined_ansible_path` (`apps/desktop/src-tauri/src/ansible.rs:119-123`)
   beschreibt die Prüfung als Schutz davor, dass `ansible-playbook` beliebiges YAML ausführt. Die Prüfung stellt aber
   nur sicher, dass eigene Temp-Dateien ausgeführt und gelöscht werden: den Inhalt schreibt `ansible_write_playbook`
   (`commands.rs:643-646` → `ansible.rs:95-117`) so, wie die Oberfläche ihn übergibt. Die drei Ansible-Commands
   (`commands.rs:636-651`) laufen zudem auch im Launcher-Prozess, anders als die Commands der Workspace-Verwaltung
   (`only`, `commands.rs:534-536`). Gewünscht: Ansible nur im Workspace-Prozess; Kommentar und Doku sagen, was die
   Prüfung leistet (T4). Weiter (T5, offene Frage 1): ein Command `ansible_run(playbook_id, targets)`, für das Rust
   den Inhalt selbst vom angemeldeten Server lädt.

5. **Commands je Prozess (T6, offene Frage 2).** Alle 40 Commands sind in jedem Prozess registriert
   (`apps/desktop/src-tauri/src/main.rs:220-261`); ohne `AppManifest` erlaubt Tauri jedem Fenster jeden Command
   (Externe Integrationen). Launcher- und Workspace-Fenster heißen beide `main` (`main.rs:110`, `:209`), die
   Capability `apps/desktop/src-tauri/capabilities/default.json` gilt für `main`. Die Trennung leisten heute `only()`
   und Commands, die einen Workspace oder eine Sitzung brauchen.

## Ziel & Nicht-Ziele

Ziel:
- Der Provisionierungsbefehl enthält jeden Wert als ein Shell-Wort mit wörtlichem Wert; ein Wert aus den Zeichen
  `[A-Za-z0-9@%+=:,./_-]` bleibt, wie er ist (die Anzeige ändert sich für die erzeugten Werte nicht). Ein Token außerhalb
  von `[A-Za-z0-9_-]` oder eine Server-ID, die keine UUID ist, ergibt keinen Befehl, sondern eine Meldung.
- Die eigene Kopie eines Passworts (stdin-Payload für xfreerdp, UTF-16-Kopie für den Credential Manager) nullt der
  Desktop mit `zeroize` statt mit `unsafe`; `connection/` erlaubt kein `unsafe`. Die Entwickler-Doku sagt, wie das
  Passwort zu xfreerdp bzw. in den Credential Manager kommt und welche Kopien ungenullt bleiben (Entscheidung am
  Gate, siehe „Offene Fragen“).
- `sync_connections` lädt nur im Sync-Workspace, nur von dessen gespeicherter Sync-URL (die Oberfläche muss genau sie
  nennen), immer ohne Geräte-Identität. Name, Argument und Antwort des Commands bleiben.
- Die Ansible-Commands lehnen im Launcher ab; Kommentar und Doku beschreiben die Pfadprüfung, wie sie wirkt.
- Nur nach Kevins Ja: `ansible_run` (T5), Capabilities je Prozess (T6).

Nicht-Ziele (YAGNI):
- Kein durchgängiges Nullen aller Kopien von Passwörtern und Tokens (IPC, Webview, Schlüsselbund, Sitzung), kein
  `secrecy`; `zeroize` nur für die zwei eigenen Kopien aus T2.
- Keine Änderung an `api_proxy`, an den Zielen eines Ansible-Laufs (Hostnamen aus der Oberfläche, geprüft wie heute,
  `ansible.rs:34-48`) und am Windows-Terminal.
- Kein Umbau des Provisionierungs-Tabs über die Befehlszeilen hinaus (Auto-Hide, Token-Liste bleiben).
- Schon erledigt und hier nicht geplant: die Laufzeitdateien des Tunnels (`visitor.toml`, `identity/`) liegen nur,
  solange frpc läuft — Stopp, Abmelden, Anmeldungswechsel und Programmende leeren `run/` (`stop_frpc`,
  `apps/desktop/src-tauri/src/frpc.rs:909-920`; `main.rs:202-206`, `:265-266`; PR #239), beschrieben samt dem
  Fall „frpc endet von selbst“ in `docs/developer/desktop.html:154`.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | desktop-ui | `apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte`, `…/ProvisioningTab.test.ts`, `apps/desktop/ui/src/lib/utils/shell.ts` (neu), `apps/desktop/ui/src/lib/utils/shell.test.ts` (neu), `apps/desktop/ui/src/lib/i18n/dictionaries.ts`, `CHANGELOG.md` |
| T2 | desktop-rs | `apps/desktop/src-tauri/src/connection/rdp.rs`, `apps/desktop/src-tauri/src/connection/mod.rs`, `apps/desktop/src-tauri/src/password.rs`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html` |
| T3 | desktop-rs | `apps/desktop/src-tauri/src/commands.rs`, `apps/desktop/src-tauri/src/workspace.rs`, `apps/desktop/src-tauri/src/sync.rs`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `CHANGELOG.md` |
| T4 | desktop-rs | `apps/desktop/src-tauri/src/commands.rs`, `apps/desktop/src-tauri/src/ansible.rs`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html` |
| T5 [?] | desktop | `ansible.rs`, `commands.rs`, `main.rs`, `apps/desktop/ui/src/lib/bridge/index.ts`, `apps/desktop/ui/src/lib/stores/ansible.ts`, `…/ansible.pipeline.test.ts`, Doku Desktop + Ansible (DE+EN), `CHANGELOG.md` |
| T6 [?] | desktop | `apps/desktop/src-tauri/build.rs`, `capabilities/default.json` (weg), `capabilities/launcher.json`, `capabilities/workspace.json` (neu), `main.rs`, `apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts`, Doku Desktop (DE+EN) |

Kein Pfad steht auf `scripts/dev/review-risk.txt`.

## Datenmodell / API / Migrationen

Keine Server-Route, kein Schema, keine Migration, keine gespeicherte Datei ändert ihr Format. Tauri-IPC: T1–T4 lassen
Namen, Argumente und Antworten aller Commands, wie sie sind (T3 und T4 lehnen in Fällen ab, die die Oberfläche nie
auslöst: die Oberfläche ruft `syncConnections` nur im Sync-Workspace mit der geladenen Sync-URL,
`apps/desktop/ui/src/lib/stores/connections.ts:116-117`, `settings.ts:55-59`; Ansible nur im Workspace). T5 ändert die
IPC (drei Commands → einer) und ist deshalb Kevins Entscheidung. T6 ändert keine Namen, aber die Fensterlabels und
welche Commands ein Fenster rufen darf. Die Liste der Commands prüft `apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts`
gegen `commands.rs`, `main.rs`, die Bridge und die Tabelle in `desktop.html` (DE+EN).

## Externe Integrationen

- POSIX Shell Command Language, 2.2.2 Single-Quotes (pubs.opengroup.org, gelesen 2026-10-22): „Enclosing characters
  in single-quotes ('') shall preserve the literal value of each character within the single-quotes.“ und „A
  single-quote cannot occur within single-quotes.“ — daher `'` als `'\''`.
- Tauri 2 (v2.tauri.app/security/capabilities, gelesen 2026-10-22): „By default, all commands that you registered in
  your app are allowed to be used by all the windows and webviews of the app. To change that, consider using
  `AppManifest::commands`.“ „The security boundaries are depending on window labels (not titles).“ tauri-build 2.6.3
  `AppManifest::commands`: „Define a list of commands that gets permissions autogenerated in the format of
  `allow-$command` and `deny-$command` where $command is the command name in snake_case.“ Ob ein Command, der nicht im
  `AppManifest` steht, dann verweigert wird: nicht verifiziert (T6 belegt es per Test).
- xfreerdp (stdin), Windows Credential Manager: unverändert.

## Trade-offs & Alternativen

1. **Quoting (T1):** (a) nur, wenn nötig, wie Pythons `shlex.quote` (sichere Zeichen bleiben) — **Empfehlung**: die
   erzeugten Werte (Base64url, UUID, Hex, https-URL) sehen aus wie heute, die Doku
   (`docs/admin/agent-deployment.html:46-51`) und `apps/desktop/e2e/test/specs/provisioning.live.js` bleiben. (b) immer
   quoten: jede Anzeige ändert sich, kein Gewinn.
2. **Formatprüfung (T1):** Token nur gegen die Zeichenklasse `[A-Za-z0-9_-]+` (nicht gegen das Präfix — ein anderes
   Präfix am Server bräche sonst den Tab), Server-ID als UUID (8-4-4-4-12 Hex, Groß-/Kleinschreibung egal).
3. **Passwort (T2):** (a) entfernen und ehrlich beschreiben — **Empfehlung (Kevin)**. (b) `zeroize` für die zwei
   Kopien: deckt IPC, Webview, Schlüsselbund und Sitzung nicht und wäre eine neue direkte Abhängigkeit
   (`THIRD_PARTY_LICENSES.md`). Wächter: `#![forbid(unsafe_code)]` in `connection/mod.rs` (das einzige `unsafe` unter
   `connection/` ist `rdp.rs:457`); damit ist die Task ohne den Fix rot (Kompilierfehler).
4. **Sync (T3):** (a) Argument bleibt, muss gleich der gespeicherten Quelle sein (Schreibweise wie beim Speichern,
   `storage.rs:435`: „a sync source is the same one only as it is spelled“), geladen wird die gespeicherte —
   **Empfehlung**, ohne Vertragsänderung, eine Abweichung ist ein Fehler statt eines stillen anderen Abrufs. (b) Argument
   ignorieren: ein toter Parameter im Vertrag. Der Fehlertext nennt keine URL (eine Sync-URL kann Zugangsdaten tragen,
   vgl. `workspace.rs:716-723`). Der Zweig mit Geräte-Identität entfällt mit seinen drei Tests (`Test-Löschung:`).
5. **Ansible im Launcher (T4):** `only(Side::Workspace)` in den drei Commands — **Empfehlung**, klein, wie die übrigen
   Commands der Workspace-Seite. Alternative: Capabilities (T6).
6. **`ansible_run` (T5):** Rust holt Metadaten (`filename`) und Inhalt am angemeldeten Server
   (`GET /api/ansible/playbooks/{id}` und `/{id}/content`, `apps/server/app/modules/ansible/router.py:93-118`), schreibt
   Inventory und Playbook, startet und räumt bei jedem Fehler vor dem Start beide Dateien ab. Ausgeführt wird dann
   immer, was am Server liegt. Kosten: IPC-Änderung samt Bridge, Store, Doku; berührt dieselben Dateien wie andere
   Arbeit an `ansible.rs`.
7. **Capabilities (T6):** (a) eigene Labels `launcher`/`workspace`, `AppManifest::commands` in `build.rs`, zwei
   Capability-Dateien, Paritätstest; (b) Label `main` behalten und die Capability je Prozess zur Laufzeit hinzufügen
   (`Manager::add_capability`, Feature `dynamic-acl`, in tauri 2.11.5 Standard) — Capabilities dann außerhalb des
   Standardordners. (a) ist statisch und prüfbar. Gegen beide spricht der kleine Gewinn nach T3/T4: im Launcher ist
   dann kein Command mehr frei, der dort nicht hingehört, und das Workspace-Fenster braucht alle Workspace-Commands.

## Risiken & Rollback

- T1: Liefert ein Server ein Token oder eine ID in anderer Form, zeigt der Tab keinen Befehl mehr (gewollt); das
  Token ist am Server trotzdem angelegt und erscheint in der Liste. Rollback: Revert.
- T2: keine Verhaltensänderung; `forbid(unsafe_code)` verbietet künftiges `unsafe` unter `connection/` — braucht eine
  spätere Änderung dort `unsafe`, muss sie den Wächter bewusst ändern.
- T3: ein Sync-Workspace, dessen Oberfläche eine andere Schreibweise als die gespeicherte schickte, bekäme einen
  Fehler; die Oberfläche nimmt die URL aus `load_settings` (`storage.rs:383`), also genau die gespeicherte.
- T5/T6: siehe offene Fragen; T6 kann einen Command vergessen, den die Oberfläche braucht → Fehler zur Laufzeit; den
  fängt nur der Paritätstest und die GUI-E2E (`linux-full`).
- Jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T1: CHANGELOG (Changed). T2: `docs/developer/desktop.html:268` (DE+EN), ein Satz zur Passwortübergabe und dazu, dass
der Desktop Passwörter und Tokens im Speicher nicht überschreibt. T3: `desktop.html:245` (DE+EN, Sync-Abruf),
CHANGELOG (Changed). T4: `desktop.html:182` und `:247` (DE+EN). T5: `desktop.html:114`, `:182`, `:247`,
`docs/admin/ansible.html:67` (DE+EN), CHANGELOG. T6: `desktop.html:171` (DE+EN).

## Offene Fragen

1. **T5 — `ansible_run` statt `ansible_generate_inventory` + `ansible_write_playbook` + `ansible_launch`?** (IPC-Vertrag,
   Kevin) Empfehlung: ja — Oberfläche und Backend erscheinen gemeinsam, es gibt keinen anderen Verbraucher; danach
   läuft nur Inhalt, der am Server liegt, und ein Lauf räumt in einem Aufruf ab. Trade-off: Vertragsänderung und eine
   Task über zwei Komponenten. Bei „nein“ wird T5 `[~]`.
2. **T6 — Commands je Prozess über Tauri-Capabilities?** Empfehlung: nein, zurückstellen — nach T3/T4 bleibt im
   Launcher kein Command frei, der dort nicht hingehört, und im Workspace-Fenster schränkt eine ACL nichts ein, was die
   Oberfläche nicht braucht; Gewinn wäre nur „verweigert, bis freigegeben“ für künftige Commands, bei Labels,
   `build.rs`, zwei ACL-Dateien und einem GUI-E2E-Lauf als Beweis. Bei „ja“ baut T6 Variante (a).

Entschieden (Kevin 2026-10-22): Frage 1 ja, T5 gebaut. Frage 2 zurückgestellt, T6 `[~]`. T2 abweichend von
Trade-off 3 (a): die eigene Kopie wird mit `zeroize` genullt statt die Schleife ersatzlos zu entfernen; neue direkte
Abhängigkeit `zeroize` (Cargo.toml, Cargo.lock, `THIRD_PARTY_LICENSES.md`), der Wächter
`#![forbid(unsafe_code)]` in `connection/mod.rs` bleibt.
