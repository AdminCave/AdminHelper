# Ansible erreicht Server wie Verbinden — Task-Ledger
Status: aktiv · Branch: feature/kern-ansible-1 · Review: pro Task
Spec: docs/features/kern-ansible-1.md (Roadmap R-1202, R-1204)
Heavy: none — kein Stack-, Gateway-, PKI- oder Install-Pfad und keine Desktop-Journey, die ein Live-Spec faehrt (die E2E-Box hat kein Ansible); Format-Beleg mit ansible-inventory aus einer Wegwerf-Venv
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1202: Inventar als JSON mit dem SSH-Ziel der Verbindung, geprüft wie Verbinden  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/ssh.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @0beb2eb1e 2026-11-09T12:29:03+01:00
Review: approve (.ah-out/review/kern-ansible-1/T1.verdict.json)
Änderung: `AnsibleTarget` bekommt `connection: Option<Connection>` (aufgelöst von der UI). Rust prüft jede Verbindung mit `validate_connection_input`, verlangt den Typ SSH und ruft `reject_foreign_port` auf, alles vor dem Schreiben. `generate_inventory` schreibt `inventory.json`: `all.hosts` mit dem Hostnamen als Alias, `children` je Tag, Hostvars `ansible_host`, `ansible_port`, `ansible_user` und `ansible_ssh_private_key_file`. Die übrigen Schalter aus `base_args(terminal=false)` gehen gequotet in `ansible_ssh_common_args`, der Sprung-Host als `-o ProxyJump=`. Ohne Verbindung bleibt es beim Hostnamen. Tests: Hostvars und Gruppen; Quoting rund (shlex-Gegenprobe); fremder Port abgelehnt; Nicht-SSH abgelehnt; ungültige Werte abgelehnt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T2 — R-1202: UI wählt und löst die SSH-Verbindung je Server auf  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/ansible.ts, apps/desktop/ui/src/lib/models/ansible.test.ts, apps/desktop/ui/src/lib/stores/ansible.ts, apps/desktop/ui/src/lib/stores/ansible.test.ts, apps/desktop/ui/src/pages/Ansible.svelte, apps/desktop/ui/src/pages/Ansible.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @eda415c17 2026-11-09T12:50:16+01:00
Review: approve (.ah-out/review/kern-ansible-1/T2.verdict.json)
Änderung: Je gewähltem Server die SSH-Verbindungen (`serverId`) finden: genau eine wird genommen; ohne Verbindung gilt der Hostname, und die Ansicht markiert ihn; bei mehreren gibt es eine Auswahl je Server, vorbelegt mit der ersten nach Namen. Vor dem Start `resolveConnection` je Ziel. Bleibt eine STCP-Verbindung ohne laufenden Visitor unaufgelöst, wird der Start mit dem Servernamen abgelehnt. Das Ziel geht mit `connection` an Rust. Texte DE+EN. Tests für die drei Fälle, die Ablehnung und die Vorbelegung.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T4
Abhängt von: T1

### T3 — R-1204: Ansible fragt das SSH-Passwort ab  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/commands.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @90098c0f5 2026-11-09T12:57:36+01:00
Review: approve (.ah-out/review/kern-ansible-1/T3.verdict.json)
Änderung: Nutzt ein Ziel `SshAuthMethod::Password`, bekommt `playbook_args` den Schalter `--ask-pass`. Das gilt für das OS-Terminal und für das eingebettete Terminal; `linux_run_script` nutzt dieselben Argumente. Tests: Schalter genau bei einem Passwort-Ziel, in beiden Startwegen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4
Abhängt von: T1

### T4 — Doku Ansible-Ziele (DE+EN), Changelog  [x]
Komponente: desktop-ui · Dateien: docs/admin/ansible.html, docs/en/admin/ansible.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-ansible-1.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @084065873 2026-11-09T13:08:10+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Die Abschnitte „Inventory-Generierung“ (JSON, Hostvars, Beispiel mit RFC-5737-Adressen) und „SSH-Erreichbarkeit“ beschreiben das Ziel wie Verbinden: Tunnel, Auswahl je Server, Markierung „Hostname“, Ablehnung ohne Visitor und, falls T3 gebaut ist, die Passwort-Abfrage. Die Ansible-Zeile der Command-Tabelle in `desktop.html` wird angepasst. Changelog unter `### Fixed`, in ASCII.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/ansible.html, docs/en/admin/ansible.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-ansible-1.md
Task-Review: am Ende
Abhängt von: T2

