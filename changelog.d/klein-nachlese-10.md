### Fixed

- **Agent: unbekannte Zeile von `doveadm log errors`:** `dovecot_status` meldet sie als Fehler des Laufs, statt sie
  still zu ueberspringen.
- **Agent: Image verschwindet waehrend `lmn_linbo`:** ein Image, das zwischen dem Lesen des Verzeichnisses und der
  Pruefung seines Torrents verschwindet, bricht den Lauf nicht mehr ab; es zaehlt nicht mit.
