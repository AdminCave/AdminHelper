---
name: roadmap
description: Show AdminHelper's roadmap (tasks/private/ROADMAP.md) at a glance and triage its new rows with Kevin — /roadmap renders "Als Nächstes", In Arbeit with the WIP caps and Neu as a count; /roadmap triage walks the `neu` rows via AskUserQuestion (accept, reject, defer, bundle). Every change goes through scripts/dev/roadmap.py, never as an edit of the file.
---
<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `/roadmap` — der rote Faden, gezeigt und triagiert

`tasks/private/ROADMAP.md` ist Kevins Datei im privaten Repo und die einzige
Reihenfolge-Wahrheit (CLAUDE.md §2). Dieser Skill **liest** sie über `roadmap.py` und
**ändert** sie nur über `roadmap.py`: flock, `.bak`, Zeilenzahl-Prüfung und ein lokaler
Commit je Schritt kommen von dort (DEVELOPMENT.md, „Die Roadmap als Skript").

**Nie:** `Edit`/`Write` auf die Datei · „Als Nächstes" umschreiben (das kuratiert Kevin von
Hand; der Skill darf einen Vorschlag machen, nicht schreiben) · `approve` ohne Kevins
ausdrückliches Wort (die Freigabe ist sein einziger Pflicht-Checkpoint) · das private Repo
pushen (den Befehl nennen, Kevin führt ihn aus).

Alle Aufrufe ohne `--file`: der Default ist die echte Datei. Exit-Codes von `roadmap.py`
sind Anweisungen: **2** Aufruf oder Übergang falsch (Meldung zeigen, nicht umgehen) ·
**3** `neu`-Deckel voll · **4** Dublette (die Meldung nennt die offene Zeile) · **5** die
Datei wurde gerade von Hand geändert (Kevin fragen, ob sein Editor offen ist; nicht
wiederholen, bis er es sagt) · **6** Zeilenzahl passte nicht, `.bak` ist zurückgespielt
(STOPP, berichten).

## `/roadmap` — der Überblick

1. `python3 scripts/dev/roadmap.py show` (liest nur, keine Sperre).
2. Knapp rendern, in dieser Reihenfolge:
   - **Als Nächstes**: die Punkte, je die erste Zeile, wörtlich.
   - **In Arbeit** mit den Deckeln: die `WIP:`-Zeile. `show` druckt nur die Zähler; ist
     ein Deckel erreicht (Zähler >= `aktiv` 1 · `bereit` 2 · `pr` 3 · `neu` 20), schreib
     selbst `Warnung:` mit dem Deckel dahinter (CLAUDE.md §3, Warn-Trigger 3). Die Zeilen
     von „In Arbeit" mit ID, Klasse, Status.
   - **Neu**: nur die Anzahl gegen den Deckel und `ALT` (abgelaufene Zeilen), keine Liste.
   - Geplant, Zurückgestellt, Blockiert als Anzahl; Abgeschlossen und Archiv weglassen.
3. `python3 scripts/dev/roadmap.py lint`. Funde: Anzahl und die ersten drei nennen, nichts
   reparieren — eine doppelte ID oder eine kaputte Zeile ist Kevins Handarbeit. Eine
   Abweichung von `ALT` im Kopf ist keine: der nächste Schreibvorgang rechnet den Kopf neu.
4. Steht `neu` am Deckel (>= 20: ab da verweigert `add`, und `heavy.sh` bekommt für einen
   Fund keine Zeile mehr) oder ist `ALT` > 0: `/roadmap triage` vorschlagen, ein Satz.

## `/roadmap triage` — die neuen Zeilen mit Kevin

1. **Stand.** `roadmap.py show` und `roadmap.py lint`. Meldet `lint` eine `neu`-Zeile im
   falschen Abschnitt, gehört sie trotzdem in die Triage (sie ist `neu`).
2. **Reihenfolge.** Die `neu`-Zeilen nach Klasse (SEC > REG > REL > BUG > FEAT > REF >
   IDEE), innerhalb der Klasse in der Reihenfolge der Datei. Zu jeder Zeile
   `roadmap.py show R-nnnn` lesen (Quelle, Beweis, Ablauf, Dedup-Key).
3. **Fragen, 2–4 Zeilen je Runde** in **einem** `AskUserQuestion`-Aufruf, eine Frage je
   Zeile. Header `R-nnnn`, Frage: Klasse, Titel, Quelle in einem Satz. Die **Empfehlung
   zuerst**, mit „(Empfohlen)" und einem Halbsatz Begründung in der Beschreibung:
   - **Annehmen** → `roadmap.py status R-nnnn geplant`. Danach `/feature-plan --kurz R-nnnn`
     *vorschlagen*, nicht starten (den Kurz-Modus bringt Stufe 5b; bis dahin
     `/feature-plan` mit der Zeile als Auftrag).
   - **Ablehnen** → `roadmap.py status R-nnnn abgelehnt --note "<Grund>"`. Ohne Grund
     kein Ablehnen: fehlt er in Kevins Antwort, einmal nachfragen.
   - **Zurückstellen** → `roadmap.py status R-nnnn zurückgestellt [--note "<bis wann/warum>"]`.
   - **Bündeln** (nur REF, ≥ 2 Zeilen derselben Komponente in dieser Triage) → noch kein
     Status; am Ende `/feature-plan --bundle R-a,R-b` vorschlagen (auch das bringt 5b).
   - **REG**: die Annehmen-Option heißt „Annehmen, Regression bestätigt" und setzt
     `status R-nnnn geplant --note "Regression bestätigt"` — der Haken ist die Notiz.
     Hält Kevin sie für nicht reproduziert: Ablehnen mit diesem Grund.
   Empfehlung, in dieser Reihenfolge: SEC/REG/BUG mit Beweis → Annehmen · „Beweis fehlt"
   → Zurückstellen · abgelaufenes REF/IDEE (`Ablauf` vorbei) → Ablehnen, Grund
   „abgelaufen" · mehrere REF einer Komponente → Bündeln · sonst Annehmen.
4. **Ausführen.** Nach jeder Runde die gewählten Verben einzeln, jeweils mit Exit-Code
   berichten. Ein Exit ≠ 0: die Meldung zeigen und die Runde dort anhalten (siehe oben).
   Dann die nächste Runde, bis keine `neu`-Zeile mehr offen ist oder Kevin aufhört; die
   letzte Runde darf eine einzige Zeile haben.
5. **Abschluss.** `roadmap.py show --wip` und eine Zeile je Entscheidung (ID → Status). Dann
   den Push des privaten Repos **nennen**, nicht ausführen:
   `git -C tasks/private push`.

## Was dieser Skill nicht tut

Er gibt nichts frei (`approve` sagt Kevin selbst: „R-nnnn freigeben" → dann und nur dann
`roadmap.py approve R-nnnn`), plant nichts (das ist `/feature-plan`), schreibt kein
„Als Nächstes" und legt keine Zeilen an (`add` gehört den Findern, `heavy.sh` und Kevin).
