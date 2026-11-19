<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Neuordnung, Phase 0: Abnahme der Screens und Kevins Entscheidungen

Roadmap R-1558 (FEAT, Architektur) mit R-1515 (IDEE) · Zug `arch-monitoring-neu-p0-abnahme` · Fortsetzung von
`arch-monitoring-neu-p0` (PR #573), dessen T12 und T13 hierher verschoben wurden. Stand des Codes: `origin/main@1d699f0af`.

## Problem / Motivation

Phase 0 hat ADR 0004, die Mockups unter `apps/desktop/ui/src/mockups/monitoring-neu/`, den Regel-Prototyp und die
Experimente gemergt. Offen blieben zwei Punkte des ADR, §14:

1. **Fragen 1–11.** Kevin hat sie am 2026-11-18 per Ask alle nach Empfehlung beantwortet, im ADR stehen sie aber
   noch als „offen“.
2. **Frage 12, Abnahme der Screens.** Kevin wollte die Screens zuerst sehen. Daraus wurden fünf Runden mit einem
   privaten Artefakt, gebaut in einer Wegwerf-Kopie des Mockups außerhalb des Baums:
   - **Runde 1:** Serverliste wie im heutigen Monitoring statt einer Lage ohne Server-Zuordnung.
   - **Runden 2–4:** übersichtlicher, mit Lagekarte, Karten-Board und Animationen.
   - **Runde 5:** Handy-Ansicht und sehr viele Server und Checks.

   Kevin hat Runde 5 am 2026-11-19 angenommen („Annehmen, umbauen“), dazu die Mengen-Grenzen „Wie im Mockup“.

Der Entwurf aus den Runden liegt nur in der Wegwerf-Kopie. Der Mockup-Baum im Repo zeigt noch den Stand von PR #573,
mit Reiter „Lage“, Server-Auswahl per Select und ohne Handy- und Mengenverhalten.

Bei der Abnahme hat Kevin zwei Punkte nachgelegt (2026-11-19): Auch mit sehr vielen Hosts und Checks muss die
Ansicht übersichtlich bleiben, ob mit Seiten, war offen. Und wo es Sinn ergibt, soll sich die Sortierung umstellen
lassen. Beides hat er am selben Tag per Ask entschieden (Ziel, Trade-offs).

## Ziel & Nicht-Ziele

**Ziel**

- Der Mockup-Baum im Repo zeigt den abgenommenen Entwurf der Runden 1–5, mit Tests:
  - **Serverliste links:** schlechteste zuerst, Suche „/“, Pfeiltasten. Ab 25 ruhigen Servern sind diese in einer
    Zeile eingeklappt.
  - **„Alle Server“ als Start:**
    - Lagekarte mit den 20 schlimmsten Servern und „alle zeigen“.
    - Flotten-Teppich ab 40 Servern.
    - Karten-Board mit 24 Karten, davon 8 mit Kennzahlen, dazu „weitere Server zeigen“.
    - Offene Probleme als Liste.
  - **Server-Seite:** folgt der Auswahl in der Serverliste, mit Vitalwerten und Objektart-Gruppen.
  - **Objektart-Gruppen:** Zeilen erst beim Öffnen, Seiten zu je 60. Bei mehr als 42 Objekten zeigt eine
    Gruppe einen Statusbalken statt Punkten.
  - **Seitengrößen:** Objekte 200 je Seite, Querschnitte 150 je Seite. Lange Listen zeigen den ersten Teil und
    darunter „N weitere anzeigen“, keine Seitenzahlen (Kevin 2026-11-19).
  - **Sortierung umstellbar** (Kevin 2026-11-19, per Ask):
    - Objekte und Querschnitte: Ein Klick auf den Spaltenkopf sortiert, ein zweiter dreht die Richtung
      (`aria-sort`). Danach beginnt die Liste wieder bei der ersten Seite.
    - Serverliste: Zustand oder Name. Die Trennung in „Mit Problemen“ und „Ohne Probleme“ bleibt.
    - Karten-Board von „Alle Server“: Zustand, Neueste (der Server mit dem jüngsten offenen Problem zuerst)
      oder Name.
    - Fest bleiben Lagekarte, „Neueste Probleme“, Objektart-Gruppen, „Ausgeblendet“ und „Abdeckung“.
    - Standard ist überall „schlimmste zuerst“. Ausgeblendete Objekte bleiben am Ende, leere Werte stehen in
      beiden Richtungen hinten.
    - Die Wahl gilt für die Sitzung: Reiter-, Server- und Datenwechsel behalten sie, ein Neuladen beginnt
      wieder beim Standard.
  - **Kennzahl-Balken** mit Warn- und Kritisch-Marke.
  - **Handy (≤ 760 px):**
    - Serverliste als Schublade, Escape schließt sie.
    - Eine Spalte, kein seitliches Überstehen. Breite Tabellen scrollen in ihrem Kasten.
    - Ein Reiterwechsel beginnt oben.
  - **Datenumschalter** „Normal“ / „Groß“: 292 Server mit 10 510 Objekten, deterministisch erzeugt.
  - **Animationen** nur mit `prefers-reduced-motion`-Abschaltung.
- ADR 0004 hält Kevins Antworten 1–11 wörtlich mit Datum fest, dazu die Abnahme mit den Runden, den Grenzen,
  den Seiten und der Sortierung.
  Status „angenommen“. Die Folgen für P2/P3 sind nachgezogen: Serverliste und „Alle Server“ statt einer eigenen
  Lage-Ansicht.

**Nicht-Ziele**

- Keine Produktansicht. „In die echte Desktop-UI“ heißt hier: in den Mockup-Baum des Repos statt der Wegwerf-Kopie.
  Die Produkt-Monitoring-Ansicht braucht das Objektmodell aus P1 (R-1559) und baut in P2/P3 (R-1560, R-1561) nach
  diesem Entwurf.
- Kein neues Verhalten in Server, Monitoring oder Agent, keine API, keine Migration, keine i18n-Schlüssel. Die
  Mockup-Texte bleiben deutsch, wie in P0 entschieden.
- Keine neue Abhängigkeit. Animationen nehmen `svelte/motion` und `svelte/transition` aus Svelte selbst.
- Kein Browser-Test in der CI für das Mockup (siehe Trade-offs).

## Betroffene Komponenten & Dateien

Nur `desktop-ui`, nur unter `apps/desktop/ui/src/mockups/monitoring-neu/`, dazu das ADR.

- **Bausteine:**
  - `grammar.ts`: neu `objectLabel` und `meterOf`.
  - `Meter.svelte` (neu).
  - `ObjectRow.svelte`: Balken, Handy-Zeilen, Klasse `is-hidden` statt `hidden`, weil `app.css` `.hidden` global
    ausblendet.
  - `ObjectDrawer.svelte`: gleitet ein.
  - `exceptions.ts`: nimmt `objectLabel`.
- **Zusammenfassung je Server und große Flotte:**
  - `views/servers.ts` (neu): `serverSummaries`, `lageByServer`, `BAR_ORDER`.
  - `views/StatusBar.svelte` (neu).
  - `fixtures/scale.ts` (neu) mit Test.
- **Listen-Ansichten:**
  - `views/KindGroups.svelte` (neu), von `KindsView.svelte` und der Server-Seite genutzt.
  - `views/ObjectsView.svelte`, `views/CrossView.svelte`: Seiten, Handy, `is-hidden`.
  - `views/CoverageView.svelte`: Tabellen im Scroll-Kasten.
- **Übersicht:** `views/ServerNav.svelte`, `views/Lagekarte.svelte`, `views/AllServers.svelte` (alle neu).
- **Rahmen:**
  - `MockupApp.svelte`: Serverliste, Reiter ohne „Lage“, Handy-Schublade, Datenumschalter, Scroll-Reset.
  - `views/ServerView.svelte`: kein eigenes Select mehr.
  - `views/Lage.svelte` entfällt, „Alle Server“ ersetzt sie.
- **Sortierung:**
  - `views/sorting.ts` (neu): Ordnungen und die Wahl je Ansicht für die Sitzung, ohne Speicher.
  - `views/ObjectsView.svelte`, `views/CrossView.svelte`, `views/cross.ts` (Sortwert je Zelle): Spaltenköpfe.
  - `views/ServerNav.svelte`, `views/AllServers.svelte`, `views/servers.ts` (jüngstes Problem je Server):
    Umschalter.
- **Tests:**
  - `views/views.test.ts`, `ObjectRow.test.ts`, `views/ExceptionDialog.test.ts` (Klasse `is-hidden`, neuer
    Rahmen).
  - Neu: `grammar.test.ts`-Fälle, `views/servers.test.ts`, `views/limits.test.ts`, `views/overview.test.ts`,
    `views/sorting.test.ts`.
  - `src/styles/tokens.test.ts` läuft in jedem `Verify:` mit: jedes `var(--x)` muss deklariert sein.
- **Doku:** `docs/adr/0004-monitoring-neuordnung.md` (§1 Status, §13, §14).

`isolation.test.ts` bleibt wie es ist und gilt weiter: kein Import aus dem Produkt, keine weitere Build-Eingabe.
`vitest.setup.ts` bleibt unverändert. jsdom kennt weder `matchMedia` noch `Element.scrollTo`. Die Mockup-Tests
setzen beides lokal vor ihren Imports (`vi.hoisted`), wie die übrigen Desktop-Tests ihre jsdom-Lücken lokal
stubben. Ein globaler Stub würde die Umgebung aller Desktop-Tests ändern.

## Datenmodell / API / Migrationen

Keine. Fixtures und Typen bleiben im Mockup (`model.ts` unverändert).

## Externe Integrationen

Keine. `MediaQuery` und `SvelteMap` (`svelte/reactivity`), `Tween` und `prefersReducedMotion` (`svelte/motion`)
gehören zu Svelte 5.57 im Lockfile.

## Trade-offs & Alternativen

- **Übernahme aus der Wegwerf-Kopie statt Neubau.** Die Kopie ist der abgenommene Stand: svelte-check ist sauber
  und die Proben grün. Die Tasks übernehmen sie Datei für Datei mit Tests und Prüfer. Ein Neubau würde Kevins
  Abnahme nicht mehr treffen.
- **Layout-Beweis per headless Chromium außerhalb der CI (empfohlen) statt Playwright im Desktop-UI-Paket.**
  - jsdom rechnet kein Layout. Behalten werden Grenzen, Falten, Seiten, faule Zeilen, Schublade, Escape,
    Scroll-Reset und Handy-Zustand, das deckt vitest ab.
  - Kein seitliches Überstehen bei 390 px, eine Spalte und die Reiterzeiten belegt die Probe aus den Runden gegen
    den Worktree-Build. Ihre Summary steht im Commit-Body von T5.
  - Ein Browser-Lauf in der PR-CI für ein Wegwerf-Mockup wäre eine neue Abhängigkeit für wenig Dauerwert. P2 baut
    die Produktansicht mit eigenen E2E.
- **Querschnitte 150, Objekte 200 je Seite.** So stehen sie im Mockup, das Kevin mit „Wie im Mockup“ angenommen hat.
  Die Ask-Beschreibung nannte „Objektlisten 200“, das ADR nennt beide Werte.
- **„N weitere anzeigen“ statt Seitenzahlen oder Endlos-Scrollen** (Kevin 2026-11-19, empfohlen):
  - Die Position bleibt, die Browsersuche findet alles Gezeigte, der Zähler nennt etwa „200 von 3 412“.
  - Mit Sortierung steht das Gesuchte im ersten Teil. Seitenzahlen sagen bei sortierten Listen wenig.
  - Endlos-Scrollen erreicht das Seitenende nie und hält tausende Zeilen im Browser.
- **Sortierung für die Sitzung** (Kevin 2026-11-19, empfohlen) statt dauerhaft je Ansicht: Ein frischer Blick
  beginnt immer bei den schlimmsten, ein Problem rutscht nie durch eine alte Wahl nach unten. Im Mockup hält ein
  Modul die Wahl im Speicher der Seite.
- **Lagekarte ohne Umschalter:** Ab 40 Servern zeigt sie 20 Zeilen. Nach Name wären das nicht mehr die
  schlimmsten. Kevin hat sie nicht gewählt.
- **Task-Zuschnitt nach Abhängigkeit:** Bausteine → Zusammenfassung → Listen → Übersicht → Rahmen. Jede Task ist
  für sich grün, weil neue Ansichten erst T5 im Rahmen verdrahtet.

## Risiken & Rollback

- **Dev-only.** Das Mockup kommt nicht in den Desktop-Build, das hält `isolation.test.ts` fest. Ein Fehler trifft nur
  den Vite-Dev-Server, und jeder Task-Commit lässt sich einzeln zurücknehmen.
- **Größe der Fixture:** 10 510 Objekte machen die Tests langsamer. Die Fixture entsteht beim Import, Tests mit
  Rendern nehmen sie nur, wo eine Grenze geprüft wird.
- **Globale CSS-Kollisionen:** `.card`, `.chip`, `.list`, `.hidden` usw. aus `app.css`. Die neuen Ansichten nehmen
  nur eigene Klassennamen. jsdom sieht solche Kollisionen nicht, die Probe schon.

## Doku-Impact

ADR 0004 (§1 Status „angenommen“, §13 P2/P3, §14 Antworten und Abnahme). `DEVELOPMENT.md` nennt nur den Einstieg
des Mockups und bleibt gültig. Keine Produkt-Doku, kein CHANGELOG-Fragment: das Mockup ist nicht im Build, so wie in
P0.

## Offene Fragen

Keine. Fragen 1–12 hat Kevin beantwortet, die Grenzen „Wie im Mockup“, Seiten und Sortierung am 2026-11-19.
