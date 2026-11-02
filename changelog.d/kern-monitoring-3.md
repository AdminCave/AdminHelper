### Added

- **Desktop: Verlauf eines Servers im Monitoring:** Das Dashboard eines Servers mit Agent-Daten zeigt CPU, RAM,
  Swap, Speicher je Mount, Latenz und Load je CPU ueber 1 Std., 24 Std., 7 Tage oder 30 Tage, mit Vorperiode,
  Schwellen, Statuswechseln, Wartungsfenstern, Zoom, Kennzahlen, Speicher-Prognose und CSV-Export.
- **Desktop: Server vergleichen:** Der Reiter Verlauf der Monitoring-Seite vergleicht CPU, RAM, Speicher oder Load
  je CPU ueber alle Server mit Agent-Daten, mit Rangliste und bis zu vier Servern im Chart.
- **Monitoring:** Das Monitoring speichert Swap und die CPU-Zahl aus dem Agent-Report als eigene Serien und bietet
  dazu `/status/server/{id}/history` und `/status/compare`, und `/checks/{id}/metrics` kennt den Zeitraum 30d.
