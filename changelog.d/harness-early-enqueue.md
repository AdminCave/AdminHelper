### Changed

- **Merge Queue: frueher einreihen:** Jeder Check eines Pull Requests ist jetzt Pflicht-Check (ausser `Changed paths`
  und den einzelnen Shards, deren Sammel-Jobs Pflicht sind), und die Queue fasst bis zu drei Pull Requests zu einer
  Gruppe zusammen. Eine Session reiht ihren Pull Request gleich nach dem Erstellen ein; Auto-Merge wartet auf die
  Pflicht-Checks.
