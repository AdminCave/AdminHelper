<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# heavy.sh: was der Lauf auf stdout druckt, trägt keine Box-Adresse — Task-Ledger
Status: erledigt · Branch: harness/heavy-notes-mask · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; Frage 1 Lesart L2: nur stdout maskieren; Frage 2 report.md bleibt woertlich, Restrisiko auf Kevins Wort 2026-10-13; Frage 3 VMIDs bleiben; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0351 (Kurz-Ledger ohne Spec)
Heavy: none — `heavy.sh` mit seinem hermetischen Test (Shims für vm.py, iter, warm und multibox); kein Stack-, Gateway-, PKI- oder Install-Pfad, keine VM.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen:
„mask_addr auch auf die NOTES“. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der
Aufsicht. Zeilenangaben origin/main@bef5d17e. `scripts/tests/heavy.sh` ist ein Harness-Pfad; den PR merged Kevin oder die
Aufsicht auf sein Wort. Adressen in Tests und Proben sind Platzhalter (RFC 5737).

**Befund.** `heavy.sh` läuft in tmux, und was es auf stdout druckt, steht im Transkript des Laufs.
- `mask_addr` (`:116-118`) maskiert URL-Hosts, `nodes/<name>`, UPIDs, `user@host` und IPv4. Es wirkt heute nur auf
  `REASON` (`set_infra`, `:108-112`), also auf Kopf- und Urteilszeile.
- `note` (`:119`) druckt jede Notiz unmaskiert und legt sie unverändert ins Array. Die Marker aus `all.log` (`:346`)
  und `multibox.log` (`:868`) tragen dabei Meldungen von vm.py, etwa `no ssh: <nutzer>@<adresse>`.
- Die Log-Ausschnitte gehen ebenso unmaskiert auf stdout:
  - `tail -5 doctor.log` (`:169`);
  - `tail -5 warm.log` (`:298`, `:304`);
  - `tail -25 all.log` (`:324`);
  - `tail -25 multibox.log` (`:860`).
- `session_status_test.sh:356-361` verlangt in `heavy.sh` genau ein `sed -E`-Programm, gleich dem des Hooks.

### T1 — heavy.sh: Notizen und Log-Ausschnitte gehen maskiert auf stdout, report.md und die Logs bleiben wörtlich (R-0351)  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8533e0f7 2026-10-13T20:35:17+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve, Nit miterledigt
Änderung:
- `mask_addr` (`:116-118`) wird zu zwei Funktionen mit demselben einen Programm:
  - `mask_stream` (stdin → stdout) trägt das unveränderte `LC_ALL=C sed -E '…'`.
  - `mask_addr <text>` ist `printf '%s' "$1" | mask_stream`.

  So steht das Programm weiter genau einmal in der Datei (`session_status_test.sh:356-361`).
- `note` (`:119`) druckt `mask_addr "$1"` und legt die Notiz unverändert ins Array. `report.md` (`:973-978`) bleibt
  damit wörtlich, wie der Ledger status-no-address den Rumpf des Reports gelassen hat. Die Logs unter `.ah-out` bleiben
  ebenso wörtlich.
- Die fünf Ausschnitte (`:169`, `:298`, `:304`, `:324`, `:860`) gehen vor dem Einrücken durch `mask_stream`:
  `tail -N <log> | mask_stream | sed 's/^/  /'`.
- Der Kopfkommentar an `mask_addr` sagt dazu: Was auf stdout geht, ist maskiert; Report und Logs unter `$OUT` bleiben
  für die Triage wörtlich.
- `heavy_test.sh`:
  - Der vm.py-Shim kann bei `doctor` eine Ausgabe drucken (`SHIM_DOCTOR_OUT`), der warm-Shim ebenso (`SHIM_WARM_OUT`),
    je als neue Zeile; `mk_case` setzt beide zurück.
  - Neue Fälle am Dateiende, mit `192.0.2.7`. Die Prüfungen laufen als Here-Strings, nicht als Pipe:
    - `all` mit `no ssh: adminhelper@192.0.2.7` im iter-Log → rc 74, stdout ohne die Adresse, und die Notiz lautet
      `infra marker in all.log: vm.py: no ssh: <user>@<host> …`. In `all.log` und in den Notizen von `report.md` steht
      die Adresse wörtlich.
    - `capstone` mit `server=192.0.2.7` in der Summary von multibox → stdout ohne die Adresse. Die Summary-Zeile in
      `report.md` bleibt wörtlich.
    - `doctor` mit `https://192.0.2.7:8006` in seiner Ausgabe → rc 74, stdout ohne die Adresse.
    - `warm` mit derselben Meldung wie oben → rc 74, stdout ohne die Adresse.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; der Kommentar an `mask_addr` sagt, was maskiert wird und was nicht)
Beweis: origin/main@bef5d17e. Die Probe mit den Shims aus `heavy_test.sh` und `192.0.2.7` (nicht committet) zeigt die
Adresse auf stdout:
- im `tail -25` von `all.log` und in der Notiz zum infra-Marker;
- in der Summary von multibox (`server=…`) und in einer `ok server-box … @ …`-Zeile;
- im `tail -5` von `doctor.log` und `warm.log`.
Orakel: mutation-sample — `note` druckt wieder `$1` statt `mask_addr "$1"`: der Fall `all` rot. Der Ausschnitt `:324`
ohne `mask_stream`: derselbe Fall rot.
Dedup-Key: ref:scripts:heavy.sh:notes-unmasked
HEAD: bef5d17e
Semantik: `heavy.sh:113-115`: „The reason heads report.md, and AH-STATUS shows that line in every session: no address or
host name of the lab in it … The rest stays word for word, for the triage.“ Kevins Annahme (Roadmap R-0351, 2026-10-13):
„mask_addr auch auf die NOTES“. Das tmux-Transkript des Laufs gehört in dieselbe Vorsicht wie die Session-Transkripte
(`tasks/status-no-address.md:48-49`).
