# Harness: exakter Schrittname, Einstufung nicht ansprechbarer Schritte, Probelauf ohne Abräumen (kern-harness-3)

Roadmap: R-1148, R-1206, R-1153 (alle vor dem Release 0.47.0, R-1110; Harness-Änderung auf Kevins Wort,
Triage 2026-11-09). R-1157 aus demselben Zug wandert in `tasks/kern-harness-4.md` (Gründe unten).

## Problem / Motivation
- **R-1148:** `run.sh --step <name>` sucht Teilzeichenketten (`want_step`, `scripts/tests/run.sh:239`). Ist ein
  Schrittname Präfix eines anderen (`desktop_e2e_connect` und `desktop_e2e_connect_tunnel`), lehnt der Trockenlauf
  (`run.sh:1000`) ihn als mehrdeutig ab; der kürzere Schritt lässt sich nie allein fahren.
- **R-1206:** `heavy.sh` wiederholt einen roten Schritt (`rerun_step`, `heavy.sh:694`) und prüft ihn auf einer
  zweiten VM (`w2_run`, `heavy.sh:762`) mit `run.sh all --strict --step <schritt>`. Ist der Name mehrdeutig, endet
  jeder dieser Läufe mit `ambiguous step` und Exit 2, ohne dass der Schritt lief. `classify_red_step` und
  `second_vm_check` (`heavy.sh:707`, `:833`) werten das als rot; im Sammellauf 2026-11-09 wurde
  `desktop_e2e_connect` so als `extern` eingestuft, obwohl Retry und Gegenprobe nie stattfanden. Die Gegenprobe
  auf dem letzten PASS-Commit fährt dessen `run.sh`: auch nach dem Fix von R-1148 bleibt der Schritt dort
  mehrdeutig.
- **R-1153:** `vm.py reap --dry-run` räumt trotzdem ab: `auto_reap` (`scripts/vm/vm.py:2126`) läuft nach jedem Verb
  außer `list` und `doctor` (`vm.py:2201`), also auch nach dem Probelauf, und zerstört abgelaufene VMs der eigenen
  Lane.

## Ziel & Nicht-Ziele
- `--step` mit einem Namen, der genau einem Schritt **gleicht**, fährt diesen einen Schritt, auch wenn er Präfix
  eines anderen ist; ein Teilstring, der mehrere trifft und keinem gleicht, bleibt mehrdeutig (Exit 2).
- `heavy.sh` erkennt einen Retry- oder Zweit-VM-Lauf, der mit `ambiguous step`/`unknown step` endete, als „Schritt
  nicht ansprechbar“: im Retry `infra` (der Lauf konnte nicht laufen), in der Zweit-VM `unbestaetigt`, nie `extern`
  oder `reg`.
- `vm.py reap --dry-run` ändert nichts, auch nicht über den Lane-Sweep.
- Nicht-Ziel: Schritte umbenennen; die Klassifikationslogik sonst ändern.

## Betroffene Komponenten & Dateien
`scripts/tests/run.sh`, `scripts/tests/run_flags_test.sh`, `scripts/tests/heavy.sh`, `scripts/tests/heavy_test.sh`,
`scripts/vm/vm.py`, `scripts/vm/tests/test_vm.py`, `docs/developer/cicd.html`, `docs/en/developer/cicd.html`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- **R-1148, exakter Treffer gewinnt (gewählt):** kleinste Änderung, alle bisherigen Teilstring-Aufrufe bleiben
  gültig. Alternative „nur exakt“: bricht `--step ruff` und Co. in Ledgern und Doku.
- **R-1206, Marker im Log (gewählt):** `run.sh` druckt die beiden Fehlermeldungen am Zeilenanfang; heavy.sh liest
  sie aus dem Log des Laufs. Alternative eigener Exit-Code für „nicht ansprechbar“: der alte Basis-Commit hätte ihn
  nicht, die Gegenprobe dort bliebe falsch eingestuft.
- **R-1153:** der Sweep entfällt nur bei `reap --dry-run`; jedes andere Verb sweept weiter.

## Risiken & Rollback
Harness-Pfade: ein Fehler in `want_step` könnte einen anderen Schritt fahren als gewollt; die Flag-Tests prüfen
exakten Treffer, Teilstring und Mehrdeutigkeit. Rollback je Task per Revert.

**R-1157 wandert:** Die eigene known_hosts-Behandlung ändert `desktop_e2e_connect.sh`, einen GUI-Schritt; beweisen
lässt sie sich nur auf einer Box (Heavy `linux-full`). Solange der Sammellauf rot ist, merged die Session kein
Vorhaben mit `linux-full`; dieser Zug bleibt mit `none` mergebar.

## Doku-Impact
`docs/developer/cicd.html` DE+EN: `--step` (exakter Name gewinnt) und die `infra`/`unbestaetigt`-Zeilen der
Einstufung; CHANGELOG nicht nötig (Harness, nicht ausgeliefert).

## Offene Fragen
Keine.
