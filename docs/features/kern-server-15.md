# kern-server-15 — Healthchecks ohne Proxy, Log-Level, Hook-Glocke, Tag-Abgleich

Roadmap: R-1758, R-1763, R-1764, R-1773 (Zug `tasks/kern-server-15.md`).

## Problem je Zeile

- **R-1758:** Die Compose-Healthchecks von `monitoring` (`docker-compose.yml:611`) und `ca-issuer`
  (`docker-compose.yml:396`) rufen `urllib.request.urlopen` auf. urllib nimmt die Proxy-Variablen aus der Umgebung,
  die Docker aus der Client-Konfiguration in jeden Container gibt, und schickt auch eine Loopback-Anfrage durch den
  Proxy. Ohne erreichbaren Proxy wird der Dienst nie gesund. Der Server-Check nutzt seit kern-server-14 T7
  `build_opener(ProxyHandler({}))` (`docker-compose.yml:205`).
- **R-1773:** `ah_common/logging_config.py:33` prüft `LOG_LEVEL` mit `logging.getLevelName`. Ein von einer Bibliothek
  registrierter Name wie `TRACE` (uvicorn) geht so durch. Der CA-Issuer prüft gegen eine feste Liste
  (`apps/ca-issuer/app/main.py:42`), und `docs/admin/betrieb.html:133` verspricht für alle drei Dienste die fünf Namen.
- **R-1763:** Drei Nachlese-Punkte aus kern-server-14:
  - `notify_hook_failure` (`apps/server/app/modules/hooks/script_runner.py:377`) liest erst, ob es schon eine Notiz
    gibt, und schreibt dann. Zwei gleichzeitige Fehlschläge desselben Hooks kommen beide durch die Prüfung.
  - Die Kategorie `hooks` ist nicht im Glocken-Vokabular (`apps/server/app/modules/notifications/models.py:130`,
    `apps/desktop/ui/src/lib/models/notifications.ts:17`). Der Desktop zeigt sie deshalb roh und sortiert sie hinten
    ein.
  - `_cleanup_orphans` (`apps/monitoring/app/tag_sync.py:158`) ruft `cleanup_server` mit dem synchronen
    `send_all_clears` auf. Viele offene Alarme eines gelöschten Servers halten so den Tag-Abgleich auf. Die Route
    reicht die Entwarnungen seit R-1622 an eine Hintergrund-Task weiter.
- **R-1764:** Ein Hinweis der Sicherheitsprüfung zu den Hook-Fehlernotizen. Die Einzelheiten stehen in
  `tasks/private/`.

## Ziel und Nicht-Ziele

Ziel ist, die vier Zeilen so zu beheben, wie oben beschrieben. Nicht-Ziel ist eine neue Kategorie-Logik in der Web-UI:
die Web-UI hat kein Glocken-Vokabular.

## Betroffene Komponenten

| Komponente | Dateien |
|---|---|
| Compose | `docker-compose.yml` |
| pycommon, getestet über server | `apps/pycommon/ah_common/logging_config.py` |
| Server | `hooks/script_runner.py`, `hooks/scheduler.py`, `core/events.py` |
| Monitoring | `tag_sync.py` |
| Desktop-UI | `lib/models/notifications.ts`, `lib/i18n/dictionaries.ts` |

Es gibt keine Migration und keine Änderung an der API.

## Trade-offs

- **Entprellung (R-1763):** Ein Prozess-Lock je Hook um Prüfen und Schreiben. Das reicht, weil Hooks nur im
  Server-Prozess laufen. Bei mehreren Workern bleibt ein seltenes Doppel möglich; ein DB-Lock wäre dafür schwerer und
  ist nicht belegt nötig.
- **Tag-Abgleich:** Die Entwarnungen gehen in einen Daemon-Thread. Der Abgleich wartet nicht auf den Hub, und ein
  Fehler wird nur geloggt, wie beim Senden aus der Hintergrund-Task.

## Risiken und Rollback

Jede Task kann einzeln per `git revert` zurückgenommen werden. Wegen `docker-compose.yml` gilt `Heavy: linux-full`;
der Stack-Job der PR-CI startet die Healthchecks real.

## Doku-Impact

- `docs/admin/betrieb.html` DE+EN: Log-Level, nur wenn der Wortlaut sich ändert.
- `docs/developer/hooks.html` DE+EN: die Glocken-Notiz eines fehlgeschlagenen Hooks.
- Changelog-Fragment.

## Offene Fragen

Keine.
