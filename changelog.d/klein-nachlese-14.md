### Fixed

- **Monitoring: SMART-Zaehler:** `smart_disks_warning` und `smart_disks_critical` zaehlen Platten, nicht mehr deren
  Meldungen; eine Platte mit zwei Warnungen zaehlt einmal. Die Platten stehen im Bericht nach Geraet sortiert.
- **Webhook: zu tief verschachtelter Body:** Ein Body, den der JSON-Parser wegen der Verschachtelung abbricht, ist ein 422
  wie ein Body ab 33 Ebenen; das Skript lief bisher mit leerer Nutzlast.
- **Desktop: Monitoring:** Die Backup-Liste zeigt fehlende Gaeste zuerst, dann veraltete. Der Check zfs_health bietet die
  Scrub-Grenzen (Warnung und kritisch, in Tagen) im Formular an.
