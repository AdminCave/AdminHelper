### Changed

- **Monitoring SMART: "nicht erhoben" und "nicht lesbar" statt ok bzw. SMART FAILED:** ohne smartctl oder ohne
  Platten steht `smart_health` auf info, ein gescheiterter Scan auf unknown. Liefert smartctl fuer eine Platte kein
  Gesamturteil (etwa SMART abgeschaltet), schickt der Agent kein `smart_passed` mehr, und die Platte gilt als nicht
  lesbar ("SMART not readable") statt als defekt; der Desktop zeigt sie als N/A.
- **Monitoring ZFS: Scrub-Alter einstellbar:** `scrub_warn_days` und `scrub_crit_days` (Vorgabe 35/60 Tage) im Check
  `zfs_health`.
- **Server: Anfragen werden wie im Monitoring-Dienst begrenzt.**

### Fixed

- **Monitoring Disk-Forecast: eine volle Platte ist critical:** sie meldete bisher "stabil". Die Prognose folgt jetzt
  den Plattenregeln des Ressourcen-Checks desselben Servers (`ignore_mounts`, `disk_overrides`, `disk_min_free_gb`).
- **Monitoring ZFS: SUSPENDED und REMOVED sind critical, Scrub-Fehler warning;** der Desktop zeigt DEGRADED rot wie
  die Bewertung.
- **Monitoring-Status-Zusammenfassung zaehlt nur eingeschaltete Checks:** ein abgeschalteter kritischer Check blieb
  sonst dauerhaft auf dem Dashboard.
- **Modul-Checks: eigene Regeln und Schalter bleiben:** ein Katalog-Update ueberschreibt geaenderte Regeln nicht mehr,
  und eine zurueckgekehrte Instanz schaltet nur die Checks wieder ein, die ihr Verschwinden abgeschaltet hat.
