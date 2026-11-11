# Harness: eigene known_hosts-Datei für den Connect-Lauf (kern-harness-4)

Roadmap: R-1157 (vor dem Release 0.47.0, R-1110; Harness-Änderung auf Kevins Wort, Triage 2026-11-09). Aus
`tasks/kern-harness-3.md` hierher verschoben, weil die Änderung einen Box-Beweis des GUI-Schritts braucht und der
Sammellauf damals rot war; seit dem Sammellauf 2026-11-09 17:05 (PASS) ist das möglich.

## Problem / Motivation
`scripts/tests/desktop_e2e_connect.sh` entfernt vor den Specs und im EXIT-Trap mit `forget_e2e_host_key`
(`ssh-keygen -R "[127.0.0.1]:2222"`) den Host-Key des SSH-Ziels aus dem known_hosts des ausführenden Nutzers. Auf
der Wegwerf-VM ist das harmlos; auf einer Dev-Box löscht der Lauf einen Schlüssel, den der Nutzer für diese
Adresse gepinnt hat (Fund aus dem security-Review von arch-ssh-terminal, Nit).

## Ziel & Nicht-Ziele
- Der Lauf liest und schreibt nur eine eigene known_hosts-Datei unter `$E2E_WORK`; das known_hosts des Nutzers
  bleibt unberührt.
- Der Spec sieht weiter die Host-Key-Frage (die Datei des Laufs startet leer) und nach dem Reconnect keine mehr.
- Nicht-Ziel: eine Produkt-Option für die known_hosts-Datei der App (die App setzt keine; das bleibt so).

## Betroffene Komponenten & Dateien
`scripts/tests/desktop_e2e_connect.sh`, `scripts/tests/desktop_e2e_skip_test.sh`,
`apps/desktop/e2e/test/specs/ssh-connect.live.js` (nur der Kommentar, der das Entfernen durch den Orchestrator beschreibt).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
OpenSSH `ssh_config(5)`: `UserKnownHostsFile`; für jede Option gilt der erste gelesene Wert, die Kommandozeile
vor den Konfigurationsdateien. Ein `-o`-Wert wird an Leerzeichen geteilt: der Pfad unter `$E2E_WORK` (mktemp) ist
ohne Leerzeichen.

## Trade-offs & Alternativen
- **ssh-Shim im PATH (gewählt):** Die App findet `ssh` über `PATH` (`terminal::which("ssh")`,
  `apps/desktop/src-tauri/src/commands.rs:772`); das Skript legt schon einen Shim-Ordner vor `PATH`
  (`SHIM_DIR`, für `xdg-open`). Ein `ssh`-Shim dort ruft das echte ssh (vorher absolut aufgelöst) mit
  `-o UserKnownHostsFile=$E2E_WORK/known_hosts` vor allen Argumenten auf. Das gilt für das ssh des Terminals,
  den SFTP-Kanal und das ssh im OS-Terminal, die alle den PATH der App erben. Nichts außerhalb von `$E2E_WORK`
  wird geschrieben.
- **Eintrag sichern und zurückschreiben:** `ssh-keygen -F` vorher sichern, nachher wieder anhängen. Verworfen:
  der Lauf schreibt weiter in die Datei des Nutzers, und ein Abbruch zwischen Löschen und Zurückschreiben verliert
  den Schlüssel.
- **Produkt-Option (Env-Variable der App):** verworfen, Testhaken im Produkt für einen Harness-Fund.

## Risiken & Rollback
Löst ein Terminal-Emulator `ssh` nicht über den geerbten PATH auf, liefe das ssh des OS-Terminals am Shim vorbei;
es meldet sich ohnehin nie an (nur `[preauth]`), schriebe aber nach einer Host-Key-Antwort ins Nutzer-known_hosts.
Der Box-Lauf des Schritts zeigt, ob der Spec und die sshd-Zählung grün bleiben. Rollback: Revert des einen Commits.

## Doku-Impact
Keine: die Doku beschreibt den known_hosts-Umgang des Connect-Laufs nicht.

## Offene Fragen
Keine.
