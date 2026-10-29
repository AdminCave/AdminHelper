<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Härtung 3: Ansible-Laufverzeichnis, Playbook-Name und Antwortgröße, Sync-Doku, Pin-Reset, Provisionierungsbefehl

Stand des Codes: `feature/desktop-hardening-2@cea7fb9b` (PR #269, beim Planen noch nicht gemergt). Der Branch steht
absichtlich darauf: `ansible_run`/`fetch_json`, der Sync aus der gespeicherten Quelle und die Prüfungen im
Provisionierungs-Tab kommen erst mit #269. Nach dessen Merge holt der Branch `origin/main` herein; der builder greppt
jede `datei:zeile` vor dem Schreiben neu. Roadmap: R-0748 (BUG), R-0771 und R-0817 (REF, enthält R-0772); dazu
Härtungen derselben Stellen (Kevin 2026-10-22).

## Problem / Motivation

1. **Ansible-Temp-Dateien liegen direkt im gemeinsamen Temp-Verzeichnis.** `generate_inventory` und
   `write_playbook_temp` schreiben nach `std::env::temp_dir()` (`apps/desktop/src-tauri/src/ansible.rs:169-173`,
   `:193-198`), unter Linux `/tmp`. Ansible liest `group_vars/` und `host_vars/` relativ zum Inventory und zum
   Playbook und lädt Module und Plugins aus Verzeichnissen neben dem Playbook (Externe Integrationen). Ein Lauf liest
   also mit, was andere Programme in `/tmp` unter diesen Namen ablegen. Dazu: Scheitert `write_all` nach dem Anlegen
   (`:174-175`, `:199-200`), bleibt die halb geschriebene Datei liegen; `run()` (`:81-100`) entfernt nur das Inventory,
   wenn das Playbook scheitert. `docs/developer/desktop.html:114` sagt, es lösche „die Dateien, die es schon geschrieben
   hat“. Und Tests, die vor dem Aufräumen scheitern, lassen ihre Dateien in `/tmp` (auf der Dev-Box lagen am
   2026-10-22 358 Inventory-Dateien aus einem Test vor c13e2c4e).
2. **Der Playbook-Dateiname geht fast roh in eine Befehlszeile.** `safe_name` (`ansible.rs:182-186`) ersetzt nur `/`,
   `\` und `..`. Unter Windows geht der Pfad als Argument an Windows Terminal (`ansible.rs:262-270`,
   `terminal.rs:107-128`), das `;` als Trenner seiner Unterbefehle liest, und im Fallback an `cmd`. Der Server lässt
   heute nur `^[\w\-. ]+\.(yml|yaml)$` zu (`apps/server/app/modules/ansible/schemas.py:27`, `:49`); der Desktop soll
   sich an seiner Grenze nicht darauf verlassen.
3. **`fetch_json` liest eine Antwort ohne Größengrenze** (`ansible.rs:74`, `response.json()`), und kein Test prüft eine
   2xx-Antwort, deren Body nicht passt (Befund des testers zu #269).
4. **R-0817:** `cargo clippy --all-targets` meldet `zombie_processes` im Test-Helfer `signal_mid_run`
   (`ansible.rs:567-593`: `wait()` nur, wenn `try_wait` nichts lieferte); das Gate fährt clippy ohne `--all-targets`.
   Veraltete Kommentare und Doku: `http_client.rs:48-51` („such as a sync URL on another origin“),
   `docs/developer/desktop.html:238` + EN (Sync-Abruf unter `build_client`, seit #269 ohne Identität, `:245`),
   `connection/rdp.rs:778-780` (der Kommentar verspricht mehr, als der Test prüft).
5. **Sync-Doku und Test.** Der Klammersatz zur Webview-CSP in `docs/developer/desktop.html:247` + EN sagt, aller
   Server-Verkehr laufe über `api_proxy`. Ein Workspace ohne gespeicherte URL übernimmt aber beim ersten Speichern
   einmal eine URL aus der Oberfläche (`storage.rs:439-448`, `meta_with`), danach nur diese; von dort lädt der Sync
   (`sync.rs:11-32`). Die Doku soll das genau so sagen. Und seit #269 die drei `sync_identity_*`-Tests entfielen,
   prüft kein Test, dass der Sync-Abruf ohne Geräte-Identität läuft (`sync.rs:23`, Befund des testers zu #269).
6. **R-0748:** `forget_pin` (`tofu.rs:354-363`) verwirft den Fehler von `keyring_delete` (`:220-222`).
   `reset_server_cert_pin` (`commands.rs:91-95`) meldet Erfolg, der alte Pin bleibt im Schlüsselbund, nach dem Neustart
   wird die Verbindung wieder abgelehnt.
7. **R-0771:** `keyring_read`/`keyring_write` (`tofu.rs:210-218`) machen jeden Fehler zu `()`; nichts loggt ihn.
8. **Provisionierungsbefehl.** `TOKEN_FORM` (`ProvisioningTab.svelte:20`) lässt ein führendes `-` zu (der Server
   erzeugt `adminhelper_prov_…`, `apps/server/app/modules/provisioning/router.py:70`). `shellQuote`
   (`apps/desktop/ui/src/lib/utils/shell.ts`) ist für POSIX-Shells richtig; in fish sind innerhalb einfacher
   Anführungszeichen `\\` und `\'` Escapes, ein `\` in der Server-URL käme dort anders an. Und der Einzeiler trägt den
   Einmal-Token (`ProvisioningTab.svelte:94-99`, `--token` `:98`); er bleibt so in der Shell-History.
   `scripts/agent-install.sh` fragt ihn ohne `--token` schon heute verdeckt über `/dev/tty` ab (`:32-33`, `:306-316`).

## Ziel & Nicht-Ziele

**Ziel**
- (T1) Inventory und Playbook eines Laufs liegen in einem eigenen, exklusiv angelegten Verzeichnis im Temp-Verzeichnis
  (unter Unix Modus 0700); neben ihnen liegt nur, was der Lauf schreibt. Scheitert ein Schritt vor dem Start, entfernt
  `run` das ganze Verzeichnis, gleich welche Datei schon (halb) geschrieben war; das Linux-Skript entfernt nach dem
  Lauf das Verzeichnis. Die Pfadprüfung verlangt dieses Verzeichnis. Kein Test lässt etwas im Temp-Verzeichnis liegen.
- (T2) Der Dateiname behält nur `[A-Za-z0-9._-]`; `fetch_json` liest höchstens 16 MiB; ein Test für 2xx mit
  unpassendem Body.
- (T3) clippy `--all-targets` ohne Befund in `ansible.rs`; Kommentare und Doku wie der Code.
- (T4) Die Doku nennt die erste URL eines Workspace; ein Test pinnt den Sync ohne Geräte-Identität.
- (T5) Ein Pin-Reset, dessen Löschen im Schlüsselbund scheitert, meldet den Fehler.
- (T6) Keyring-Fehler im TOFU-Pfad stehen im Log, ohne Fingerprint.
- (T7, T8) Token-Form ohne führendes `-`; `shellQuote` gibt `\` so aus, dass POSIX-Shells und fish denselben Wert lesen.
- (T9, nach Kevins Antwort) Der Einzeiler im Provisionierungs-Tab enthält den Token nicht; das Skript fragt ihn ab.

**Nicht-Ziele**
- Windows räumt nach einem gestarteten Lauf weiter nicht auf (`docs/developer/desktop.html:114`, „Unter Windows löscht
  sie nach einem gestarteten Lauf niemand“); `%TEMP%` ist dort je Nutzer.
- Die 358 alten Dateien in `/tmp` der Dev-Box: ihre Quelle ist mit c13e2c4e behoben; wegräumen ist Handarbeit, kein Code.
- Kein Escaping in `terminal.rs` (`open_windows_terminal`): das plant `desktop-process-safety` (T1, T2); T2 hier prüft
  den Namen am Ursprung.
- `scripts/agent-install.sh` bleibt unverändert (T9 nutzt die vorhandene Abfrage). Der Befehl „Nur provisionieren“
  behält `--token`; ihn auf `--token-stdin` umzustellen braucht einen Agenten mit dieser Option (ops-install-hardening)
  und ist eine eigene Zeile.
- Keine Bestätigung der ersten URL eines Workspace durch einen nativen Dialog (sichtbares Verhalten; Offene Fragen 2).
- `docs/adr/0002-phase-a-task-plan.md:202` (in R-0817 genannt) bleibt: ein abgeschlossener Plan von 2026-06, der
  `sync.rs` als damals betroffen nennt, keine Beschreibung des heutigen Codes.
- Kein `log`-Capture-Test für T6 (kein solches Werkzeug im Desktop; reines Logging).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | desktop-rs | `ansible.rs`, `commands.rs` (Test-Helfer), `docs/developer/desktop.html` + EN, `docs/admin/ansible.html` + EN, `CHANGELOG.md` |
| T2 | desktop-rs | `ansible.rs`, `commands.rs` (Test-Auslöser), `CHANGELOG.md` |
| T3 | desktop-rs | `ansible.rs`, `http_client.rs`, `connection/rdp.rs`, `docs/developer/desktop.html` + EN |
| T4 | desktop-rs | `sync.rs`, `docs/developer/desktop.html` + EN |
| T5 | desktop-rs | `tofu.rs`, `commands.rs`, `session.rs`, `CHANGELOG.md` |
| T6 | desktop-rs | `tofu.rs` |
| T7 | desktop-ui | `ProvisioningTab.svelte`, `ProvisioningTab.test.ts` |
| T8 | desktop-ui | `shell.ts`, `shell.test.ts`, `CHANGELOG.md` |
| T9 | desktop-ui | `ProvisioningTab.svelte`, `ProvisioningTab.test.ts`, `dictionaries.ts`, `docs/admin/agent-deployment.html` + EN, `CHANGELOG.md` |

`tofu.rs`, `http_client.rs` stehen auf `scripts/dev/review-risk.txt`: T3, T5, T6 zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine Migration, kein Server-Vertrag. Tauri-Commands behalten Namen, Argumente und Antworten; `reset_server_cert_pin`
und `reset_device_identity` können zusätzlich mit einem Keyring-Fehler scheitern (die Oberfläche zeigt Fehler beider
Commands schon an: `SettingsModal.svelte:170-177`, `:195-205`, `Login.svelte:103-113`, `:136-143`). Intern ändern sich
`ansible::generate_inventory`/`write_playbook_temp` (bekommen das Laufverzeichnis) und `tofu::forget_pin` (gibt
`Result` zurück). T9 ändert den angezeigten Befehl, nicht das Skript.

## Externe Integrationen

- Ansible, Variablen relativ zu Inventory und Playbook: `docs/docsite/rst/inventory_guide/intro_inventory.rst`
  (ansible-documentation, devel; „searching paths relative to the inventory source or the playbook file“), Module und
  Plugins neben dem Playbook: `docs/docsite/rst/dev_guide/developing_locally.rst` („Ansible automatically loads all
  executable files from certain directories adjacent to your playbook or role as modules“). Gelesen 2026-10-22 über
  https://github.com/ansible/ansible-documentation (docs.ansible.com lieferte HTTP 429). Ansible ist auf der Dev-Box
  nicht installiert: am Binary nicht verifiziert.
- Windows Terminal, `;` trennt Unterbefehle: https://learn.microsoft.com/windows/terminal/command-line-arguments
  (gelesen 2026-10-22).
- fish, Escapes in einfachen Anführungszeichen (nur `\'` und `\\`): https://fishshell.com/docs/current/language.html#quotes
  (gelesen 2026-10-22); POSIX 2.2.2/2.2.1 (einfache Anführungszeichen, Backslash außerhalb):
  https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html. fish ist lokal nicht installiert: der Test
  modelliert die fish-Regel und fährt die POSIX-Rundreise über `/bin/sh` (nicht am fish-Binary verifiziert).
- reqwest `Response::chunk` und `content_length` (Feature `stream` ist aktiv, `Cargo.toml`).

## Trade-offs & Alternativen

1. **Laufverzeichnis (T1)** — (a, empfohlen) eigenes Verzeichnis je Lauf mit `std::fs::DirBuilder` (Unix `mode(0o700)`),
   `create` statt `create_all` (exklusiv), Name `adminhelper_ansible_<pid>_<n>_<nanos>`, bei `AlreadyExists` ein neuer
   Name (höchstens 16 Versuche); keine neue Crate. (b) Crate `tempfile`: neue Abhängigkeit für drei Zeilen. (c) Dateien
   weiter direkt im Temp-Verzeichnis und Ansible per `ANSIBLE_*`-Variablen einengen: ändert nichts an `group_vars/`
   neben dem Inventory. Die Pfadprüfung erkennt das Verzeichnis an Ort, Präfix und (Unix) Modus ohne Gruppen- und
   Fremdbits; ein Verzeichnis eines anderen Nutzers mit 0700 lässt sich nicht auflösen, eines mit weiteren Bits besteht
   die Prüfung nicht (so ohne `libc` für die uid).
2. **Dateiname (T2)** — Allowlist mit `_` als Ersatz (empfohlen) statt Ablehnen: ein Lauf mit Leerzeichen im Namen
   (`schemas.py:27` lässt ` ` zu) bleibt möglich. Keine Längenkappung (der Dateisystemfehler bleibt ein Fehler des Laufs).
3. **Antwortgröße (T2)** — 16 MiB: der Gateway nimmt Uploads bis 10 MiB (`apps/gateway/nginx.conf:85`), ein Playbook
   als JSON-String bleibt darunter.
4. **Sync-Doku (T4)** — (a, empfohlen) die Doku nennt die erste URL; (b) eine native Bestätigung der ersten URL:
   sichtbares Verhalten auch für Server-Workspaces, eigene Zeile (Offene Fragen 2).
5. **Pin-Reset (T5)** — Cache und Client-Cache leert `forget_pin` auch, wenn der Schlüsselbund scheitert (dieser Prozess
   pinnt beim nächsten Kontakt neu), und gibt den Fehler zurück. In `reset_device_identity_in` geht der Fehler nach dem
   Zurücksetzen der Identität zurück: die Oberfläche zeigt den Fehler, die Identität ist trotzdem weg (wie heute bei
   einem Fehler danach); der Text sagt, dass nur der Pin blieb.
6. **Token im Einzeiler (T9)** — (A, empfohlen) Einzeiler ohne `--token`, das Skript fragt; der Tab zeigt den Token mit
   Kopierknopf daneben. (B) `--token-file`/stdin in `agent-install.sh`: unter `curl … | sudo bash -s` ist stdin das
   Skript, eine Datei legt den Token auf die Platte; Änderung an einer Datei, deren PR Kevin merged. (C) so lassen.

## Risiken & Rollback

- T1 ändert, wo die Dateien liegen; der Linux-Lauf löscht mit `rm -rf --` genau das geprüfte Verzeichnis (der Pfad
  stammt aus `create_run_dir`, nie aus der Oberfläche). Rollback: Revert von T1 (T2 und T3 bauen darauf).
- T5: ein Schlüsselbund, der Löschen nicht kann, meldet jetzt einen Fehler, wo er bisher still war.
- T9: ohne Terminal (Skript in einer Pipeline) bricht der Einzeiler ab; für Massen-Rollouts bleibt der Weg mit
  `--token` (`docs/admin/agent-deployment.html:167`, Ansible/cloud-init).
- Merge-Reihenfolge mit `desktop-blocking` (T3 Signal-Test in `ansible.rs`, T9 `tofu.rs`) und `desktop-process-safety`
  (`connection/rdp.rs`): siehe Ledger.

## Doku-Impact

DE+EN: `docs/developer/desktop.html` (`:114` Laufverzeichnis, `:238` Sync, `:247` Pfadprüfung und erste URL),
`docs/admin/ansible.html` (`:67`, `:70`), bei T9 `docs/admin/agent-deployment.html` (`:44`, `:46-51`, `:52`).
CHANGELOG für T1, T2, T5, T8, T9.

## Offene Fragen

1. **T9 [?]:** Einzeiler ohne Token, das Skript fragt ihn ab (A, empfohlen) — oder `--token-file`/stdin im Skript
   (B, eigenes Vorhaben nach ops-install-hardening) — oder so lassen (C, T9 `[~]`)?
2. **T4:** Doku präzisieren (empfohlen, geplant) — oder zusätzlich eine native Bestätigung der ersten URL als neue
   Zeile?
