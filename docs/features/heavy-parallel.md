<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness: Sammellauf mit Sekunden je Schritt und auf zwei Boxen parallel

Roadmap R-0603 (REF, Harness) · Kevins Wort 2026-10-21 (diktiert, damit Kevins Wort für die Harness-Pfade):
„(1) Report nennt je Schritt die Sekunden (steps-all.tsv heute leer), (2) run.sh all auf zwei VMs parallel
(Desktop-GUI-E2E auf eigener Box, Rest auf zweiter), RAM-Prüfung des Hosts wie in vm.py.“
Zeilenangaben gelten für `origin/main@8dec2275`; die Bau-Session greppt sie beim Start neu.

## Problem / Motivation

1. **Keine Schritt-Tabelle.** Der Report eines Sammellaufs (`.ah-out/weekly/<lauf>/report.md`) hat seit Mitte
   Oktober nur noch die Ebenen-Zeile, etwa `| all | - | pass | 5867 | … |`, und `steps-all.tsv` ist leer. Die Notiz
   lautet jedes Mal „last-all.json describes another tree — ignored (evidence must match this run)“. Welcher Schritt
   die 98 Minuten kostet, sagt der Report nicht, und `history.csv` bekommt keine Schritt-Zeilen mehr.
2. **Ein Lauf dauert über 1,5 h** auf einer Box (5867 s am 2026-10-20). Die Desktop-GUI-E2E (`desktop_e2e_*`) laufen
   mit etwa 30 min am Ende hinter allem anderen, obwohl sie von den übrigen Schritten nichts brauchen. Ein Lauf ist
   am 2026-10-21 an der damaligen Schranke von 6000 s abgebrochen (UNVERIFIED, Timeout).

### Befund zu 1 (Ursache)

`heavy.sh` vergleicht `head` und `tree_hash` des gezogenen Artefakts mit dem Commit und dem Tree-Hash, die es selbst
beim Start im Checkout berechnet (`scripts/tests/heavy.sh:92-94`, `artifact_is_ours` `:262-274`, `:369-373`).
`run.sh` auf der Box schreibt in das Artefakt zuerst die Antwort des eigenen `git` und nimmt die Werte des Clients
(`AH_HEAD`, `AH_TREE_HASH` aus `iter.sh`, `scripts/vm/iter.sh:65-76`) nur, wenn dieses `git` nichts sagt
(`scripts/tests/run.sh:449-472`). Ob die Box ein `git` hat, hängt davon ab, woher der Sync kommt:

- **Aus einem Worktree** reist `.git` nur als Zeiger, die Box hat kein Repo, `run.sh` nimmt die Werte des Clients,
  und sie passen. So liefen die beiden Läufe vom 2026-09-25 (33 bzw. 34 Schritt-Zeilen).
- **Aus dem Haupt-Checkout** reist das ganze Repo mit (`scripts/vm/rsync-exclude.txt:7-10`). `run.sh` rechnet den
  Tree-Hash dann auf der Box selbst, und zwar am **Ende** des Laufs (`write_artifact`, `run.sh:474-510`), über einen
  Baum, den der Sync anders geformt hat als den des Clients: `apps/server/data` ist vom Sync ausgenommen
  (`rsync-exclude.txt:25`), trägt aber die getrackte Datei `apps/server/data/.gitkeep`. Der Hash der Box kann den
  des Clients deshalb nie treffen. Alle 16 Läufe aus dem Haupt-Checkout seit dem 2026-09-18 haben das Artefakt
  verworfen, beide aus einem Worktree nicht.

