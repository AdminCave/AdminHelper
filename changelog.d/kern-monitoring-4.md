### Fixed

- **Monitoring-Verlauf und Server-Vergleich zeigen die neuesten Werte (R-1104):** der Zeitraum endete am letzten
  vollen Rasterschritt, die juengsten Daten fehlten bis zu einem Schritt (15 min bei 24 Std., 6 h bei 30 Tagen).
  Er endet jetzt am ersten Rasterpunkt ab jetzt.
