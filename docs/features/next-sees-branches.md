<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `roadmap.py next` sieht Ledger auf Branches

Roadmap: R-0099 · Ledger: `tasks/next-sees-branches.md` · Branch: `harness/next-sees-branches`
Geplant 2026-09-27 von der Aufsicht (adminhelper-ac) auf Kevins Wort; muss vor Stufe 7 (Worker) gemergt sein.

## Problem / Motivation

`roadmap.py next --exclude-components C …` soll Zeilen überspringen, deren Ledger eine ausgeschlossene
Komponente berührt (`DEVELOPMENT.md:460–463`). `components_of` (roadmap.py:814–834) liest das Ledger aber nur
aus dem Arbeitsbaum (`:823–830`). Seit R-0065 liegt ein geplantes Ledger bis zum Merge nur auf seinem Branch:
Aus dem Haupt-Checkout ergibt `components_of` dann `set()`, und die Zeile gilt als disjunkt (`:846`). Der
Worker aus Stufe 7 sieht in seinem Klon (`runner-setup.sh` klont `-b main`, `DEVELOPMENT.md:652` verbietet ihm
`git switch`/`git branch`) nur `main` und nach einem Fetch `origin/*` — für ihn wäre jede geplante Zeile frei.

Beleg (origin/main@70e91718, Roadmap-Zeile per Prozess-Substitution, das Ledger vom echten, nur lokalen Branch
`feature/box-ohne-repo`): `python3 -B scripts/dev/roadmap.py --file <(…) --today 2026-09-27 next
--exclude-components scripts` → `R-0095 BUG Box ohne Repo (tasks/box-ohne-repo.md)`, Exit 0; erwartet Exit 1,
denn `git show feature/box-ohne-repo:tasks/box-ohne-repo.md` trägt zweimal `Komponente: scripts`. Gegenprobe mit
`tasks/harness-stufe-5c.md` im Baum: `next: no freigegeben row is ready`, Exit 1.

Der Branch-Name folgt nicht aus dem Pfad (`harness-stufe-5c.md` → `harness/stufe-5c`, dazu `fix/`, `docs/`),
und der Ledger-Kopf `Branch:` steht im Ledger selbst — als Suchschlüssel taugt er nicht.

## Ziel und Nicht-Ziele

Ziel (Kevin, 2026-09-27):
- `components_of` vereinigt die `Komponente:`-Zeilen aus dem Arbeitsbaum und aus **jedem** `refs/heads/*` und
  `refs/remotes/*` (ohne symbolisches `HEAD`), das den Pfad trägt. Mehrdeutigkeit wird zur Vereinigung: eher
  zu viel ausgeschlossen, nie zu wenig. Das deckt den Worker-Klon (nur `origin/*`) und das ungetrackte
  REG-Ledger aus `heavy.sh` (Baum) ab.
- **fail-closed, eng gefasst:** Nur wenn `--exclude-components` gesetzt ist **und** die Spalte `Ledger` einen
  repo-relativen Pfad nennt, den weder Baum noch Ref trägt, wird die Zeile übersprungen, mit einer stderr-Zeile
  `next: R-nnnn skipped — ledger <pfad> not found in the tree or on any branch (git fetch?)`.

Nicht-Ziele:
- Kein Formatwechsel der Spalte `Ledger`, keine neue Spalte.
- Kein `git fetch` in `roadmap.py` (read-only, ohne Netz); der Aufrufer fetcht, das steht in der Doku.
- Keine Berechnung der Ausschlussliste aus den `aktiv`-Zeilen (gehört in die Stufe-7-Spec).
- Keine Slug-Normalisierung (`wochenlauf-gruen`, `harness-stufe-5a/5b/5c` in der Spalte ergeben weiter `set()`;
  fail-closed greift nur bei einem Pfad `tasks/….md`); normalisiert wird von Hand über `status --ledger`.
- Keine Änderung an `lane.sh`, `heavy.sh` oder an Zeilen ohne Ledger (`—`).

## Betroffene Komponenten und Dateien

`scripts/dev/roadmap.py` (Harness-Pfad), `scripts/dev/tests/test_roadmap.py`, `DEVELOPMENT.md` (`next`,
:458–463), `.claude/skills/feature-plan/SKILL.md` (Gate, :203–205, Harness-Pfad).

## Datenmodell / API / Migrationen

Keine. Neu ist nur die stderr-Zeile von `next`.

## Externe Integrationen

Nur die git-CLI: `git -C ROOT for-each-ref`, `git -C ROOT grep -E '^Komponente:' <refs…> -- <pfad>` mit
`--literal-pathspecs`; lokal erprobt (0,016 s über 23 Refs), per WebFetch nicht verifiziert. `git grep` mit
rc=1 unterscheidet nicht zwischen „Datei fehlt" und „keine Komponente" — die Existenz je Ref prüft
`git cat-file -e <ref>:<pfad>`.

## Trade-offs und Alternativen

| | Wie | Urteil |
|---|---|---|
| **Vereinigung aus Baum und allen Refs** (gewählt) | ein `git grep` über alle Bäume | kein Format, keine Präfixliste, Worker-Klon und REG-Ledger abgedeckt; veraltete Kopien auf alten Branches schließen mehr aus als nötig (sicher, kostet nur Wartezeit; Gegenmittel `fetch --prune`) |
| `<branch>:<pfad>` in der Spalte | `git show` auf den genannten Ref | Formatwechsel für alle Schreiber und Leser, nach Merge und `lane.sh done` veraltet, braucht doch einen Rückfall |
| Suche nur `feature/*`, `harness/*` | `for-each-ref` + `cat-file -e` | Präfixliste zu kurz (`fix/`, `docs/`), bricht bei Mehrdeutigkeit ab |
| Plan wieder auf `main` | wie vor R-0065 | widerspricht R-0065 und dem Ruleset |

fail-closed nur eng gefasst, weil die breite Form („keine Komponente ableitbar" zählt auch als Konflikt) die
erwarteten Werte zweier bestehender Tests drehen würde (`test_next_skips_excluded_components`,
`test_next_reads_no_ledger_outside_the_repository`).

## Risiken und Rollback

- Ein Worker ohne Fetch sieht alle Zeilen mit Ledger als übersprungen, stderr nennt sie — sichtbar und besser als
  falsche Parallelität.
- Ein geerbtes `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` des Aufrufers lenkt die Suche in ein fremdes Repo
  (Präzedenz 2a8dd0ae): die git-Aufrufe laufen mit einer Umgebung ohne `GIT_*`.
- Pathspec-Magie aus der Zelle (`:(exclude)…`, Globs): `--literal-pathspecs`; die ROOT-Sperre für absolute Pfade
  bleibt.
- Rollback: `git revert` je Task; keine Format- oder Datenänderung, die Roadmap-Datei bleibt unberührt.

## Doku-Impact

`DEVELOPMENT.md` (`next`: wo das Ledger gesucht wird, fail-closed, der Aufrufer fetcht) und der Gate-Satz in
`feature-plan`. CHANGELOG: keine (interner Bugfix am Werkzeug).

## Offene Fragen

Keine. Entschieden (Kevin, 2026-09-27): Vereinigung aus Baum und allen Refs, fail-closed eng.