Planer-Probe (`origin/main@6f05b316`, ohne VM): ein lokaler Klon, mit `rsync -a --delete --exclude-from
scripts/vm/rsync-exclude.txt` in ein zweites Verzeichnis kopiert, ergibt dort mit `scripts/dev/tree-hash.sh` einen
anderen Hash als im Klon (`ca4abbc1…` gegen `3924a443…`); legt man `apps/server/data/.gitkeep` zurück, sind beide
gleich. Auf der echten Box ist das **nicht verifiziert** (die Box wurde nicht betreten); dazu kommen dort womöglich
Dateien, die der Lauf selbst anlegt und die nicht ignoriert sind. Für den Fix ist das gleich: Der Hash der Box ist
der falsche Messpunkt.

Kevin hat am 2026-09-25 entschieden: „Die Box braucht kein Repo … Kopf und Tree-Hash gibt `iter.sh` vom Client mit“
(`DEVELOPMENT.md:1235-1236`). Der Fix setzt genau das durch.

## Ziel & Nicht-Ziele

**Ziel**
- Der Report nennt für **jeden** Schritt von `run.sh all` Ergebnis und Sekunden, `steps-all.tsv` ist gefüllt, auch
  bei einem Lauf aus dem Haupt-Checkout.
- `heavy.sh all` fährt `run.sh all --strict` als **zwei Teile gleichzeitig** auf zwei Boxen: Teil `gui` (die
  Desktop-GUI-E2E) auf einer eigenen Box, Teil `rest` (alles andere) auf der bisherigen Warm-Box.
- Gesamturteil, Report, `tasks/private/history.csv`, die Klassifikation roter Schritte samt REG-Zeile und
  `UNVERIFIED` verhalten sich wie heute. **PASS nur, wenn beide Teile grün sind**; ein Teil, der nicht lief, macht
  den Lauf `UNVERIFIED` oder rot, nie grün.
- Die RAM-Prüfung vor jedem Klon (`vm.py`, `capacity_report` `scripts/vm/vm.py:629-656`) bleibt die einzige
  Kapazitäts-Wahrheit; `heavy.sh` fragt im Pre-flight nur nach den Rollen, die es wirklich klont.

**Nicht-Ziele**
- Keine weitere Aufteilung (drei oder mehr Boxen, Lastausgleich nach gemessenen Zeiten). Erst messen (Beweislauf).
- Kein Umbau von `capstone` und `multibox.sh`; `weekly` übergibt dem Capstone weiter die Box des Slots `desktop`.
- Keine Änderung an `vm.py` selbst (die neue Rolle steht nur in `profiles.json`), an der Zweit-VM-Logik (`w2`) oder
  am Format von `history.csv`.
- Keine sortierte „langsamste Schritte“-Ansicht; die Sekunden stehen in der Schritt-Tabelle.

## Betroffene Komponenten & Dateien

Alles Komponente `scripts` (Harness):

| Datei | Änderung |
|---|---|
| `scripts/tests/run.sh` | Evidenz: Client-Werte vor dem `git` der Box (`:449-472`); neues Flag `--part gui\|rest` (Parser `:54-71`, Filter in `want_step` `:214-218`, Artefakt-Feld `part` neben `step` `:487`) |
| `scripts/vm/lib.sh` | `warm_set`/`warm_clear` (`:128-135`) unter einer Sperre |
| `scripts/vm/warm.sh` | zweiter Slot/Rolle `gui` (`:166-171`) |
| `scripts/vm/profiles.json` | Rolle `gui` mit der Form von `desktop` (`:26`) |
| `scripts/vm/reap.sh` | Slot `gui` in der Schleife (`:43`); `--role <rolle>` gibt genau einen Slot frei |
| `scripts/vm/iter.sh` | `--slot desktop\|gui` wählt die Warm-Box (`:52`, `:95`, `:140-141`, `:208-209`); `--part` wird an `run.sh` durchgereicht (`:166`) |
| `scripts/tests/heavy.sh` | Auswertung einer Ebene als Funktion; zwei Teile parallel; Freigabe der GUI-Box; Notiz nennt bei verworfenem Artefakt beide Identitäten |
| `scripts/vm/rsync-exclude.txt` | Kommentar `:4-10` richtigstellen |
| Tests | `scripts/tests/run_flags_test.sh`, `iter_flags_test.sh`, `vm_wrappers_test.sh`, `lib_vm_test.sh`, `heavy_test.sh`, `scripts/vm/tests/test_vm.py` |
| Doku | `DEVELOPMENT.md`, `docs/developer/cicd.html` + `docs/en/developer/cicd.html`, `.claude/skills/test/SKILL.md`, `.claude/skills/vm/SKILL.md`, `.claude/rules/testing.md`, `CHANGELOG.md` |

