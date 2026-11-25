### Added

- **Monitoring: Ausnahmen:** `/api/monitoring/exceptions` (admin-only) legt Ausnahmen an, die fuer einen Check, einen
  Check-Typ, einen Server oder alle Server gelten, dauerhaft, einmalig oder woechentlich, und deren Benachrichtigungen
  unterdruecken (`no_notify`, collect-but-mute); gelten mehrere, zaehlt die engste. Wer eine Ausnahme oder ein
  Wartungsfenster anlegt, aendert oder beendet, wird festgehalten. Das Update uebernimmt die Wartungsfenster als
  Ausnahmen.
- **Monitoring: ausgeschlossene Objekte:** Was eine Einstellung eines Checks ausblendet (`ignore_devices`,
  `ignore_mounts`, `ignore`, `exclude_vmids`, `ignore_containers`), fuehrt die Objekt-API als nicht erhoben mit dem
  Namen der Einstellung, am Ende der Liste; jedes Objekt nennt im Feld `exception`, was es ausnimmt.

### Changed

- **Monitoring: Wartungsfenster loeschen beendet sie:** Ein geloeschtes Wartungsfenster gilt nicht mehr, bleibt aber
  90 Tage nachvollziehbar. Der Stummschalt-Grund einer Ausnahme, die kein Wartungsfenster ist, heisst `exception`.
