# Ansible erreicht Server wie Verbinden (kern-ansible-1)

Roadmap: R-1202 (BUG), R-1204 (BUG). Kevins Vorgaben vom 2026-11-09 stehen in den Notizen beider Zeilen.

## Problem / Motivation

- **R-1202:** `ansible.rs::generate_inventory` schreibt nur `hostname` und die Tags der gewählten Server in eine
  INI-Datei. Port, Benutzer und Schlüssel der SSH-Verbindung des Servers bleiben ungenutzt, ebenso ihre Optionen
  (Sprung-Host, Auth-Methode) und der FRP-Tunnel. Ein Server, der nur über einen STCP-Tunnel erreichbar ist oder
  dessen Hostname der Client nicht auflöst, ist für Ansible unerreichbar. Verbinden (SSH) erreicht denselben Server.
- **R-1204:** Bei einer SSH-Verbindung mit Passwort-Authentifizierung fragt Verbinden das Passwort im Terminal ab.
  `ansible-playbook` bekommt kein `--ask-pass` und scheitert deshalb.

## Ziel & Nicht-Ziele

Ziel: Für jeden gewählten Server läuft Ansible gegen dasselbe Ziel, das Verbinden (SSH) für die SSH-Verbindung
dieses Servers öffnet. Das umfasst Adresse und Port nach der Tunnel-Auflösung, den Benutzer, den Schlüssel und die
ssh-Schalter der Verbindung.

Auswahl der Verbindung je Server:

| SSH-Verbindungen des Servers | Ziel |
|---|---|
| genau eine | diese |
| keine | der Hostname wie bisher; die Ansible-Ansicht markiert den Server |
| mehrere | Auswahl je Server, vorbelegt mit der ersten nach Namen |

Ist der Tunnel-Visitor einer STCP-Verbindung nicht gestartet, lehnt die UI den Start mit dem Namen dieses Servers ab.
Es gibt keinen Rückfall auf den Hostnamen. Das Inventar ist JSON (`inventory.json`), gelesen vom yaml-Plugin, das in
Ansible standardmäßig aktiv ist. Der Alias jedes Hosts bleibt sein Hostname, damit Playbooks, `host_vars` und
Ausgaben dieselben Namen sehen wie bisher.

Nicht-Ziele:
- kein Weg über Windows: Windows bleibt unverändert, Ansible läuft dort ohnehin nicht nativ;
- kein `HostKeyAlias`, weil die Visitor-Ports in der Port-Registry fest sind;
- keine eigene Passwort-Abfrage in der UI;
- keine Änderung an Server-API oder Playbook-Verwaltung.

## Betroffene Komponenten & Dateien

- **desktop-rs:**
  - `apps/desktop/src-tauri/src/ansible.rs`: `AnsibleTarget` bekommt `connection: Option<Connection>`; die
    Inventar-Erzeugung schreibt JSON mit Hostvars.
  - `apps/desktop/src-tauri/src/commands.rs`: `ansible_run`, `terminal_open_ansible` und `ansible_run_with` prüfen
    jede Verbindung mit `validate_connection_input`, verlangen den Typ SSH und rufen `reject_foreign_port` auf.
  - `apps/desktop/src-tauri/src/connection/ssh.rs`: eine `pub(crate)`-Funktion für die Schalter einer Verbindung
    ohne Terminal (`base_args(terminal=false)`); der Sprung-Host geht als `-o ProxyJump=…` hinein.
- **desktop-ui:**
  - `lib/models/ansible.ts` (`buildAnsibleTargets`) und `lib/stores/ansible.ts`: Auswahl der Verbindung,
    `resolveConnection` je Server, Ablehnung bei fehlendem Visitor;
  - `pages/Ansible.svelte`: Markierung „Hostname“ und die Auswahl je Server;
  - `lib/bridge/index.ts` (Typen) und `lib/i18n/dictionaries.ts` (DE+EN).

## Datenmodell / API / Migrationen

Keine Server-API und keine Migration. Der Tauri-Vertrag wächst um ein optionales Feld `connection` je Ziel. Ein
Aufrufer ohne dieses Feld bekommt das bisherige Verhalten, den Hostnamen.

Hostvars je Host mit Verbindung:
- `ansible_host` und `ansible_port`;
- `ansible_user`, falls gesetzt;
- `ansible_ssh_private_key_file`, falls gesetzt;
- `ansible_ssh_common_args`: die übrigen Schalter, für Ansibles shlex-Aufteilung gequotet.

## Externe Integrationen

- Ansible yaml-Inventar-Plugin: Standard-Endungen `.yaml`, `.yml`, `.json`, standardmäßig aktiviert
  (https://docs.ansible.com/ansible/latest/collections/ansible/builtin/yaml_inventory.html, gelesen 2026-11-09).
- ssh-Connection-Plugin: `ansible_host`, `ansible_port`, `ansible_user`, `ansible_ssh_private_key_file`,
  `ansible_ssh_common_args`; Passwort per `--ask-pass`. `password_mechanism` steht laut aktueller Doku standardmäßig
  auf `ssh_askpass`, ältere Versionen brauchen `sshpass`
  (https://docs.ansible.com/ansible/latest/collections/ansible/builtin/ssh_connection.html, gelesen 2026-11-09).

## Trade-offs & Alternativen

- **JSON statt INI** (Kevins Vorgabe): Werte mit Leerzeichen und Quotes, etwa in `ansible_ssh_common_args`, lassen
  sich in INI nicht sauber escapen; JSON baut `serde_json`.
- **Auflösung in der UI, Prüfung in Rust** (Kevins Vorgabe): Das ist derselbe Weg wie bei Verbinden. Rust traut
  dem Webview nicht und prüft deshalb jede Verbindung wie `terminal_open_ssh`.
- **R-1204, Passwort:** Empfehlung `--ask-pass`, sobald ein Ziel Passwort-Authentifizierung nutzt. Die Abfrage
  kommt im Terminal wie bei Verbinden, ein Passwort je Lauf. Alternative: Server mit Passwort-Verbindung ablehnen.
  Offene Frage an Kevin, siehe unten.

## Risiken & Rollback

- Ein Ziel mit fremdem Loopback-Port muss abgelehnt werden. Das prüft `reject_foreign_port`; ein Test belegt es.
- Ändert ein Wert aus der Verbindung die ssh-Kommandozeile: Die Werte sind durch `validate_connection_input` geprüft
  und gehen gequotet in `ansible_ssh_common_args`. Ein Test prüft mit einem Leerzeichen-Pfad, dass shlex sie
  zurückgewinnt.
- Rollback: Revert des Merge-Commits; der Tauri-Vertrag ist abwärtskompatibel.
- Restrisiko: Es gibt keinen Live-E2E-Test mit echtem `ansible-playbook`, denn die Desktop-E2E-Box hat kein Ansible.
  Das Format belegt `ansible-inventory --list` aus einer Wegwerf-Venv gegen das erzeugte Inventar (Beleg im Ledger).

## Doku-Impact

`docs/admin/ansible.html` und `docs/en/admin/ansible.html`: Abschnitte „Inventory-Generierung“ und
„SSH-Erreichbarkeit“; die Ansible-Zeile in `docs/developer/desktop.html` DE+EN; `changelog.d/kern-ansible-1.md`.

## Offene Fragen

1. **R-1204 (Kevin):** Wie soll Ansible mit Passwort-Verbindungen umgehen? Empfehlung: `--ask-pass`, einmal je
   Lauf im Terminal. Trade-off: Alle Passwort-Ziele eines Laufs teilen ein Passwort, und ältere Ansible-Versionen
   brauchen `sshpass`.