Risikopfade (`scripts/dev/review-risk.txt`): `scripts/tests/run.sh`, `scripts/tests/heavy.sh`, `scripts/vm/*`,
`.claude/*` — jede Task bekommt zusätzlich `security`.

## Datenmodell / API / Migrationen

Kein Produkt-API, keine Migration, kein Vertrag Server ↔ Web ↔ Desktop ↔ Agent.

Harness-Formate:
- **`last-<layer>.json`** (run.sh): neues Feld `"part"` (`""`, `"gui"`, `"rest"`), wie `"step"` und `"only"`.
  `head`/`tree_hash` kommen bei einem Box-Lauf mit Sync vom Client. Leser: `heavy.sh`, `verify.sh` (lokal, ohne
  `AH_HEAD`/`AH_TREE_HASH`, also unverändert).
- **Summary-Zeile** `run.sh[all]: …` bleibt unverändert; `heavy.sh` setzt im Report ein Etikett davor
  (`[rest] run.sh[all]: …`, `[gui] run.sh[all]: …`), der Text danach bleibt wörtlich.
- **`.vm/warm.env`**: neue Schlüssel `gui`, `gui_name`, `gui_ttl`; daneben `warm.env.lock`. `vm.py` liest als VMID
  nur Schlüssel ohne Unterstrich (`vm.py:1675-1695`), `gui` zählt damit als Warm-Slot, ohne Code-Änderung.
- **`steps-all.tsv`**: die Schritte beider Teile, je Zeile `<name>\t<ergebnis>\t<sekunden>\t<teil>`.
- **`history.csv`**: Format unverändert. Je Schritt eine Zeile (Spalte `vm` = Box des Teils), dazu **eine**
  Ebenen-Zeile `all,-,<gesamturteil>,<wandzeit>,<vm-rest>+<vm-gui>`. `last_pass_commit` (`heavy.sh:535-538`) und
  `/feature-build` §5 lesen weiter nur `all,-,pass`.

## Externe Integrationen

