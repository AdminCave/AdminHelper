### Added

- **Monitoring: App-Module fuer selbst betriebene Anwendungen:** die Erkennung findet Nextcloud, Paperless-ngx, Immich,
  OnlyOffice, Collabora, GitLab, Gitea/Forgejo, Zammad, Mattermost, Rocket.Chat, Synapse, Jitsi (Videobridge und
  Jicofo), BigBlueButton, 3CX, Keycloak, OpenLDAP, Vaultwarden, Bitwarden, WordPress, Moodle, Odoo, BookStack,
  Wiki.js, Frigate, Home Assistant und Uptime Kuma am Container-Image (eine Instanz je Compose-Projekt) oder an der
  systemd-Unit. Je Modul prueft der Agent Container oder Unit und fragt einen lesenden HTTP-Endpunkt auf dem eigenen
  Host — nichts, was etwas ausloest oder aendert (kein `wp-cron.php`, kein Moodle-Cron, kein Uptime-Kuma-Push), und
  Anwendungen, die fehlgeschlagene Logins sperren, nur ohne Login. Ein Aufruf, der bei der Anwendung etwas anlegt,
  laeuft hoechstens alle 15 min. Checks, deren Ziel auf dem Host fehlt, legt das Uebernehmen nicht an und nennt sie
  unter "Nicht alles uebernommen". Der Status-Check von Nextcloud sendet `Host: localhost` und braucht einen Agent
  in der Version des Monitoring-Dienstes; ein aelterer meldet ihn `unknown`. Doku: Monitoring, Abschnitt App-Module
  (DE+EN).
