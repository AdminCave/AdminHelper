---
name: roadmap
description: Show AdminHelper's roadmap (tasks/private/ROADMAP.md) at a glance and triage its new rows with Kevin — /roadmap renders "Als Nächstes", In Arbeit with the WIP caps, the trains and Neu as a count; /roadmap triage walks the `neu` rows via AskUserQuestion (accept into a train, reject, defer). Every change goes through scripts/dev/roadmap.py, never as an edit of the file.
---
<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `/roadmap` — der rote Faden, gezeigt und triagiert

`tasks/private/ROADMAP.md` ist Kevins Datei im privaten Repo und die einzige
Reihenfolge-Wahrheit (CLAUDE.md §4). Dieser Skill **liest** sie über `roadmap.py` und
**ändert** sie nur über `roadmap.py`: flock, `.bak`, Zeilenzahl-Prüfung und ein lokaler
Commit je Schritt kommen von dort (DEVELOPMENT.md, „Die Roadmap als Skript").

**Nie:** `Edit`/`Write` auf die Datei · „Als Nächstes" umschreiben (das kuratiert Kevin von
Hand; der Skill darf einen Vorschlag machen, nicht schreiben) · `approve` (die Freigabe setzt
die Session nach dem Plan-Commit von `/feature-plan`, CLAUDE.md §4). Nach jeder Änderung
pusht die Session das private Repo (`git -C tasks/private push`, CLAUDE.md §11).

Alle Aufrufe ohne `--file`: der Default ist die echte Datei. Exit-Codes von `roadmap.py`
sind Anweisungen: **2** Aufruf oder Übergang falsch (Meldung zeigen, nicht umgehen) ·
**4** Dublette (die Meldung nennt die offene Zeile) · **5** die Datei wurde gerade von Hand
geändert (Kevin fragen, ob sein Editor offen ist; nicht wiederholen, bis er es sagt) ·
**6** Zeilenzahl passte nicht, `.bak` ist zurückgespielt (STOPP, berichten).

## `/roadmap` — der Überblick

1. `python3 scripts/dev/roadmap.py show` (liest nur, keine Sperre).
2. Knapp rendern, in dieser Reihenfolge:
   - **Als Nächstes**: die Punkte, je die erste Zeile, wörtlich.
   - **In Arbeit**: die `WIP:`-Zeile. `show` druckt nur Zähler, alle sind Anzeige, kein Deckel:
     `aktiv`, `bereit` und `pr` (CLAUDE.md §2, „Parallel, wo es geht“) wie `neu` (`add` nimmt
     jede neue Zeile an, Kevin 2026-10-22). Die Zeilen von „In Arbeit" mit ID, Klasse, Status.
   - **Neu**: nur die Anzahl und `ALT` (abgelaufene Zeilen), keine Liste.
   - Geplant, Zurückgestellt, Blockiert als Anzahl; Abgeschlossen und Archiv weglassen.
   - **Züge**: `python3 scripts/dev/roadmap.py zuege`, je Zug eine Zeile (Ledger, Stufe, wartet/unterwegs, Zeilen).
3. `python3 scripts/dev/roadmap.py lint`. Funde: Anzahl und die ersten drei nennen, nichts
   reparieren — eine doppelte ID oder eine kaputte Zeile ist Kevins Handarbeit. Eine
   Abweichung von `ALT` im Kopf ist keine: der nächste Schreibvorgang rechnet den Kopf neu.
4. Steht `neu` bei 20 oder mehr (die Zahl hinter dem Strich im Kopf; `add` nimmt trotzdem
   an) oder ist `ALT` > 0: `/roadmap triage` vorschlagen, ein Satz.

## `/roadmap triage` — die neuen Zeilen mit Kevin

1. **Stand.** `roadmap.py show` und `roadmap.py lint`. Meldet `lint` eine `neu`-Zeile im
   falschen Abschnitt, gehört sie trotzdem in die Triage (sie ist `neu`).
2. **Reihenfolge.** Die `neu`-Zeilen nach Klasse (SEC > REG > REL > BUG > FEAT > REF >
   IDEE), innerhalb der Klasse in der Reihenfolge der Datei. Zu jeder Zeile
   `roadmap.py show R-nnnn` lesen (Quelle, Beweis, Ablauf, Dedup-Key). Dazu einmal
   `roadmap.py zuege`: welche Züge warten (nehmen Zeilen auf) und welche unterwegs sind
   (nehmen keine mehr). Zwei `neu`-Zeilen mit demselben Fund: Zusammenlegen vorschlagen
   (die jüngere `abgelehnt --note "Dublette von R-nnnn"`).
