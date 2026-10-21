<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Fixes 2: Temp-Reste, „Passwort merken“ im Server-Modus, E2E- und Test-Fixtures — Task-Ledger
Status: aktiv · Branch: feature/desktop-fixes-2 · Review: pro Task
Spec: Roadmap R-0549, R-0553, R-0551, R-0544, R-0555 (keine eigene Datei: fünf kleine Desktop-Funde, ein Bündel der Session 2026-10-21)
Heavy: linux-full — T4 ändert die E2E-Specs der Tunnel- und Registrierungs-Journeys (`tunnel-connect.live.js`, `tunnel-start.live.js`, `settings-enroll.live.js`), die nur in der GUI-E2E des Sammellaufs laufen (`desktop_e2e_connect_tunnel.sh`, `desktop_e2e_tunnel.sh`); T2 ändert das Schreiben von `prefs.json`, `workspaces.json`, `workspace.json` und `secrets.json`, das jede Desktop-Journey nutzt; T3 ändert den RDP-Connect-Flow. Kein `scenario` (kein FRP-Datenpfad, keine PKI, kein Install); kein `windows`: der Windows-Weg des Ansible-Starts bleibt, und die neuen Rust-Tests ohne `cfg(unix)` laufen unter Windows im Job `rust-windows` der PR-CI
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: —. Zeilenangaben gelten für `origin/main@82e4a7b8` und werden beim Baustart neu gegreppt. Kein Risikopfad nach `scripts/dev/review-risk.txt` (kein `security`-Prüfer). T1 und T2 ändern denselben Absatz `docs/developer/desktop.html:114` (DE+EN) und `CHANGELOG.md`, T3 ebenfalls `CHANGELOG.md`: die Tasks bauen nacheinander.

Ziel: (1) Die Temp-Dateien eines Ansible-Laufs (Inventory und Playbook) gehen mit dem Lauf. (2) Ein abgebrochenes Schreiben von `write_json_atomic` hinterlässt keine dauerhafte Kopie im App-Datenordner. (3) Im Server-Modus legt „Passwort merken“ keinen Schlüsselbund-Eintrag mehr unter einer Client-`id` an, die der Server beim Speichern ersetzt. (4) Drei Desktop-E2E-Specs melden die Ablehnung eines Tauri-Commands so, dass ihr Text die eigene Prüfung erreicht. (5) Die Fehlertexte in den Desktop-UI-Testfixtures haben die Form, die Rust seit dem Entfernen der URL liefert.

Entscheidungen am Gate (Kevin): T3 — sichtbares Verhalten; der Plan baut die Empfehlung (im Server-Modus kein Häkchen „Passwort merken“ für eine Verbindung, die der Server noch nicht führt; lokal und Sync unverändert). T5 — die Zeile R-0555 ist `neu`: sie gilt erst, wenn Kevin sie annimmt und freigibt; sonst wird T5 `[~]`.

