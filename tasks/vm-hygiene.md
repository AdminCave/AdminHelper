<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# VM-Hygiene: `.devenv.sh` bleibt zu Hause, `iter.sh` verlängert ehrlich — Task-Ledger (Kurz)
Status: erledigt (2/2) · Branch: fix/vm-hygiene · Commit-Granularität: pro Task · Review: am Ende (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-2.md (Sync-Excludes, TTL-Semantik) — Kurz-Ledger, keine eigene Spec; Befunde aus dem 2b-Review und dem 2b-Live-Beweis
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine; T1 wird per Probe-Klon nach dem nächsten Bake bewiesen (Datei fehlt auf der Box), T2 per hermetischem Test
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0048 (SEC), R-0049 (BUG) · Hängt ab von: PR #22 (vm-migration) gemergt
Befund: `.devenv.sh` (per-Host, gitignored, trägt `AH_TEST_DB` und das heavy-freie `AH_REQUIRED` der Dev-Box) reist mit `vm.py sync` auf jede Box und liegt in den Templates 3901/3902 (geprüft 2026-09-18). Zweiter Schaden: `scripts/dev/verify.sh` sourct die Datei auf der Box, die Box erbt damit die Dev-Box-Menge und kann unter `--strict` grün werden, obwohl die schweren Schritte übersprungen wurden — genau die Falle, die die Box-Regel aus 3b schließen sollte. Dazu R-0049: `iter.sh` verlängert die Warm-Box mit seinem eigenen 8-h-Default statt mit der Frist der Box (live: 18 min → 7 h 58 min nach einem `iter.sh lint`).

### T1 — `.devenv.sh` aus dem Sync, Box-Regel gilt auf der Box  [x] (rsync-exclude + Warum; verify.sh-Kommentar; verify_test: Tree mit devenv setzt AH_REQUIRED, Tree ohne lässt es ungesetzt — 31 passed)
Komponente: scripts · Dateien: scripts/vm/rsync-exclude.txt, scripts/dev/verify.sh, scripts/tests/verify_test.sh
Änderung: `.devenv.sh` in `rsync-exclude.txt` mit demselben Warum-Kommentar wie `.claude/settings.local.json`. `verify.sh`: die Datei nur sourcen, wenn sie existiert (heute schon) — und ein Kommentar, dass sie auf einer Box **fehlen soll**, damit `AH_REQUIRED` ungesetzt bleibt und die Box-Regel aus `run.sh` (unset + schwerer Layer ⇒ alle Layer-Schritte Pflicht) greift. Hermetischer Test in `verify_test.sh`: ohne `.devenv.sh` im Baum bleibt `AH_REQUIRED` ungesetzt (Beweis über `AH_DRY_RUN`/Ausgabe `required (strict):` der Layer-Menge). Toolchain-PATH auf der Box kommt aus dem Bootstrap (`/etc/profile.d`), nicht aus `.devenv.sh` — im Test nicht relevant, im Kommentar benennen.
Verify: bash scripts/tests/run.sh unit --strict --only scripts   und   grep -n '^\.devenv\.sh$' scripts/vm/rsync-exclude.txt   (1 Treffer)
Doku: DEVELOPMENT.md ein Satz im `.devenv.sh`-Absatz (bleibt auf der Dev-Box; die Box bekommt keine)

### T2 — `iter.sh --extend`: Frist der Box respektieren  [x] (warm.sh merkt `desktop_ttl` in warm.env — nur die Desktop-Box wird von iter.sh verlängert, Review-Nit; iter.sh: AH_WARM_TTL > desktop_ttl > 8h; vm_wrappers_test 36 passed mit vier neuen Fällen; vm.py unverändert — `run --extend <dauer>` reicht)
Komponente: scripts · Dateien: scripts/vm/iter.sh, scripts/vm/vm.py (nur falls `run --extend` die Ist-Frist nicht liefert), scripts/tests/vm_wrappers_test.sh
Änderung: `iter.sh` verlängert nur, wenn `AH_WARM_TTL` **explizit gesetzt** ist, oder — ohne Variable — auf die Frist, mit der die Box gewärmt wurde: `vm.py` liest dazu den `ttl-`-Tag der Box und die Warm-Frist aus `.vm/warm.env` (neuer Schlüssel `desktop_ttl=<sekunden>`, von `warm.sh` geschrieben); `--extend` ohne Wert verlängert um genau diese Spanne. Eine bewusst kurze Box (`AH_WARM_TTL=20m`) bleibt damit kurz. Hermetischer Test mit Fake-`vm.py`: Warm mit 20m + iter ohne Variable ⇒ `--extend 20m`; iter mit `AH_WARM_TTL=8h` ⇒ `--extend 8h`; ohne `desktop_ttl` in warm.env ⇒ Default 8h (Bestandsschutz).
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: DEVELOPMENT.md Satz zu `AH_WARM_TTL` und Verlängerung · CHANGELOG Unreleased/Fixed
