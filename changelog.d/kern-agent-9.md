### Fixed

- **Monitoring: Container mit vielen exponierten Ports:** meldete ein Container 64 oder mehr exponierte Ports und
  keine lauschenden, galt ein Port jenseits der ersten 64 als fehlend, und ein Katalog-Check auf diesen Port wurde
  nicht angelegt; eine volle Liste gilt jetzt als unbekannt, der Agent waehlt den Port beim Pruefen.