### T1 — Ansible-Temp-Dateien nach dem Lauf löschen (R-0549)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, docs/admin/ansible.html, docs/en/admin/ansible.html, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @35de17ae 2026-10-21T10:02:55+02:00
Review: approve (.ah-out/review/desktop-fixes-2/T1.verdict.json)
Änderung: Der Befehl, den `launch_ansible` (`ansible.rs:144`) unter Linux dem Terminal gibt (`bash -c`, `:165-178`), löscht Inventory und Playbook (beide über `shell_escape`), sobald `ansible-playbook` endet, gleich mit welchem Exit-Code, und ebenso, wenn die Shell vorher endet, weil das Terminal während des Laufs geschlossen wird (SIGHUP): etwa ein `trap` auf HUP/INT/TERM, der `exit` ruft, und ein EXIT-Trap, der löscht; laut Bash-Handbuch („Signals“) läuft ein Trap erst nach dem Ende des Vordergrundbefehls. Den Befehlstext baut eine eigene Funktion, damit ein Test ihn ausführen kann; die Zeile „Ansible beendet. Druecke Enter zum Schliessen.“ bleibt. Scheitert der Start nach der Pfadprüfung (`is_confined_ansible_path`, `:124`; kein `ansible-playbook`, kein Terminal), löscht `launch_ansible` beide Dateien, bevor es den Fehler zurückgibt; Pfade, die die Prüfung nicht bestehen, löscht es nie. Der Windows-Weg (`:156-164`) startet unverändert: Ansible läuft ohne WSL nicht als Steuerknoten unter Windows (ansible-documentation, `installation_guide/intro_installation.rst`: „Windows without WSL is not natively supported as a control node“). Nicht Teil der Task: scheitert `ansible_write_playbook` nach dem Inventory (`stores/ansible.ts:145-146`), bleibt das Inventory liegen. Der Test `generate_inventory_rejects_host_and_group_injection` (`:191`) löscht die Inventory-Datei seines gültigen Falls (`:211`). Tests (`#[cfg(unix)]`, zuerst rot): der Befehlstext mit einem Stub-`ansible-playbook` in einem eigenen PATH-Verzeichnis (nur in der Umgebung des Kind-`Command`, nie global) und stdin `null` ausgeführt → beide Dateien weg, bei Exit 0 und bei Exit 2; ein Stub, der schläft, und SIGHUP an die Prozessgruppe (`process_group(0)`, erst nachdem der Stub eine Marke geschrieben hat) → beide Dateien weg; ein gescheiterter Start über eine eingespeiste Start-Funktion (nicht über PATH) → beide Dateien weg; ein Pfad, der die Prüfung nicht besteht → die Datei bleibt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible::
Doku: docs/admin/ansible.html + docs/en/admin/ansible.html (`:67`: nach dem Lauf löscht das Terminal Playbook- und Inventory-Datei, ein gescheiterter Start ebenso) · docs/developer/desktop.html + docs/en/developer/desktop.html (`:114`, letzter Satz zu den Ansible-Temp-Dateien: wer sie wann löscht) · CHANGELOG.md (Fixed)
Beweis: builder desktop-workspaces T9, 2026-10-19 · Code-Lesung origin/main@82e4a7b8 — `create_temp_file` (`ansible.rs:21-31`) legt die Dateien an; nichts in `ansible.rs`, `commands.rs:636-651` oder `stores/ansible.ts:145-147` löscht sie, jeder Lauf lässt zwei Dateien im System-Temp. Der erste Test der Task ist auf HEAD rot (mit dem heutigen Befehlstext bleiben beide Dateien)
Semantik: docs/admin/ansible.html:67 — „schreibt ihn in eine temporäre Datei, generiert das Inventory und startet den Lauf“: temporär, also für den Lauf; keine Stelle sagt, wann die Dateien gehen
Dedup-Key: bug:desktop:ansible.rs:temp-cleanup
HEAD: 82e4a7b8