### T5 — R-1204: Mit `--ask-pass` melden sich nur Passwort-Ziele per Passwort an  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @3436658c1 2026-11-09T13:25:30+01:00
Review: approve (.ah-out/review/kern-ansible-1/T5.verdict.json)
Änderung: Fund der Abschlussprüfung (security, branch). Hat der Lauf `--ask-pass` (`asks_password`), bekommt jedes Ziel, dessen Verbindung nicht `SshAuthMethod::Password` nutzt, und jedes Ziel ohne Verbindung in `ansible_ssh_common_args` `-o PasswordAuthentication=no -o KbdInteractiveAuthentication=no`. Ohne `--ask-pass` bleibt das Inventar wie bisher. Test in `generate_inventory`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (Verhalten wie dokumentiert: das Passwort gilt den Passwort-Servern des Laufs)
Abhängt von: T3

### T6 — README: Ansible-Inventar als JSON  [x]
Komponente: desktop-ui · Dateien: README.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @439d32f48 2026-11-09T13:30:03+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Fund der Abschlussprüfung (reviewer, branch): README.md beschreibt noch ein INI-Inventar. Der Satz nennt `inventory.json`, das Ziel wie Verbinden und `--ask-pass` bei Passwort-Zielen, mit Verweis auf docs/en/admin/ansible.html.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: README.md
Task-Review: am Ende
Abhängt von: T4

### T7 — Doku: das abgefragte Passwort gilt nur den Passwort-Servern  [ ]
Komponente: desktop-ui · Dateien: docs/admin/ansible.html, docs/en/admin/ansible.html, changelog.d/kern-ansible-1.md
Änderung: Fund der security-Folgerunde (nit): Nach T5 gilt das Passwort nur den Servern des Laufs mit Passwort-Anmeldung, nicht allen; Callout DE+EN und Changelog entsprechend.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/ansible.html, docs/en/admin/ansible.html, changelog.d/kern-ansible-1.md
Task-Review: am Ende
Abhängt von: T5

## Entscheidungen
- T1: Format-Beleg mit ansible-core 2.22.0 aus einer Wegwerf-Venv (2026-11-09): `ansible-inventory -i inventory.json --list` liest das Inventar aus dem Test `generate_inventory_sends_ansible_where_the_connection_goes` (Gruppe `web`, Hostvars, IPv6 ohne Klammern); shlex teilt `ansible_ssh_common_args` in genau die Schalter zurück; `ansible -m ping -vvv` baut `-o Port=23001 -o 'IdentityFile="/home/me/.ssh/id ed25519"' … -o ProxyJump=jump@192.0.2.10`.
- T1: Ansible setzt `PreferredAuthentications` selbst und vor `ansible_ssh_common_args`; ssh nimmt den ersten Wert, unser Wert aus der Auth-Methode wirkt dort also nicht. Hingenommen: `IdentitiesOnly` und der Schlüssel wirken weiter, eine Passwort-Abfrage regelt `--ask-pass` (T3). Mit `--ask-pass` setzt Ansible diese Schalter nicht, dort wirken unsere Werte (Probe des T3-Prüfers mit ansible-core 2.22.0).
- T1: Ein Tag `all` wird keine Kindgruppe: das yaml-Plugin bricht dann mit „can't add group to itself“ ab, und Ansible fällt still auf das ini-Plugin zurück (mit ansible-core 2.22.0 geprobt); derselbe Hostname mit verschiedenen Zielen wird abgelehnt statt still eines zu nehmen.
- T1: Der Port-Guard (`reject_foreign_port` je Verbindung) läuft vor dem Abruf des Playbooks, damit ein abgelehnter Lauf den Server nicht fragt.
- T3: Frage beantwortet in der Notiz von R-1204 (Kevin 2026-11-09): `--ask-pass`, Abfrage im Terminal wie bei Verbinden, ein Passwort je Lauf.
- T5: Ein Ziel ohne Verbindung bekommt in einem `--ask-pass`-Lauf eine eigene `ansible_ssh_common_args`; sie ersetzt für diesen Host ein `ssh_common_args` aus einer eigenen `ansible.cfg`. Hingenommen (nur Läufe mit Passwort- und Hostname-Ziel zugleich und eigener Config); Hinweis des T5-Prüfers.
