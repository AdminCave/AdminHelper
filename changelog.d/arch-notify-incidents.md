### Added

- **Glocke: Vorfaelle statt Einzelmeldungen:** der Notification-Hub faltet die Meldungen eines Checks auf einem
  Server in einen Vorfall mit Zaehler und Verlauf; ein Eintrag je Person, der bei jeder neuen Benachrichtigung wieder
  ungelesen nach oben rueckt. Benachrichtigt wird bei einem neuen Vorfall, bei der Eskalation von warning auf critical
  und fruehestens 30 Minuten nach der letzten Benachrichtigung; die Entwarnung behebt den Vorfall von selbst, ein
  Rueckfall binnen 30 Minuten oeffnet ihn still wieder. Die neuen Agents einer Sammelmeldung werden ein gemeinsamer
  Vorfall.
- **Vorfaelle im Team bearbeiten:** Bestaetigen, Als behoben markieren, Wieder oeffnen und Notizen, mit Benutzername im
  Verlauf; nur wer jeden Server des Vorfalls sieht. Neue Routen unter `/api/notifications` (`/unread`, `/hide`,
  `/incidents/{id}`, `/incidents/ack`, `resolve`, `reopen`, `notes`, `mute`, `/server-mutes`).
- **Stummschalten:** einen Vorfall fuer 1 Stunde oder bis morgen 07:00 (per API bis 7 Tage), einen Server fuer
  24 Stunden; stumme Eintraege bleiben gelesen, zaehlen nicht in der Glocke und senden keine E-Mail.
- **Desktop: Benachrichtigungs-Center mit Vorfaellen:** sechs Postfaecher (Posteingang, Offen, Bestaetigt, Behoben,
  Stumm, Alle), Kategorien mit Anzahl, Detail mit Aktionen je Zustand, Servern, Regeln, Kanaelen, Verlauf und Notizen,
  "Regel bearbeiten" fuer Monitoring-Vorfaelle; die Glocke bestaetigt offene Eintraege direkt, eine Auswahl wird
  bestaetigt, ausgeblendet oder gelesen markiert.

### Changed

- **Glocke ohne eigenen Monitoring-Cooldown:** der Monitoring-Dienst schickt jede Problem-Meldung mit dem Schluessel
  des Checks und den Ergebnissen seiner Alert-Regeln; wen sie erreicht, entscheidet der Hub am Vorfall. Der
  Event-Hook `alert.triggered` feuert nur noch, wenn die Glocke fuer critical benachrichtigt.
- **Kategorien der Server-Meldungen:** `lifecycle` heisst jetzt `tunnel` (FRP), `security` (Zertifikate) oder `agent`
  (entfernter Server); bestehende Regeln mit `lifecycle` bekommen alle drei.
- **Feed nach letzter Benachrichtigung sortiert:** `GET /api/notifications` ordnet nach `notified_at` und laesst
  ausgeblendete Eintraege weg; der Ungelesen-Zaehler zaehlt stumme und ausgeblendete nicht mit.