### T2 — Verwaiste Temp-Dateien von write_json_atomic abräumen (R-0553)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/storage.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @c13e2c4e 2026-10-21T10:10:07+02:00
Review: approve (.ah-out/review/desktop-fixes-2/T2.verdict.json)
Änderung: `write_json_atomic` (`storage.rs:112`) löscht vor dem Schreiben im Verzeichnis der Zieldatei die Temp-Dateien früherer Schreibvorgänge derselben Datei (`<Dateiname>.<Ziffern>.tmp`, die Form von `:118-120`), deren Änderungszeit mindestens eine feste Frist zurückliegt (Konstante, Vorschlag 10 Minuten; ein Schreiben dauert Millisekunden bis Sekunden). Eine jüngere (ein anderer Prozess schreibt gerade), eine mit unlesbarer oder künftiger Änderungszeit und jede andere Datei bleiben; ein Fehler beim Löschen (unter Windows etwa eine geöffnete Datei) wird ignoriert. Muster wie `sweep_stale_rdp_files` (`connection/rdp.rs:672`), aber im Zweifel behalten statt löschen. Die festen Namen `prefs.json.tmp` und `workspaces.json.tmp` räumt weiter die Migration (`migration.rs:162-167`). Test (Name enthält `write_json_atomic`, zuerst rot): Zieldatei `prefs.json` in einem Scratch-Verzeichnis, daneben `prefs.json.4242.tmp` mit einer Änderungszeit eine Stunde zurück (`File::set_modified`), `prefs.json.4243.tmp` frisch, `other.json.4242.tmp` alt und `prefs.json.tmp` alt → nach `write_json_atomic` ist nur `prefs.json.4242.tmp` weg, die Zieldatei hat den neuen Inhalt. `write_json_atomic_replaces_the_file_whole_and_leaves_no_temp` (`:1491`) bleibt grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- write_json_atomic
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:114`, nach „Temp-Datei mit pid, `sync_all`, Umbenennen“: die Temp-Datei eines abgebrochenen Schreibens räumt das nächste Schreiben derselben Datei ab, sobald sie älter als die Frist ist) · CHANGELOG.md (Fixed)
Beweis: builder R-0431 T36, 2026-10-20 · Code-Lesung origin/main@82e4a7b8 — `storage.rs:121-127` löscht die Temp-Datei nur, wenn Schreiben oder Umbenennen im selben Prozess scheitern; endet der Prozess dazwischen, löscht sie niemand, denn `migration.rs:162-167` nimmt nur die festen Namen. Der Test der Task ist auf HEAD rot (`prefs.json.4242.tmp` bleibt)
Semantik: docs/developer/desktop.html:114 — „ersetzt der Desktop auf allen Plattformen auf einmal (Temp-Datei mit pid, `sync_all`, Umbenennen)“: die Temp-Datei ist ein Mittel des Ersetzens; keine Stelle sieht vor, dass sie bleibt
Dedup-Key: bug:desktop:storage.rs:write_json_atomic-pid-temp
HEAD: 82e4a7b8

### T3 — Server-Modus: „Passwort merken“ nur für Verbindungen, die der Server führt (R-0551)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Änderung: `handleRdpAuth` (`connectFlow.ts:152`) erlaubt das Merken (`requestPassword(…, allowRemember)`, `:167`) im Server-Modus nur, wenn die Verbindung in der Liste steht (`connections`-Store, gleiche `id`), also schon vom Server kommt. Eine noch nicht gespeicherte (Editor, „Verbinden“ vor „Speichern“, `ConnectionEditor.svelte:84-92`) bekommt den Dialog ohne Häkchen; das getippte Passwort gilt nur für diesen Start, und `save_password` wird auch dann nicht gerufen, wenn das Ergebnis des Dialogs `remember` trägt (`:171`). Lokal und Sync bleiben unverändert. Gebaut wird die Empfehlung aus den Entscheidungen am Gate; entscheidet Kevin anders, passt die Task Änderung und Tests an. Tests in `connectFlow.test.ts` (zuerst rot), im Aufbau von „RDP start after the prompt remembers the password“ (`:319`, frischer Modulgraph mit `__TAURI_INTERNALS__`): Server-Modus mit `storePasswords`, Verbindung nicht in der Liste, der Dialog meldet `remember: true` → `requestPassword` mit `allowRemember` `false`, kein `save_password`, Start mit dem getippten Passwort über `open_connection`; dieselbe Verbindung in der Liste → `allowRemember` `true` wie bisher; lokaler Modus, Verbindung nicht in der Liste → `true` wie bisher.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:268`, Connect-Flow Schritt 2, „wahlweise mit Speichern über `save_password`“: im Server-Modus nur für eine Verbindung, die der Server schon führt) · CHANGELOG.md (Fixed)
Beweis: reviewer desktop-hardening T5, Session adminhelper-fe 2026-10-19 · Code-Lesung origin/main@82e4a7b8 — `connectFlow.ts:167` erlaubt das Merken immer; `emptyConnection` (`models/connection.ts:104`) gibt einer neuen Verbindung eine Client-UUID, `rdp_storage_key` (`password.rs:48-53`) nimmt diese `id` in den Schlüssel, und `upsert` legt im Server-Modus (`stores/connections.ts:168-176`) die Verbindung ohne `id` an (`toServerPayload`, `:147-162`), der Server vergibt eine eigene. Der erste Test der Task ist auf HEAD rot (`allowRemember` ist `true`, `save_password` wird gerufen)
Semantik: docs/developer/desktop.html:198 — „`<id>` ist die `id` der Verbindung … und gehört damit zu genau einer Verbindung eines Workspace“: ein Eintrag unter der Client-UUID gehört nach dem Speichern zu keiner
Dedup-Key: bug:desktop:ConnectionEditor.svelte:remember-unsaved-server-id
HEAD: 82e4a7b8

