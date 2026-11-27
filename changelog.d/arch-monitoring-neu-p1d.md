### Added

- **Monitoring: eigene Schwellen ueberstehen Katalog-Updates:** Was der Admin an den Regeln eines Modul-Checks aendert
  (Grenze, Entwarnung, Stufe, an/aus), haelt der Dienst je Regel getrennt vom Katalog fest und legt es beim Uebernehmen
  einer neuen Katalog-Definition ueber die neuen Regeln; Konflikte nennen `GET /api/monitoring/checks/{check_id}/rules`
  und das Log. `PUT /api/monitoring/checks/{check_id}/rules` setzt die Aenderungen (admin-only). Regeln, die mit einer
  aelteren Version geaendert wurden, rechnet der Dienst beim Start um, wo das genau geht; sonst bleiben sie wie bisher
  eingefroren.
- **Monitoring: Entwarnung und Bedingung fuer Probe-Regeln:** Eine Regel kann `clear` tragen (sie haelt nach dem
  Anschlagen, bis der Wert die Entwarnung erreicht) und `when` (sie gilt nur, solange eine Bedingung ueber ein Feld
  desselben oder eines anderen Probe-Checks derselben Instanz gilt; fehlt der Wert oder ist er veraltet, bewertet sie
  trotzdem).

### Changed

- **Monitoring: Uebernehmen behaelt geaenderte Regeln:** Bisher blieb ein Check, dessen Regeln der Admin geaendert
  hatte, beim Uebernehmen einer neuen Katalog-Definition bei der alten; jetzt bekommt er die neue Definition mit den
  Aenderungen des Admins darueber. `PUT /api/monitoring/checks/{check_id}` uebersetzt geaenderte `rules` eines
  Modul-Checks in diese Aenderungen und antwortet mit 422, wo das nicht geht.
