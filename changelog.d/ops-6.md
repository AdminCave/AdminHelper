<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

### Fixed

- **install.sh/update.sh: `$` vor einem nicht gesetzten Namen in der `.env` (R-1051):** docker compose setzte diesen
  Teil eines Werts still leer (`$NAME`, `${NAME}`) oder brach jeden Aufruf ab (`${NAME?…}`). Beide Skripte halten
  jetzt vor dem ersten Compose-Aufruf an und nennen nur die Zeile; `$$` und einfache Quotes bleiben der Weg fuer ein
  woertliches `$`. Fehlermeldungen von docker compose geben beide Skripte einheitlich aus.
