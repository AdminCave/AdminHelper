<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-3 — Admin-Uebersicht DE/EN angleichen (Roadmap R-0525)

## Problem
`docs/en/admin/index.html` und `docs/admin/index.html` sind verschieden gegliedert. DE hat „Komponenten auf einen
Blick“, „Typische Admin-Aufgaben“, „Architektur in einem Absatz“ und „Versionen“; EN hat „Stack at a Glance“,
„Reading Order“ und „Prerequisites“. Dazu behauptet EN :43 „Managed mTLS PKI (10 y CA / 1 y client certs)“. Gegen
`apps/ca-issuer/app/pki.py` geprueft: Root 3650 d, Intermediates 1825 d, Leafs 90 d (nativ) / 365 d (Browser) /
365 d (Gateway). Die massgebliche Stelle `docs/en/admin/operations.html:201` (und DE `betrieb.html:243`) nennt
Root 10 Jahre, Zwischenzertifikate 5 Jahre; „1 y client certs“ stimmt nur fuer Browser-Zertifikate.

## Ziel & Nicht-Ziele
- EN folgt der DE-Gliederung (DE ist die ausfuehrlichere und aktuell gepflegte Fassung); die EN-Lesereihenfolge
  bleibt als Liste unter „Typical admin tasks“ erhalten, die „Prerequisites“-Box bleibt.
- Die PKI-Aussage wird durch einen Verweis auf die Betriebsseite ersetzt statt Zahlen zu kopieren.
- Der Versionsabschnitt (DE nennt v0.37.2, aktuell 0.46.0) wird in beiden Sprachen auf die aktuelle Serie gezogen.
- Nicht-Ziel: Inhalt der anderen Admin-Seiten, DE-Umbau.

## Betroffene Dateien
`docs/en/admin/index.html`, `docs/admin/index.html` (nur Versionsabschnitt).

## Datenmodell / API / Externes
Keine.

## Trade-offs
Alternative: DE auf die EN-Kurzform kuerzen — verworfen, verliert die Workspaces- und Aufgaben-Texte.

## Risiken & Rollback
Reine Doku; Revert des Commits.

## Doku-Impact
Die beiden Index-Seiten selbst.

## Offene Fragen
Keine. `semantik`: docs/en/admin/operations.html:201 „consists of a root (10 years) and the intermediates … (5 years)“.
