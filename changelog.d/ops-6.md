<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

### Fixed

- **install.sh/update.sh: `$` vor einem nicht gesetzten Namen in der `.env` (R-1051):** docker compose setzte diesen
  Teil eines Werts still leer (`$NAME`, `${NAME}`) oder brach jeden Aufruf ab (`${NAME?…}`). Beide Skripte halten
  jetzt vor dem ersten Compose-Aufruf an und nennen nur die Zeile; `$$` und einfache Quotes bleiben der Weg fuer ein
  woertliches `$`. Fehlermeldungen von docker compose geben beide Skripte einheitlich aus.
- **install.sh: `--admin-user` wird vor dem Start geprueft (R-1057):** ein Name ausserhalb von 3 bis 64 Buchstaben,
  Ziffern, `.`, `_` oder `-` endet sofort mit Exit 2, statt die Installation erst nach `docker compose up`
  abzubrechen.
- **update.sh: gescheitertes Backup-first (R-1050):** die Meldung ist jetzt englisch; ein Test belegt, dass das Update
  dann ohne Aenderung endet.