### T4 — Desktop-E2E: Ablehnungen aus executeAsync als { rejected } (R-0544)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/tunnel-connect.live.js, apps/desktop/e2e/test/specs/tunnel-start.live.js, apps/desktop/e2e/test/specs/settings-enroll.live.js, apps/desktop/e2e/eslint.config.js
Änderung: Die drei Helfer melden eine Ablehnung als `{ rejected: <Text> }` statt `{ error: … }`, wie `logout.live.js:17-25` und `workspace-picker.live.js:27-40`: `invoke` in `tunnel-connect.live.js:33-47` (die Prüfung `:45` liest `out.rejected`); `tunnelStatus` in `tunnel-start.live.js:27-35` (eine Ablehnung lässt den Spec mit ihrem Text scheitern, statt ein Objekt zu liefern, das `toMatchObject` vergleicht); `invoke` in `settings-enroll.live.js:24-36` (samt Kommentar `:24`). `eslint.config.js` bekommt `no-restricted-syntax` mit dem Selektor `CallExpression[callee.name='done'] > ObjectExpression > Property[key.name='error']` und einer Meldung, die den Grund nennt (webdriver wertet ein Skriptergebnis mit `error`-Schlüssel als gescheiterten Befehl); damit ist der Lint auf HEAD rot (drei Treffer) und danach grün. Das Verify ist Lint und Unit-Tests der E2E (`npm run lint`); ob die Specs auf dem echten Stack laufen, zeigt der Sammellauf.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Beweis: builder+reviewer R-0430 T16, 2026-10-19 · `isSuccessfulResponse` in `webdriver/build/node.js:1384-1409` (webdriver 9.29.0, installiert im Haupt-Checkout): ein `value`, das ein Objekt mit Schlüssel `error` ist, gilt als gescheitert (`:1398`), der Befehl wird wiederholt (`:2272`) und wirft `WebDriverError`; `tunnel-connect.live.js:45` erreicht seinen eigenen Text nie. Code-Lesung origin/main@82e4a7b8: drei Treffer für `done({ error` unter `apps/desktop/e2e/test/`
Orakel: analyzer — die ESLint-Regel, auf HEAD rot mit drei Treffern
Metrik: `grep -rn 'done({ error' apps/desktop/e2e/test | wc -l` 3 → 0 (GNU grep)
Dedup-Key: ref:desktop-e2e:specs:executeasync-error-key
HEAD: 82e4a7b8

### T5 — Desktop-UI-Testfixtures im Fehlerformat ohne URL (R-0555)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/errors.test.ts, apps/desktop/ui/src/components/Login.pin.test.ts, apps/desktop/ui/src/lib/stores/statusBar.test.ts, apps/desktop/ui/src/components/NotificationPrefs.test.ts, apps/desktop/ui/src/lib/stores/ansible.pipeline.test.ts, apps/desktop/ui/src/lib/stores/monitoring.test.ts
Änderung: Die Fixture-Texte und die daraus erwarteten Texte nennen den Netzwerkfehler so, wie Rust ihn seit `error.rs:112` (`without_url`) liefert: `error sending request: client error (Connect): …` statt `error sending request for url (<URL>): client error (Connect): …` (reqwest 0.12.28, `src/error.rs:231` und `:267`: „for url (…)“ folgt nur bei gesetzter URL). Frisch gegrept, mehr Stellen als die Zeile nennt: `errors.test.ts:20`, `Login.pin.test.ts:17,19`, `statusBar.test.ts:37,42`, `NotificationPrefs.test.ts:103,106`, `ansible.pipeline.test.ts:123,126`, `monitoring.test.ts:153,156`. Nur dieses Präfix ändert sich; Assertions, Testnamen und Produktcode bleiben. Mechanisch, daher eine Task über sechs Dateien.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/utils/errors.test.ts src/components/Login.pin.test.ts src/lib/stores/statusBar.test.ts src/components/NotificationPrefs.test.ts src/lib/stores/ansible.pipeline.test.ts src/lib/stores/monitoring.test.ts
Doku: keine (Test)
Beweis: security-Prüfer desktop-hardening T1, 2026-10-19 (Nit) · Code-Lesung origin/main@82e4a7b8: `grep -rn 'error sending request for url' apps/desktop/ui/src` → 11 Zeilen in 6 Dateien
Metrik: `grep -rn 'error sending request for url' apps/desktop/ui/src | wc -l` 11 → 0 (GNU grep); dazu die gezielten Suiten vor und nach dem Diff grün (beide Summary-Zeilen)
Dedup-Key: ref:desktop-ui:tests:reqwest-error-fixtures
HEAD: 82e4a7b8

