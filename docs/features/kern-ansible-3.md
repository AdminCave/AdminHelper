# kern-ansible-3: Ansible-Läufe über Sprung-Hosts, SSH-Optionen je Bein

Roadmap: R-1214 (Variante b, Kevin 2026-11-11).

## Problem / Motivation

Ein Ansible-Lauf mit `--ask-pass` gibt die SSH-Schalter einer Verbindung über `ansible_ssh_common_args` an das
Ziel-Bein. Bei einem Sprung-Host (`-o ProxyJump=…` aus der Verbindung oder `ProxyJump` aus `~/.ssh/config`) baut
ssh das Bein zum Sprung-Host selbst, und zwar ohne diese `-o`-Schalter. Die Anmelde-Optionen des Laufs gelten dort
also nicht. Einzelheiten stehen in `tasks/private/`.

OpenSSH (`ssh.c`, Umwandlung von `jump_host` in `proxy_command`) gibt dem Sprung-ssh nur `-l`, `-p`, `-J`, `-F` und
`-v` mit, kein `-o`. In `readconf.c` gilt `parse_jump()` nur, solange weder `proxy_command` noch `jump_host`
gesetzt ist: Ein `-o ProxyCommand=…` auf der Kommandozeile hat also Vorrang vor einem `ProxyJump` aus der
Konfiguration. Beides ist im Quelltext gelesen (openssh-portable master, 2026-11-11).

## Ziel & Nicht-Ziele

- **Ziel:** In einem Lauf mit `--ask-pass` läuft jedes Sprung-Bein über ein eigenes `ProxyCommand`. Es ist ein
  `ssh -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no … -W [%h]:%p <hop>`, bei Ketten verschachtelt
  je Bein. Das gilt für den Sprung-Host der Verbindung und für `ProxyJump` aus der SSH-Konfiguration (`ssh -G`),
  für das Ziel ebenso wie für den ersten Hop der Kette (ssh liest die Konfiguration nur für das erste Bein).
- Ohne `--ask-pass` bleibt alles wie heute (`-o ProxyJump=…`).
- **Nicht-Ziele:**
  - Ein eigenes `ProxyCommand` aus `~/.ssh/config` umbauen. Es bleibt wie konfiguriert und wird in der Doku genannt.
  - `ssh_args` aus `ansible.cfg` oder `ANSIBLE_SSH_ARGS`.
  - Verbinden (Terminal-Sitzung) ändern.

## Betroffene Komponenten & Dateien

- `apps/desktop/src-tauri/src/ansible.rs`:
  - `host_vars` (heute `ansible.rs:282`) und `generate_inventory` (`ansible.rs:241`).
  - Neuer Baustein für die `ProxyCommand`-Kette.
  - Auflösung über `ssh -G` für Ziele, deren eigene Verbindung keinen Sprung-Host hat.
- Gelesen, nicht geändert: `apps/desktop/src-tauri/src/connection/ssh.rs` (`option_switches`, `ssh.rs:103`) und
  `apps/desktop/src-tauri/src/validation.rs` (`JUMP_RE`, `validation.rs:142`), mit dem auch die Hops aus `ssh -G`
  geprüft werden.
- Doku: `docs/admin/ansible.html`, `docs/en/admin/ansible.html`, `changelog.d/kern-ansible-3.md`.

## Datenmodell / API / Migrationen

Keine. Tauri-Commands und Inventarformat bleiben; nur der Wert von `ansible_ssh_common_args` in Läufen mit
`--ask-pass` und Sprung-Host ändert sich.

## Externe Integrationen

- OpenSSH `ssh_config(5)`:
  - `ProxyCommand` expandiert `%h` und `%p`. Ein inneres `ProxyCommand` steht im äußeren daher mit `%%h` und `%%p`.
  - Der Befehl läuft über die Shell (`exec …`), jeder Wert wird shell-gequotet.
- Quelltext: <https://github.com/openssh/openssh-portable> (`ssh.c`, `readconf.c`).
- Ansible teilt `ansible_ssh_common_args` mit `shlex` und gibt es an ssh, sftp und scp. Das `ProxyCommand` ist
  dort ein einziges gequotetes Argument.

## Trade-offs & Alternativen

Gewählt hat Kevin am 2026-11-11 Variante (b). Verworfen:
- (a) Hinnehmen.
- (c) Läufe mit `--ask-pass` und Sprung-Host ablehnen.
- Eine eigene `-F`-Datei für den Lauf: Sie ersetzt die Nutzer- und Systemkonfiguration ganz und änderte damit mehr,
  als nötig ist.

Bricht `ssh -G` ab oder liefert einen Hop, den `JUMP_RE` ablehnt, startet der Lauf nicht (fail closed), und die
Meldung nennt das Ziel.

## Risiken & Rollback

- **Quoting über drei Ebenen** (shlex, Shell, `%`-Expansion): Unit-Tests prüfen die Kette, ein Test mit dem echten
  `ssh -G` prüft, dass ssh `proxycommand` und kein `proxyjump` sieht (nur Unix).
- **`ssh -G` je Ziel** kostet einen Prozess je Host, nur in Läufen mit `--ask-pass`.
- **Rollback:** Revert der Task-Commits.

## Doku-Impact

`docs/admin/ansible.html` und `docs/en/admin/ansible.html` nennen im Abschnitt zum Inventar und zur
SSH-Erreichbarkeit das `ProxyCommand` bei `--ask-pass` sowie den Rest: ein eigenes `ProxyCommand` aus der
Konfiguration. Dazu kommt ein neutraler CHANGELOG-Eintrag.

## Offene Fragen

Keine. Die Variante hat Kevin entschieden.
