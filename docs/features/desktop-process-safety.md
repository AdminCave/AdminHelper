<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Argumente für das Windows-Terminal, frpc nach einem abgebrochenen Lauf, Ausgabe des interaktiven RDP

Stand des Codes: `origin/main@b25c65a6`. Alle `datei:zeile` beziehen sich auf diesen Stand; Pfade ohne Verzeichnis
liegen unter `apps/desktop/src-tauri/src/`. Ledger: `tasks/desktop-process-safety.md`. Roadmap R-0645 (T3, T4),
R-0646 (T5); T1 und T2 gehören zum Paket (Kevin 2026-10-22).

## Problem / Motivation

1. **Der Terminal-Start unter Windows übergibt Argumente nicht unverändert (T1, T2).** `open_windows_terminal`
   (`terminal.rs:107-128`) startet SSH (`connection/ssh.rs:58`, Argumente aus `build_ssh_args`, `:21-52`) und
   Ansible (`ansible.rs:176`, Inventory- und Playbook-Pfad). Benutzer und Domain sind am Rand nur auf Steuerzeichen
   geprüft, der Schlüsselpfad nur auf `..` (`validation.rs:57-68`), der Name eines Playbooks kommt vom Server
   (`ansible.rs:95-117`).
   - **Mit Windows Terminal** (`wt -w 0 new-tab -- <command> <args…>`, `:108-118`): wt liest `;` als Trenner seiner
     Unterkommandos, auch hinter `--`; ein wörtliches `;` muss als `\;` stehen (Doku unten). Ein Wert mit `;` kommt
     daher nicht als ein Argument an. Außerdem setzt wt die Argumente hinter `--` wieder zu einer Kommandozeile
     zusammen und setzt dabei nur ein Argument mit Leerzeichen in `"…"`, ohne ein `"` darin zu escapen (Quelltext
     microsoft/terminal, `AppCommandlineArgs::_getNewTerminalArgs`): ein Wert mit `"` oder mit Leerzeichen und
     abschließendem `\` verschiebt die Argumentgrenzen für das gestartete Programm.
   - **Ohne Windows Terminal** (`cmd /C start "" cmd /K <Zeile>`, `:120-127`): Die Zeile aus `build_windows_cmdline`
     setzt jedes Argument mit Sonderzeichen in `"…"` und davor Carets (`windows_quote`, `:146-162`). Innerhalb von
     Anführungszeichen gibt cmd ein Caret wörtlich weiter; der bestehende Test erwartet für `a&b` die Zeile `"a^&b"`
     (`:177-186`), ssh bekäme also `a^&b`. Rust quotet das ganze `/K`-Argument zusätzlich nach den Regeln der
     C-Laufzeit (`\"`), die cmd nicht kennt, und die Zeile durchläuft zwei cmd-Ebenen (`cmd /C` → `start` →
     `cmd /K`). Welches Argument ankommt, hängt dann vom Inhalt ab.
   Unter Linux ist nichts davon betroffen (`bash -c` mit `shell_escape`, `terminal.rs:142-144`). Auf Windows ist keiner
   der Fälle gefahren (keine Windows-Box); die Aussagen stammen aus Doku und Quelltext.

2. **frpc läuft weiter, wenn der Desktop-Prozess ohne geordnetes Ende stirbt (R-0645).** frpc endet nur über
   `stop_frpc` (`frpc.rs:912-921`): beim Wechsel der Anmeldung (`main.rs:205`) und bei `RunEvent::Exit`
   (`main.rs:265-266`). Gestartet wird er über das Shell-Plugin (`frpc.rs:836-844`), ohne Job Object und ohne
   Bindung an den Elternprozess. Der erste Abgleich eines neuen Prozesses leert `run/` (`frpc.rs:1019-1027`),
   beendet aber keinen frpc. Probe (frpc 0.69.1 wie `FRP_VERSION` in `.github/workflows/ci.yml:24`, Linux x86_64, ein
   Python-Elternprozess mit stdout/stderr als Pipe, per SIGKILL beendet): frpc lebt weiter und hält seinen Admin-Port,
   bis er die nächste Log-Zeile schreibt (9 s bei hängendem Login, 2 s bei 3-s-Dial-Timeout gegen `192.0.2.1`), und
   endet dann an SIGPIPE. Ein verbundener frpc, der nichts loggt, läuft entsprechend länger; unter Windows gibt es
   kein SIGPIPE (nicht verifiziert). Solange er läuft, bleiben die Tunnel der alten Anmeldung offen und seine
   Visitor-Ports belegt; der nächste Start bekommt Ausweichports oder scheitert am Bind.

3. **Das interaktive RDP hält die ganze Ausgabe von xfreerdp (R-0646).** `spawn_rdp_interactive`
   (`connection/rdp.rs:517-550`) wartet mit `wait_with_output` (`:534`), das stdout und stderr bis zum Ende der
   Sitzung vollständig sammelt, bei `/log-level:INFO` (`:133`). Der Weg mit Passwort hält nur die letzten 8 KiB
   (`OUTPUT_BUFFER_CAP`, `:56`, `:375-376`). Wie viel eine echte Sitzung ausgibt, ist nicht gemessen (kein xfreerdp
   und kein RDP-Ziel auf der Dev-Box); belegt ist nur, dass nichts die Menge begrenzt.