- Bash `wait <pid>`: „Wait until the child process specified by each id exits and return the exit status of the last
  id.“ Für ein `id`, das kein Kind ist: Status 127
  (<https://www.gnu.org/software/bash/manual/html_node/Job-Control-Builtins.html>). Je Teil schreibt der
  Hintergrund-Job Exit-Code und Sekunden zusätzlich in eine Datei, damit ein 127 nicht als Ergebnis gelesen wird.
- `flock(1)`, Form `( flock -w <s> 9 || exit 1; … ) 9>datei`; `-w` scheitert nach der Frist mit Exit 1, die Sperre
  fällt mit dem Schließen des Deskriptors (<https://man7.org/linux/man-pages/man1/flock.1.html>). Auf dem Dev-Rechner
  und den Boxen aus `util-linux`; ohne `flock` schreibt `lib.sh` wie bisher (wie `py_lock` in `run.sh:273-276`).
- Proxmox-API, rsync, FRP, Tauri: unverändert. Die Kapazitätsprüfung bleibt die von `vm.py clone`/`doctor`.

## Entwurf

### 1. Evidenz vom Client (Fix zu Problem 1)

`run.sh` nimmt `AH_HEAD`/`AH_TREE_HASH`, wenn sie 40 Hex-Zeichen sind, und fragt sein eigenes `git` nur ohne sie.
`iter.sh` gibt sie nur bei einem Lauf mit Sync mit (`iter.sh:62-66`); ein Lauf ohne Sync (`AH_NO_SYNC=1`, die
Wiederholungen der Klassifikation) trägt weiter die Antwort der Box, und `heavy.sh` liest dessen Artefakt nicht.
Lokale Läufe (`verify.sh`, `task-close.sh`) setzen keine der beiden Variablen und bleiben, wie sie sind.

Wird ein Artefakt trotzdem verworfen, nennt die Notiz beide Paare (Artefakt gegen Lauf), damit die Ursache im Report
steht und nicht erst nach 16 Läufen auffällt.

### 2. Die Teilung: `run.sh --part gui|rest`

Teil `gui` = `desktop-e2e smoke`, die Wächter-Zeile `desktop GUI E2E` und jeder `desktop_e2e_*` (die Namen, unter
denen `layer_e2e` sie führt, `run.sh:879-905`). Teil `rest` = jeder andere Schritt. Die Zuordnung ist **ein**
Prädikat und seine Verneinung: Jeder Schritt, auch ein künftiger, liegt in genau einem Teil. Der Smoke-Test gehört zu
`gui`, weil er dieselbe Tauri-Build und dasselbe Display braucht und vor den GUI-Suiten den Fehler eingrenzt;
`web Playwright E2E` gehört zu `rest`.

Gefiltert wird wie bei `--step` in `want_step`: Ein Schritt außerhalb des Teils läuft nicht und erscheint nicht im
Artefakt (kein SKIP), `--step` innerhalb eines Teils sucht nur dort. Ein unbekannter Teil ist Exit 2. Unter `--strict`
gilt weiter „kein Schritt lief“ als Fehler, je Teil.

### 3. Zwei Warm-Slots

Die zweite Box ist ein Warm-Slot `gui` derselben Lane: `warm.sh gui` klont `--profile linux-full --role gui` und
bootstrappt `full` wie `desktop`; die Rolle `gui` hat in `profiles.json` die Form von `desktop`, damit `vm.py` ihren
RAM vor dem Klon prüft und der Reaper, `list` und `reap.sh` sie wie jeden Slot behandeln. `iter.sh --slot gui …`
fährt auf ihr (Box, Name für `--expect-name`, Frist `gui_ttl`), ohne `--slot` bleibt alles beim Slot `desktop`.
`reap.sh --role gui` gibt nur diesen Slot frei. Weil zwei Wrapper desselben Checkouts nun gleichzeitig `warm.env`
schreiben können, schreibt `lib.sh` nur unter `flock`.

Kevins eigener Schnell-Loop nutzt weiter `desktop`; die GUI-Box gehört dem Sammellauf.

### 4. `heavy.sh all` mit zwei Teilen

1. **Pre-flight:** `vm.py doctor --roles` nennt die Rollen, deren Slot im Listing keine laufende Box hat (heute
   immer `desktop`, auch wenn die Box wiederverwendet wird; mit zwei Rollen würde das doppelt zählen).
2. **Box `desktop` leasen** wie heute (ein Retry, Exit 2 ohne Retry); scheitert das, ist der Lauf `UNVERIFIED`, und
   nichts startet.
3. **Beide Teile starten:** Teil `gui` im Hintergrund: `warm.sh gui` (ein Retry), dann
   `iter.sh --slot gui all --strict --part gui`; Teil `rest`: `iter.sh all --strict --part rest`. Die GUI-Box wird
   also geleast, während `rest` schon läuft. Jeder Teil zieht in sein eigenes Verzeichnis (`AH_OUT_DIR=$OUT/<teil>`),
   sein Log ist `$OUT/all-<teil>.log`, stdin ist `/dev/null`. Ein `trap` beendet beide Jobs, wenn `heavy.sh` selbst
   abgebrochen wird.
4. **Warten, dann je Teil auswerten** mit der heutigen Logik (Summary-Zeile, Infra-Marker, Artefakt-Prüfung,
   `strict-failed`, Schritte, Klassifikation). Wiederholungen roter Schritte laufen auf der Box **ihres** Teils
   (`iter.sh --slot <slot>`, `AH_NO_SYNC=1`), die Zweit-VM-Prüfung wie heute in der Lane `w2`.
5. **Kombinieren:** Infra in einem Teil (Box nicht zu bekommen, Infra-Marker, Exit 74, `strict-failed`, kein Beleg)
   macht den Lauf `UNVERIFIED`; der Grund nennt den Teil und, falls der andere Teil rot ist, auch das (heute würde
   `set_fail` nach `set_infra` still verworfen, `heavy.sh:104-112`). Sonst `FAIL`, wenn ein Teil nach der
   Klassifikation rote Schritte hat oder sein Wrapper ohne roten Schritt rot endete. `PASS` nur mit zwei grünen
   Teilen.
6. **Report:** beide Summary-Zeilen mit Etikett, die Schritt-Tabelle mit allen Schritten beider Teile (Sekunden, Box),
   eine Ebenen-Zeile mit Wandzeit, beiden Boxen und im Detail den Sekunden je Teil. JUnit beider Teile landet in
   `$OUT/junit/` (die Namen sind je Schritt eindeutig), Screenshots und Logs bleiben unter `$OUT/<teil>/`.
7. **Platz für eine dritte Box:** Vor einer Zweit-VM-Prüfung und vor dem Capstone (`weekly`) gibt `heavy.sh` die
   GUI-Box frei (`reap.sh --role gui`). Mit zwei gehaltenen Boxen passt die `w2`-Box bzw. passen die
   Capstone-Rollen sonst nicht, und ein Kandidat endete `unbestaetigt` statt `reg`/`extern` — das wäre eine
   Verschlechterung gegenüber heute.
8. **Nach dem Lauf** (offene Frage 1, Empfehlung): Ist Teil `gui` grün, gibt `heavy.sh` die GUI-Box frei; ist er rot,
   bleibt sie zur Sichtung stehen (Frist wie jede Warm-Box), sofern 7 sie nicht schon freigegeben hat.
9. **Zweite Box nicht zu bekommen** (offene Frage 2, Empfehlung): Teil `gui` läuft nach Teil `rest` seriell auf der
   Box `desktop`, der Report sagt es in einer Notiz. Ohne diese Task ist der Lauf dann `UNVERIFIED`.

## Trade-offs & Alternativen

- **Evidenz: Client vor Box (gewählt)** gegen (a) `.git` vom Sync ausnehmen: Eine Warm-Box behielte ihr altes
  `.git` (ausgenommene Pfade löscht `--delete` nicht), und `git rev-parse HEAD` nennte einen alten Commit — schlimmer
  als heute. (b) Hash auf der Box beim **Start** rechnen und `.gitkeep` in den Sync nehmen: zwei Änderungen, und jede
  künftige nicht ignorierte Datei unter einem ausgenommenen Pfad bricht es wieder. (c) Eine Lauf-Kennung (Nonce)
  statt des Tree-Vergleichs: genau für „gehört das Artefakt zu diesem Lauf?“, aber ein neues Feld durch drei Skripte,
  und `head`/`tree_hash` im Artefakt blieben falsch.
- **Teilung per `--part` (gewählt)** gegen ein allgemeines `--skip <namen>`: Mit einer Liste in `heavy.sh` könnte ein
  neuer Schritt in keinem Teil landen und still fehlen; das Prädikat in `run.sh` schließt das aus.
- **Zweiter Slot in derselben Lane (gewählt)** gegen eine zweite Lane mit eigenem Worktree (wie `w2`): Ein Worktree je
  Lauf hieße jedes Mal eine kalte Box und ein Sync ohne Repo; die Slot-Lösung nutzt `warm.sh`/`iter.sh`/`reap.sh`,
  wie sie sind.
- **GUI-Box mitten im `rest`-Lauf leasen (gewählt)** gegen beide Boxen vor dem Start: Eine kalte GUI-Box (Bootstrap
  ~18 min, Tauri-Build ~20 min laut `/test`-Skill) läge sonst vor dem `rest`-Teil.
- **Wandzeit** (Schätzung, nicht verifiziert): `rest` ≈ 5867 s − ~1800 s GUI ≈ 68 min; `gui` warm ≈ 30 min, kalt
  ≈ 18 + 20 + 30 ≈ 68 min. Der Lauf wird also etwa 30 min kürzer, und der `rest`-Teil bestimmt die Wandzeit, auch
  wenn die GUI-Box kalt startet. Ob zwei Boxen mit je 6 Kernen den Host-CPU teilen müssen und dadurch langsamer
  werden, ist nicht verifiziert (`vm.py doctor` prüft nur RAM); der Beweislauf misst es.

## Risiken & Rollback

- **Kapazität:** Zwei Desktop-Boxen belegen während des Laufs den Großteil des freien RAM; andere Lanes können in
  dieser Zeit keine Desktop-Box klonen (`vm.py` lehnt mit `capacity` ab, ein Fehler mit Grund, kein stiller). Die
  Zahlen stehen im Bericht an Kevin, nicht hier.
- **Test-Umbau `heavy_test.sh`:** Die Shims zählen heute Aufrufe; zwei Teile laufen gleichzeitig. Die Shims werden
  je Slot geführt, bestehende Assertions bleiben; wo eine erwartete Zahl sich gewollt ändert, nennt der Commit-Body
  die Stelle. Vorher ein reiner Refactor mit unverändertem Test.
- **Ein laufendes `heavy.sh` nie im selben Checkout ändern** (bash liest inkrementell): Gebaut wird im Worktree.
- **Rollback:** Revert des Merge-Commits; `.vm/warm.env` bleibt lesbar (ein übrig gebliebener Slot `gui` ist eine
  laufende Box, die `reap.sh` oder der Reaper nimmt).

## Doku-Impact

`DEVELOPMENT.md` (Schwere Suites, Schneller Loop, Wochenlauf), `docs/developer/cicd.html` + EN (Flag-Tabelle von
`run.sh`, Abschnitt Wochenlauf), `.claude/skills/test/SKILL.md` (Dauer, zwei Summary-Zeilen, Slots),
`.claude/skills/vm/SKILL.md` (`warm.sh gui`, `iter.sh --slot`, `reap.sh --role`), `.claude/rules/testing.md`
(Flags von `run.sh`), `CHANGELOG.md` (Fixed: Schritt-Tabelle; Changed: zwei Boxen).

## Offene Fragen (Kevins Bereich, je mit Empfehlung)

1. **GUI-Box nach dem Lauf:** freigeben, wenn ihr Teil grün ist (Empfehlung), oder 8 h warm halten? Warm halten
   spart dem GUI-Teil etwa 40 min, die Wandzeit aber kaum, weil `rest` sie bestimmt; dafür bleiben 6 GiB bis zu
   8 h belegt. → T11 `[?]`.
2. **Zweite Box nicht zu bekommen:** GUI-Teil seriell auf der ersten Box (Empfehlung; ein Lauf mit ~100 min statt
   eines verlorenen) oder `UNVERIFIED`? → T12 `[?]`.

## Nicht verifiziert

- Ob auf der echten Box neben der fehlenden `.gitkeep` weitere vom Lauf angelegte, nicht ignorierte Dateien den
  Hash verschieben (für den Fix ohne Belang).
- Wandzeit und CPU-Konkurrenz zweier Boxen; Bootstrap- und Build-Zeiten einer kalten GUI-Box (Zahlen aus dem
  `/test`-Skill). Der Beweislauf (`Heavy:` im Ledger) misst sie.