2a. **Zug je Zeile** (Kevin 2026-10-29), für die Annehmen-Option vorab bestimmen. Der Zug ist
   ein Ledger-Pfad `tasks/<zug>.md`; Zeilen mit demselben Schlüssel fahren zusammen, egal welche
   Klasse sie haben. Schlüssel = Stufe + Bereich + Art + schwere Prüfung (`Heavy:`) + wer merged:
   - **Klein-Session** (`klein-`): Doku-Drift, veraltete Kommentare, Test-Lücken, kleine REF ohne
     Verhaltensänderung, kleine UI-Fehler und i18n — `klein-doku-<n>`, `klein-kommentare-<komp>-<n>`,
     `klein-tests-<komp>-<n>`, `klein-ref-<komp>-<n>`, `klein-ui-<app>-<n>`.
   - **Kern-Session**: `ops-<n>` (install/update/restore, Kevin merged), `ci-<n>` (`.github/workflows/`,
     Kevin merged), `kern-<bereich>-<n>` (BUG mit Datenpfad, FEAT, größere REF, und SEC: der Name bleibt
     neutral, nie `sec-` — Branch und Ledger sind öffentlich, bevor der Fix released ist), ein Thema über
     mehrere Zeilen unter eigenem Slug.
   - **Einzeln** (eigener Slug, kein Zug): REG, ein BUG mit Nutzerwirkung (fährt sofort),
     Architektur über Komponenten (`start-session.sh arch`, Ledger `tasks/arch-<…>.md`: die Stufe
     `arch` nimmt weder die Kern- noch die Klein-Session auf).
   - Ein Zug nimmt nur Zeilen derselben schweren Prüfstufe und desselben Mergers; höchstens 15
     Tasks. Ist der passende Zug voll oder unterwegs, der nächste (`<n>+1`).
   - Ändert ein offener Branch die Dateien der Zeile (`bash scripts/dev/overlap.sh <dateien>`), gehört
     sie in den Zug dieses Branches, wenn er noch wartet, sonst in den nächsten.
3. **Fragen, 2–4 Zeilen je Runde** in **einem** `AskUserQuestion`-Aufruf, eine Frage je
   Zeile. Header `R-nnnn`, Frage: Klasse, Titel, Quelle in einem Satz. Die **Empfehlung
   zuerst**, mit „(Empfohlen)" und einem Halbsatz Begründung in der Beschreibung:
   - **Annehmen in <zug>** → `roadmap.py status R-nnnn geplant --ledger tasks/<zug>.md`; die
     Option nennt den Zug. Einzeln: `--ledger tasks/<slug>.md` und `/feature-plan --kurz R-nnnn`
     *vorschlagen*, nicht starten — bei SEC nicht: SEC kommt in einen neutral benannten Kern-Zug
     (feature-plan 3a).
   - **Ablehnen** → `roadmap.py status R-nnnn abgelehnt --note "<Grund>"`. Ohne Grund
     kein Ablehnen: fehlt er in Kevins Antwort, einmal nachfragen.
   - **Zurückstellen** → `roadmap.py status R-nnnn zurückgestellt [--note "<bis wann/warum>"]`.
   - **REG**: die Annehmen-Option heißt „Annehmen, Regression bestätigt" und setzt
     `status R-nnnn geplant --note "Regression bestätigt"` — der Haken ist die Notiz.
     Hält Kevin sie für nicht reproduziert: Ablehnen mit diesem Grund.
   Empfehlung, in dieser Reihenfolge: SEC/REG/BUG mit Beweis → Annehmen · „Beweis fehlt"
   → Zurückstellen · abgelaufenes REF/IDEE (`Ablauf` vorbei) → Ablehnen, Grund
   „abgelaufen" · sonst Annehmen in den Zug aus 2a.
4. **Ausführen.** Nach jeder Runde die gewählten Verben einzeln, jeweils mit Exit-Code
   berichten. Ein Exit ≠ 0: die Meldung zeigen und die Runde dort anhalten (siehe oben).
   Dann die nächste Runde, bis keine `neu`-Zeile mehr offen ist oder Kevin aufhört; die
   letzte Runde darf eine einzige Zeile haben.
5. **Abschluss.** `roadmap.py show --wip`, `roadmap.py zuege` und eine Zeile je Entscheidung
   (ID → Status, Zug). Dann
   das private Repo pushen: `git -C tasks/private push` (CLAUDE.md §11).

## Was dieser Skill nicht tut

Er gibt nichts frei (`approve` setzt die Session nach dem Plan-Commit von
`/feature-plan`, CLAUDE.md §4), plant nichts (das ist `/feature-plan`), schreibt kein
„Als Nächstes" und legt keine Zeilen an (`add` gehört `heavy.sh`, dem Gate von `/feature-plan`
und Kevin).
