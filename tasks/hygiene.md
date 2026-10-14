<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket hygiene: keine Box-Adresse im Reg-Ledger, list kennt alle Warm-Boxen, eine Lane-Form für die Allow-Regel (R-0365, R-0371, R-0370) — Task-Ledger
Status: erledigt · Branch: harness/hygiene · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-14 (kleines Fund-Paket, Triage Kevin 2026-10-14; F1 A --as-lane, F2 A warm.env aller Worktrees; T3 nach dem Merge von doc-smoke-lane (#167, gemergt); Review am Ende Opus; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0365, R-0371, R-0370 (Kurz-Ledger ohne Spec)
Heavy: none — heavy.sh mit heavy_test (Shims), vm.py mit test_vm.py (aufgezeichnete API, Fixture-Worktrees); keine echte VM.
Hängt ab von: harness/doc-smoke-lane — T3 setzt auf dessen Lane-Regel und Doku auf; T3 erst nach dessen Merge bauen
und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-14 von Worker A für den Chef (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-14 triagiert
(Hygiene-Paket, R-0365 zuerst). Zeilenangaben origin/main@e2055c5b; beim Bau an Symbolen orientieren.

Vorab geprüft:
- R-0365:
  - heavy.sh `write_reg_ledger` (:664–697) schreibt den Marker des roten Schritts wörtlich zweimal ins Ledger
    `tasks/reg-<datum>-<schritt>.md`: in die Zeile `Beweis:` und unter „## Beweis“. Das Ledger liegt im öffentlichen Baum.
  - Seit status-no-address (#152) und heavy-notes-mask (#162) maskiert heavy.sh Grund, NOTES und Log-Ausschnitte
    (`mask_addr`, `mask_stream` :117–123). Das Ledger nimmt den Marker roh.
  - `review.sh sec` fängt eine Adresse im Commit nicht: Der Zweig `sec` (:909–1115) prüft Pfade (privater Plan,
    SEC-Ledger, Dateien mit Zugangsdaten) und Token-Muster, keine Adressen und keine Host-Namen. Die Adressfilter in
    review.sh (`PARTIAL`, `ADDR`, `HOST` ab :1569) gelten nur für `pr-body`.
- R-0371: `verb_list` (:1670–1726) zählt eine VM der eigenen Lane als Leak, wenn kein Warm-Slot sie beansprucht. Die Slots
  liest `warm_vmids` (:1637–1659) nur aus dem eigenen `.vm/warm.env`.
  - Ein angehängter Worktree mit `AH_LANE=main` sieht Kevins Warm-Box (im `.vm/warm.env` des Haupt-Checkouts) also als
    Leak.
  - Umgekehrt sieht der Haupt-Checkout die Warm-Box eines Workers auf main als Leak.
  - Im Lauf ist das nicht belegt, aber an der Quelle eindeutig.
- R-0370:
  - Kevins `.claude/settings.json` erlaubt `Bash(python3 scripts/vm/vm.py:*)`, `Bash(bash scripts/tests/multibox.sh:*)` und
    `Bash(bash scripts/tests/heavy.sh:*)`. Ein vorangestelltes `AH_LANE=main` trifft keine davon.
  - `list --lane` ist ein bewusster Filter: test_vm.py `test_list_can_be_narrowed_to_one_lane` (:2316–2325) hält fest, dass
    der Leak der eigenen Lane trotz Filter gemeldet wird („a filter is for reading, not for looking away“, vm.py
    :1699–1701).
  - Stufe 7b braucht kein `AH_LANE`: Der Loop legt seine Bau-Worktrees mit `lane.sh new` an (ledger-loop.sh :589), also
    mit `.vm/lane`, und fährt selbst keinen Heavy-Lauf (ledger-loop.sh :404, :962–967: „Heavy offen — fährt der Chef“).

## Offene Fragen (Chef; bei Bedarf an Kevin)

- **F1 (R-0370): welche Form für einen Lauf auf main aus einem Worktree ohne Lane?**
  - **A (Empfehlung):** ein Schalter vor dem Verb, `python3 scripts/vm/vm.py --as-lane main <verb> …`.
    - Er setzt die Lane für den ganzen Aufruf, wie `AH_LANE`, und trifft die bestehende Allow-Regel.
    - `list --lane` bleibt Filter.
  - **B:** `list --lane <lane>` zählt auch als eigene Lane. Das kehrt die bewusste Filter-Semantik um und braucht eine
    `Assertion-Änderung:` in `test_list_can_be_narrowed_to_one_lane`.
  - **C:** nur Doku `env AH_LANE=main python3 …`, dazu ergänzt Kevin eine Allow-Regel. Die Settings sind seine.
- **F2 (R-0371): woher kennt list die Warm-Slots?**
  - **A (Empfehlung):** aus dem `.vm/warm.env` jedes Worktrees des Repos (`git worktree list --porcelain`, ohne geerbtes
    GIT_DIR). Das deckt beide Richtungen: Kevins Box aus Worker-Sicht, die Box eines Workers aus Kevins Sicht.
  - **B:** nur aus dem eigenen und dem des Haupt-Checkouts.
  - Bei beiden bleibt ein unlesbares oder fremdes `warm.env` folgenlos; die Leak-Prüfung fällt dann auf das eigene zurück.

T2 und T3 sind für A geschrieben.

### T1 — Das Reg-Ledger aus heavy.sh trägt den Marker maskiert (R-0365)  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @504bc9fb 2026-10-14T11:36:42+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `write_reg_ledger` (:664) nimmt den Marker durch `mask_addr` (:122), bevor er ins Ledger geht. Damit werden
  `user@host`, IPv4, URL-Hosts, `/nodes/<name>` und UPIDs maskiert, wie im Grund. Der Rest des Markers bleibt wörtlich.
- Fall in heavy_test, aufgebaut wie der Reg-Ledger-Fall :520–570:
  - ein roter Schritt, dessen Marker eine Adresse trägt (`… adminhelper@192.0.2.7 …`, RFC 5737);
  - das Ledger nennt `<user>@<host>` und keine `192.0.2.7`;
  - die Zeile `Beweis:` steht weiter darin.
Rot vorher: Auf main steht die Adresse aus dem Marker zweimal im Ledger.
Beweis: origin/main@e2055c5b, heavy.sh :686 `rot mit \`$marker\``, :691 `jedes Mal mit demselben Marker: \`$marker\``;
review.sh :909–1115 ohne Adressprüfung. Fund: Plan heavy-notes-mask (Worker B, Explorer), 2026-10-13.
Dedup-Key: bug:scripts:heavy.sh:reg-ledger-verbatim-marker
HEAD: e2055c5b
Semantik: CLAUDE.md §2 „Claude tut nie von sich aus: … Homelab-Namen … in versionierte Dateien schreiben“; heavy.sh :117
(Kommentar zu `mask_stream`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — list kennt die Warm-Slots aller Worktrees des Repos (R-0371, F2 A)  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5290d363 2026-10-14T11:50:43+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `warm_vmids` bzw. `verb_list` lesen die Warm-Slots aus dem eigenen `.vm/warm.env` und aus dem jedes anderen Worktrees,
  den `git worktree list --porcelain` nennt. Nur die Schlüssel ohne Unterstrich zählen, wie heute.
  - Ein Worktree, dessen `warm.env` fehlt oder nicht lesbar ist, fällt still weg.
  - Kann git nicht antworten, bleibt es beim eigenen `warm.env` wie heute.
- Fälle in test_vm.py mit echten Fixture-Worktrees:
  - Haupt-Checkout mit `desktop=3000` in seinem `warm.env`, `list` aus dem angehängten Worktree (`AH_LANE=main`) → 3000
    ist kein Leak;
  - umgekehrt: der Slot im Worktree, `list` aus dem Haupt-Checkout → kein Leak;
  - eine VM der Lane ohne jeden Slot → weiter Leak.
Rot vorher: Auf main meldet `list` aus dem angehängten Worktree 3000 als Leak.
Beweis: origin/main@e2055c5b, vm.py :1637–1659 `warm_vmids` liest nur `VM_STATE_DIR/warm.env`. Fund: Review
doc-smoke-lane (Worker A), 2026-10-14.
Dedup-Key: bug:scripts:vm.py:list-foreign-warm-as-leak
HEAD: e2055c5b
Semantik: vm.py `verb_list`, Kommentar: „A VM of our own lane that no warm slot and no running scenario claims is a leak“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — vm.py --as-lane <lane> vor dem Verb, eine Form für die Allow-Regel (R-0370, F1 A)  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, .claude/skills/vm/SKILL.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @01ac096a 2026-10-14T12:04:56+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung (nach dem Merge von doc-smoke-lane frisch greppen):
- `build_parser` bekommt `--as-lane <lane>` auf oberster Ebene. `main` setzt damit `AH_LANE` für den Aufruf, bevor das Verb
  läuft.
  - Rang wie `AH_LANE`: `clone --lane` geht weiter vor.
  - `list --lane` bleibt Filter.
- Fälle in test_vm.py:
  - `main(["--as-lane", "main", "list"])` im angehängten Worktree ohne Lane läuft (kein „no .vm/lane“);
  - `--as-lane pilot` wirkt wie `AH_LANE=pilot`;
  - ohne den Schalter weist der Worktree weiter ab.
- vm-Skill und DEVELOPMENT.md (Lane-Absatz aus doc-smoke-lane): Für `vm.py` in einem Worktree ohne Lane gilt
  `python3 scripts/vm/vm.py --as-lane main …`, das trifft die Allow-Regel. Für `warm.sh`, `iter.sh`, `reap.sh` und
  `heavy.sh` bleibt `AH_LANE=main`; diese fragen ohnehin nach (reap.sh hat `--lane`).
- Stufe 7b braucht kein `AH_LANE` (Vorab geprüft). Das steht als ein Satz in DEVELOPMENT.md.
Rot vorher: Auf main kennt vm.py keinen Schalter `--as-lane`. In einem Worktree ohne Lane gibt es nach doc-smoke-lane nur
`AH_LANE=main …`, das keine Allow-Regel trifft.
Beweis: .claude/settings.json (Allow-Regeln, gelesen), vm.py `build_parser` (:1933); Review doc-smoke-lane (Worker A),
2026-10-14.
Dedup-Key: ref:scripts:vm.py:ah-lane-allow-form
HEAD: e2055c5b
Semantik: CLAUDE.md §8 „Nach jedem Lauf `python3 scripts/vm/vm.py list`; eine geleakte VM ist ein Fehler, kein Detail.“
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: .claude/skills/vm/SKILL.md, DEVELOPMENT.md (Lane-Absatz)
Abhängt von: T2