## Ziel & Nicht-Ziele

Ziele:
- **T1:** wt bekommt jedes Argument so, dass es unverändert ankommt (`;` → `\;`); ein Argument, das wt nicht
  unverändert weitergeben kann (leer, mit `"`, mit Steuerzeichen, mit Leerraum und abschließendem `\`), bricht den
  Start mit einer Meldung ab, bevor etwas startet.
- **T2:** Ohne wt startet genau eine cmd-Ebene in einer neuen Konsole, mit einer Zeile, die Rust nicht noch einmal
  quotet; jedes Argument steht in `"…"`, in dem cmd `&|<>()^` wörtlich nimmt. `"`, `%` und Steuerzeichen lehnt der
  Start mit einer Meldung ab.
- **T3:** Der erste Abgleich eines Prozesses beendet einen frpc, der noch mit der `visitor.toml` in `run/` läuft,
  über `POST /api/stop` seiner eigenen Admin-API, bevor er `run/` leert und einen neuen startet.
- **T4:** Unter Windows endet frpc mit dem Desktop-Prozess, auf jedem Weg (Job Object mit
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`).
- **T5:** Das interaktive RDP hält je Strom höchstens `OUTPUT_BUFFER_CAP` Bytes vom Ende und merkt sich, ob die
  Verbindung stand; die Meldung am Ende der Sitzung folgt denselben Regeln wie heute.

Nicht-Ziele:
- Eine strengere Prüfung von Benutzer und Schlüsselpfad in `validate_connection_input`: Synchronisierte Verbindungen,
  die sie nicht bestehen, verwirft `sanitize_synced_connections` (`validation.rs:184-189`) still, auch unter Linux,
  wo die Werte unverändert ankommen; der Ansible-Weg bliebe ohne Wirkung. T1/T2 lösen es an der einen Stelle, über
  die beide Aufrufer starten (Offene Frage 1).
- `PR_SET_PDEATHSIG` für frpc unter Linux: Das Shell-Plugin bietet kein `pre_exec`, und das Signal hängt am Thread,
  der gestartet hat, nicht am Prozess (Threads aus Tokios Blocking-Pool enden nach Leerlauf); ein eigener Spawn ohne
  Plugin müsste dessen Ereignisstrom nachbauen (Offene Frage 2).
- Die Überwachung des Wegs mit Passwort (`spawn_output_monitor`, `monitor_rdp_exit`) für das interaktive RDP
  übernehmen: Sie bringt die 12-s-Zeitgrenze bis zur Verbindung und die 8-s-Regel nach der Verbindung
  (`connection/rdp.rs:45-54`), sichtbar anderes Verhalten bei einer Anmeldung von Hand; und ihr Leser hört nach
  der ersten Fehlerzeile auf zu lesen (`:385-390`).
- Weitere Punkte zur Ansible-Nachlese (Dateinamen, Antwortgrößen) stehen in einer eigenen Roadmap-Zeile.

## Betroffene Komponenten & Dateien

Nur `desktop-rs`:
- `terminal.rs` (T1, T2): neue reine Funktionen für die wt-Argumente und die cmd-Zeile, `build_windows_cmdline` und
  `windows_quote` entfallen samt ihrer drei Tests (`Test-Löschung:` in T2).
- `frpc.rs` (T3, T4): erster Abgleich, `start_frpc`; T4 mit `unsafe` Win32-Aufrufen unter `#[cfg(windows)]`.
  `frpc.rs` steht auf `scripts/dev/review-risk.txt` (FRP).
- `Cargo.toml` (T4): Features der bestehenden `windows`-Abhängigkeit, keine neue Abhängigkeit.
- `connection/rdp_logic.rs`, `connection/rdp.rs` (T5).
- `docs/developer/desktop.html` + `docs/en/developer/desktop.html` (T3, T4), `CHANGELOG.md` (alle).

Kein UI-Code, kein Tauri-Command, keine Server-Seite.

## Datenmodell / API / Migrationen

Keine. Kein Tauri-Command und kein Event ändert sich, keine Server-Route, keine Migration. `run/` behält seinen
Inhalt (T3 liest die vorhandene `visitor.toml`, es kommt keine Datei dazu). Neu sind nur Fehlermeldungen beim Öffnen
unter Windows (T1, T2), über den bestehenden `AppError::Validation`.

## Externe Integrationen

- Windows Terminal, Kommandozeile: <https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments> (`;`
  trennt Unterkommandos, `\;` ist ein wörtliches `;`). Quelltext `microsoft/terminal`:
  `AppCommandlineArgs::_addCommandsForArg` (Trennung je Argument, unabhängig von `--`), `Commandline::AddArg`
  (`\;` → `;`), `_getNewTerminalArgs` (Zusammensetzen der Kommandozeile). Nicht auf Windows gefahren; der
  CI-Runner `windows-latest` hat kein Windows Terminal.
- cmd: <https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd> (`/S`, `/K`, `/V:OFF`,
  Behandlung der Anführungszeichen). Rust: `std::os::windows::process::CommandExt::raw_arg` (seit 1.62, Text ohne
  Quoting, ausdrücklich für `cmd.exe /c`) und `creation_flags` (`CREATE_NEW_CONSOLE`),
  <https://doc.rust-lang.org/std/os/windows/process/trait.CommandExt.html>.
- frpc-Admin-API: `POST /api/stop` hinter Basic-Auth, Handler ruft `GracefulClose` (frp v0.69.1,
  `client/api_router.go`, `client/http/controller.go`). Probe mit frpc 0.69.1: richtige Zugangsdaten → 200, Prozess
  endet sofort, Port frei; falsches Passwort → 401, frpc läuft weiter; `GET` → 405.
- Win32 Job Objects: <https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects>,
  `JOBOBJECT_BASIC_LIMIT_INFORMATION` (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), `AssignProcessToJobObject`; Crate
  `windows` 0.61 (schon Abhängigkeit, `Cargo.toml` unter `cfg(windows)`).
- Rust std: `Child::wait_with_output` sammelt die ganze verbleibende Ausgabe,
  <https://doc.rust-lang.org/std/process/struct.Child.html#method.wait_with_output>.

## Trade-offs & Alternativen

- **Terminal (T1, T2):** Escapen und Ablehnen in der gemeinsamen Terminal-Schicht (empfohlen) statt Prüfregeln je
  Feld am Rand: wirkt für SSH und Ansible, ändert unter Linux nichts und verwirft keine synchronisierte Verbindung.
  Preis: ein Wert, den Windows nicht unverändert übergeben kann, öffnet unter Windows nicht mehr (vorher kam er
  verändert an). Der cmd-Fallback startet `cmd` direkt in einer neuen Konsole statt über `start`; der Fenstertitel
  kann sich dadurch ändern.
- **frpc (T3):** Stopp über die Admin-API (empfohlen) statt PID-Datei: Die `visitor.toml` mit Port und Passwort des
  Kopfs liegt schon in `run/`, das Passwort (32 Zufallsbytes) gehört genau diesem frpc, eine wiederverwendete PID
  oder der frpc eines anderen Workspace kann nicht getroffen werden (anderes Passwort → 401). Keine neue
  Abhängigkeit, gleich auf Linux und Windows. Grenze: Ein frpc, dessen Admin-API nicht antwortet (hängt), bleibt; den
  fängt unter Windows T4. Wirkt erst beim ersten Abgleich eines neuen Prozesses (nach dem Holen des Visitor-Bundles).
- **frpc (T4):** Job Object nur unter Windows; die kurze Spanne zwischen Spawn und Zuordnung bleibt (frpc startet
  selbst keine Kinder; endet der Prozess genau dort, greift T3 beim nächsten Start).
- **RDP (T5):** Eigene begrenzte Enden je Strom (empfohlen) statt der Überwachung des Passwort-Wegs (siehe
  Nicht-Ziele). Unterschied zu HEAD: Eine Fehlerzeile, die früh in einer langen, dann funktionierenden Sitzung stand
  und aus dem Ende gefallen ist, ergibt am Ende keine Meldung mehr; HEAD meldete sie noch nach Sitzungsende.

## Risiken & Rollback

- T1/T2 sind nur aus Doku und Quelltext abgeleitet; ein Fehler zeigt sich als Meldung oder als nicht startendes
  Terminal unter Windows, nicht unter Linux. Rollback: Revert des Task-Commits.
- T3 schickt beim ersten Abgleich höchstens eine Anfrage an `127.0.0.1` und wartet höchstens rund 4 s; scheitert sie,
  läuft der Abgleich wie heute weiter.
- T4 bringt `unsafe` Win32-Aufrufe; scheitert die Zuordnung, läuft frpc wie heute (Warnung im Log).
- T5 ändert nur, wie viel gehalten wird; beide Pipes werden bis EOF gelesen, xfreerdp blockiert nicht an einer
  vollen Pipe.

## Doku-Impact

`docs/developer/desktop.html:154` (EN `docs/en/developer/desktop.html:154`), Absatz zu den Tunnel-Laufzeitdateien:
der erste Abgleich beendet vorher einen noch laufenden frpc über seine Admin-API (T3); unter Windows endet frpc mit
dem Prozess (T4). CHANGELOG je Task. Terminal-Start unter Windows und RDP-Ausgabe beschreibt die Doku heute nicht:
dort sonst keine Änderung.

## Offene Fragen

1. **Zusätzlich strengere Prüfung von Benutzer und Schlüsselpfad am Rand?** Empfehlung: nein (siehe Nicht-Ziele);
   keine Task hängt daran.
2. **Unter Linux bleibt ein verwaister frpc bis zu seiner nächsten Log-Zeile oder bis zum nächsten Start des
   Workspace (T3).** Empfehlung: so hinnehmen; Alternative wäre ein eigener Spawn ohne Shell-Plugin. Keine Task hängt
   daran.