### T6 — ConnectionEditor: „zuletzt benutzt“ als Wert, nicht in Großbuchstaben (R-0564)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.lastused.test.ts
Änderung: Die Wertanzeige „zuletzt benutzt“ (`ConnectionEditor.svelte:227-230`) steht in einem `.field` und erbt dessen `text-transform: uppercase` und `letter-spacing` (Beschriftungs-Stil, `app.css` `.field`). Sie bekommt wie die Wertanzeigen aus R-0431 T54 (`Login.svelte` `.login-url`, `SettingsModal.svelte` `.sm-workspace-url`) `text-transform: none; letter-spacing: normal` (inline neben dem vorhandenen `style="color: var(--text-muted)"` oder als eigene Klasse; jsdom muss den Stil per `getComputedStyle` sehen) und ein `data-testid`. Neuer Test (SPDX-Kopf): Der Editor einer Verbindung mit `lastUsed` zeigt den Wert, und dessen berechneter `text-transform` ist `none`; zuerst rot.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.lastused.test.ts
Doku: keine (Darstellung)
Beweis: Code-Lesung `ConnectionEditor.svelte:227-230` an 82e4a7b8; Bau R-0431 T54 (2026-10-21) belegt dieselbe Vererbung im WebKitWebDriver-Lauf
Semantik: R-0431 T54 („Feste URL und Werte im Formular nicht in Großbuchstaben“): Werte stehen in Originalschreibung, nur Beschriftungen in Großbuchstaben
Dedup-Key: bug:desktop-ui:ConnectionEditor.svelte:last-used-uppercase
HEAD: 82e4a7b8

### T7 — E2E-Skript connect_tunnel: Container vor dem Start zum Aufräumen eintragen (R-0563)  [ ]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_connect_tunnel.sh
Änderung: `desktop_e2e_connect_tunnel.sh` trägt seine Container erst nach erfolgreichem `docker run -d` in `TARGETS` ein (`:78` SSH, `:93` Web, `:102` RDP, `:142` frpc); scheitert das Veröffentlichen eines Ports, legt docker den Container trotzdem an, und die Aufräum-Falle (`:36`) erreicht ihn nie. Neu steht `TARGETS+=("$X")` vor dem jeweiligen `docker run`, wie in `desktop_e2e_workspaces.sh:101`/`:135` („before the start, as the SSH target's“). Kein neuer registrierter Test (die Registrierung in `scripts/tests/run.sh` wäre ein Harness-Pfad); Beleg im Commit-Body: je Container steht die Zeile `TARGETS+=` vor dem `docker run` (grep mit Zeilennummern vorher und nachher), der echte Lauf erfolgt in der Desktop-E2E des Sammellaufs. `shellcheck` bleibt sauber.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test-Hygiene)
Beweis: Review R-0431 T32 (2026-10-20), Code-Lesung `desktop_e2e_connect_tunnel.sh:32-142` gegen `desktop_e2e_workspaces.sh:54-135` an 82e4a7b8
Semantik: `desktop_e2e_workspaces.sh:135` (Kommentar „before the start“): ein Test hinterlässt keine Container auf der Test-Box
Dedup-Key: ref:scripts:desktop_e2e_connect_tunnel.sh:targets-before-run
HEAD: 82e4a7b8
