<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server mit mehreren Prozessen: ein Schlüssel, ein Bootstrap-Token, gesperrte Hochstufung, Haltbarkeit, Log-Hygiene

Stand des Codes: `origin/main@53a7dbc5`. Ein Teil der betroffenen Stellen steht nur auf Branches, die vor dem Bau
nach `main` gemergt sein müssen: `feature/server-hardening@88e0ad98` (im Folgenden **SH**: `write_private_file`, die
neuen Schreibwege der Bootstrap-Dateien, `_redis_target`) und `origin/feature/audit-coverage@62c24174` (PR #268, im
Folgenden **AC**: `was_admin`, Event `user.promoted`). `datei:zeile` ohne Zusatz gilt für `main`, mit „SH“ oder „AC“
für den Branch. Ledger: `tasks/server-multiworker.md`. Roadmap: BUG R-0761, R-0762, R-0768; REF R-0767, R-0766, R-0776
(Kevin 2026-10-22, Triage: angenommen).

## Problem / Motivation

**Wie der Server mehrere Prozesse startet (Beleg am Code).** Der Entrypoint startet
`uvicorn app.main:app … --workers "${WEB_CONCURRENCY:-1}"` (`apps/server/docker-entrypoint.sh:54-58`; Compose reicht
`WEB_CONCURRENCY` durch, `docker-compose.yml:62`; Betriebsdoku `docs/admin/betrieb.html:158-160`). Mit mehr als einem
Worker lädt der uvicorn-Master die App nicht selbst, sondern startet `Multiprocess(config, sockets=[sock]).run()`
(uvicorn `main.py:630`), und jeder Worker ist ein eigener Prozess aus `multiprocessing.get_context("spawn")`
(uvicorn `_subprocess.py:18`, `:51`; gelesen in uvicorn 0.54.0, gepinnt ist 0.49.0,
`apps/server/requirements.txt:862`). Jeder Worker importiert also `app.core.config` selbst — dort läuft
`SECRET_KEY = _resolve_secret_key()` beim Import (`apps/server/app/core/config.py:39`; SH `:58`) — und fährt die
Lifespan selbst: `lifespan` (`apps/server/app/main.py:360-385`) → `_run_startup_tasks` (`:342-357`) → `_ensure_admin`
(`:66-120`). Daneben läuft der Scheduler als eigener Container (`docker-compose.yml:137-176`, `RUN_MODE=scheduler` →
`docker-entrypoint.sh:36-40` → `python -m app.scheduler_main`), der `app.core.config` ebenfalls importiert und
`./data` teilt (`docker-compose.yml:166-167`, Kommentar: „Shared DATA_DIR so the auto-generated SECRET_KEY matches the
web service“). Für die Admin-Zeile ist das Rennen der Worker schon behandelt (`main.py:110-116`, `IntegrityError`); für
Schlüssel- und Bootstrap-Dateien nicht.

1. **R-0761 — ohne `SECRET_KEY` kann jeder Prozess einen eigenen Schlüssel erzeugen.** `_resolve_secret_key`
   (`config.py:16-36`; SH `:36-55`) prüft, ob `.secret_key` existiert (`:23`; SH `:43`), erzeugt sonst einen Schlüssel
   und schreibt ihn (`:33-34`; SH `write_private_file`, `:53`). Prüfen und Schreiben sind nicht atomar: Zwei Prozesse,
   die beide keine Datei finden, erzeugen zwei Schlüssel; jeder behält seinen im Speicher, die Datei hält den des
   letzten Schreibers. JWTs des einen Prozesses lehnt der andere ab (`apps/server/app/core/auth.py:72`, `:85`), und nach
   dem nächsten Neustart verlieren die Tokens des Verlierers ihre Gültigkeit. Wo es trifft:
   - Nur wenn `SECRET_KEY` leer oder der Default ist (`docker-compose.yml:68`, `:143`: `change-me-in-production`).
     `scripts/init-secrets.sh:77-82` setzt einen Wert, `scripts/install.sh:208` ruft es auf; betroffen sind also
     Installationen ohne den Installer.
   - Im Compose-Weg läuft vor uvicorn `alembic upgrade head` (`docker-entrypoint.sh:44`), und `alembic/env.py:30`
     importiert `app.core.config`: Im Server-Container erzeugt dieser Alembic-Prozess den Schlüssel, bevor ein Worker
     startet, und die Worker lesen danach dieselbe Datei. Das Rennen läuft dort zwischen dem Alembic-Prozess und dem
     Scheduler-Container, die beide nur auf Postgres und Redis warten (`docker-compose.yml:127-131`, `:172-176`);
     verliert der Scheduler, hält er einen anderen Schlüssel als Datei und Worker.
   - Startet `uvicorn --workers N` ohne vorgeschalteten Prozess, rennen alle Worker gegeneinander.
   - Auf `main` kommt das Fenster von `write_text` dazu (erst kürzen, dann schreiben): Ein Leser kann eine leere Datei
     sehen und einen eigenen Schlüssel erzeugen. SH schließt dieses Fenster (`os.replace`), nicht das Rennen.
   Der Befund trifft zu; im Compose-Weg ist die Wirkung kleiner als die Zeile sagt (die Worker sind sich einig, der
   Scheduler kann abweichen).

2. **R-0762 — bei `WEB_CONCURRENCY>1` erzeugt jeder Worker sein eigenes Bootstrap-Token.** Mit leerem
   `ADMIN_PASSWORD` (Compose-Default, `docker-compose.yml:69`) und leerer Datenbank ruft jeder Worker
   `_emit_bootstrap_token` (`main.py:83`, `:94`). Jeder erzeugt ein Token und schreibt erst den Hash, dann die
   Setup-Datei (`main.py:132-148`; SH `:132-140`). Laufen zwei Worker verschränkt (A-Hash, B-Hash, B-Setup, A-Setup),
   passt das Token in der Setup-Datei nicht zum Hash, und `POST /api/auth/bootstrap` lehnt das Token aus der Datei ab
   (`apps/server/app/modules/users/auth_router.py:314-321`), bis ein Neustart neu würfelt. Dazu steht der Banner N-mal
   im Log. Die Zeile nennt das „nicht verifiziert“; die Code-Lesung belegt, dass nichts die Worker abstimmt, und der Test
   in T3 zeigt deterministisch, dass ein zweiter Worker die Dateien des ersten überschreibt.

3. **R-0768 — eine Hochstufung liest den Benutzer ohne Sperre.** `update_user` liest die Zielzeile ohne
   `with_for_update` (`apps/server/app/modules/users/router.py:105`; AC `:105`), entscheidet an `user.is_admin`
   (`:117`), ob die Standard-Benachrichtigungsregel angelegt wird (`:118-125`), und AC merkt sich `was_admin`
   (AC `:108`) und feuert nach dem Commit `user.promoted` (AC `:146-147`). Zwei gleichzeitige Hochstufungen desselben
   Benutzers lesen beide `is_admin = false`: zwei Standardregeln (keine Eindeutigkeit auf
   `notification_subscription`, `apps/server/app/modules/notifications/models.py:39-80`) und mit AC zwei Events. Die
   Herabstufung sperrt bereits (`router.py:128-132`).

4. **R-0767 — nach `os.replace` wird das Verzeichnis nicht gesynct.** `write_private_file` (SH `config.py:17-33`,
   `os.replace` `:30`) und `write_frps_config` (`apps/server/app/modules/frp/docker_manager.py:26-54`, `os.replace`
   `:47`) syncen die Datei vor dem Tausch, nicht aber das Verzeichnis danach. Der Verzeichniseintrag ist damit nach
   einem Stromausfall nicht sicher; ohne ihn findet der nächste Start keine `.secret_key` und erzeugt einen neuen
   Schlüssel (fsync(2): „Calling fsync() does not necessarily ensure that the entry in the directory containing the
   file has also reached disk. For that an explicit fsync() on a file descriptor for the directory is also needed.“).

5. **R-0766 — `remove_frps_config` loggt einen Fehler mit Traceback.** `except OSError: logger.exception(…)`
   (`docker_manager.py:98-99`), während dasselbe Modul Fehler sonst nur mit dem Typ loggt (`:66`, `:82`) und SH den
   Startabgleich ebenso umstellt.

6. **R-0776 — Log-Hygiene.**
   - Die Laufzeitwarnungen von `RedisBackend` loggen den Fehlertext, deutsch (SH `apps/server/app/core/rate_limit.py:95`,
     `:106`, `:113`).
   - `_redis_target` (SH `:125-142`) baut `scheme://host:port` aus `parts.hostname` (SH `:141`), das IPv6 ohne Klammern
     liefert: `redis://[2001:db8::1]:6379` wird zu `redis://2001:db8::1:6379` (Probe mit `urllib.parse.urlsplit`,
     Python 3.13: `hostname='2001:db8::1'`, `port=6379`).
   - `lifespan` loggt ein gescheitertes `stream_hub.start` mit `logger.exception` (`main.py:374-381`; SH `:366-373`).
   - Die Bootstrap-Route loggt einen Löschfehler deutsch und ohne Typ (`auth_router.py:347-351`).

## Ziel & Nicht-Ziele

**Ziel:**
1. Je `DATA_DIR` gibt es genau einen automatisch erzeugten Schlüssel: Der erste Prozess, der ihn veröffentlicht,
   gewinnt; jeder andere übernimmt dessen Schlüssel. Kein neuer Pflichtwert für Betreiber (T2).
2. Je Start erzeugt genau ein Worker das Bootstrap-Token; Hash und Setup-Datei stammen immer aus demselben Aufruf, der
   Banner steht einmal im Log. Ein Neustart erzeugt weiter ein neues Token (T3).
3. Zwei gleichzeitige Hochstufungen desselben Benutzers legen eine Standardregel an und feuern ein `user.promoted` (T8).
4. Nach jedem atomaren Tausch von `.secret_key`, Bootstrap-Dateien und `frps.toml` ist auch das Verzeichnis gesynct
   (T1, T4).
5. Die genannten Log-Zeilen nennen vom Fehler nur den Typ, ohne Traceback und ohne Text; neue Log-Strings sind
   englisch; IPv6-Hosts stehen in Klammern (T5, T6, T7).

**Nicht-Ziele:**
- `SECRET_KEY` zur Pflicht machen oder den Start ohne ihn abbrechen (sichtbares Verhalten, Kevins Entscheidung; die
  gewählte Lösung braucht es nicht).
- Die Worker in einem Stack-Lauf mit `WEB_CONCURRENCY>1` prüfen: Der Stack-Lauf startet einen Worker
  (`scripts/tests/integration_stack_test.sh` setzt `WEB_CONCURRENCY` nicht). Ein solcher Lauf änderte einen
  Harness-Pfad und ist nicht Teil dieses Vorhabens (Offene Fragen).
- Die Sperrdatei des Bootstrap aufräumen (sie bleibt leer liegen; Begründung unter Trade-offs).
- Weitere `logger.exception`-Stellen oder deutsche Log-Texte außerhalb der genannten Zeilen.
- Kein Befund der Zeilen ist falsch; jede Zeile wird zu mindestens einer Task.

## Betroffene Komponenten & Dateien

Eine Komponente: `server`.

| Task | Zeile | Dateien |
|---|---|---|
| T1 | R-0767 | `apps/server/app/core/config.py`, `apps/server/tests/test_secret_key_file.py` |
| T2 | R-0761 | `apps/server/app/core/config.py`, `apps/server/tests/test_secret_key_file.py`, `CHANGELOG.md` |
| T3 | R-0762 | `apps/server/app/main.py`, `apps/server/tests/conftest.py`, `apps/server/tests/test_bootstrap_workers.py` (neu), `CHANGELOG.md`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html` |
| T4 | R-0767 | `apps/server/app/modules/frp/docker_manager.py`, `apps/server/tests/test_frp_docker_manager.py` |
| T5 | R-0766 | `apps/server/app/modules/frp/docker_manager.py`, `apps/server/tests/test_frp_docker_manager.py`, `CHANGELOG.md` |
| T6 | R-0776 | `apps/server/app/core/rate_limit.py`, `apps/server/tests/test_rate_limit.py`, `CHANGELOG.md` |
| T7 | R-0776 | `apps/server/app/main.py`, `apps/server/app/modules/users/auth_router.py`, `apps/server/tests/test_log_hygiene.py` (neu), `CHANGELOG.md` |
| T8 | R-0768 | `apps/server/app/modules/users/router.py`, `apps/server/tests/test_users_promotion_event.py`, `CHANGELOG.md` |

**Abhängigkeiten:** T1, T2, T3 und T6 bauen auf SH (`write_private_file`, neue Bootstrap-Schreibwege,
`_redis_target`, `tests/test_secret_key_file.py`); T8 baut auf AC (`was_admin`, `user.promoted`,
`tests/test_users_promotion_event.py`). Der Bau beginnt erst, wenn `feature/server-hardening` auf `main` ist; T8
zusätzlich erst nach dem Merge von PR #268. Vor dem Bau `origin/main` in den Branch mergen und jede `datei:zeile` neu
greppen.

**Geteilte Dateien mit anderen Vorhaben** (für die Reihenfolge der Merges): `config.py` (SH, auth-sessions,
smtp-hardening), `main.py` (SH, fehlervertrag, server-fixes), `rate_limit.py`, `test_secret_key_file.py`,
`test_frp_docker_manager.py`, `test_rate_limit.py` (SH), `auth_router.py` (auth-sessions), `users/router.py` und
`test_users_promotion_event.py` (AC), `tests/conftest.py` (server-fixes), `docs/admin/betrieb.html` und
`docs/en/admin/operations.html` (AC und weitere Doku-Vorhaben, andere Abschnitte), `CHANGELOG.md` (alle).

## Datenmodell / API / Migrationen

Keine Migration, kein neues Feld, keine Änderung an Routen, Schemas oder Docstrings von Routen (der OpenAPI-Snapshot
bleibt). `PUT /api/users/{id}` antwortet wie bisher; nur die Reihenfolge nebenläufiger Hochstufungen ändert sich (die
zweite wartet auf die erste). Neue Datei im Datenverzeichnis: `data/.bootstrap.lock` (leer, 0600). Kein
Vertrags-Drift zu Web, Desktop oder Agent.

## Externe Integrationen

- **uvicorn** `--workers`: <https://www.uvicorn.org/deployment/> — Worker sind eigene Prozesse; Verhalten am Quelltext
  belegt (oben, uvicorn 0.54.0; die gepinnte 0.49.0 nicht einzeln geprüft).
- **link(2)**: <https://man7.org/linux/man-pages/man2/link.2.html> — `EEXIST`, wenn der neue Name existiert, auch als
  hängender Symlink. Probe (Python 3.13, tmpfs): `os.link` auf eine vorhandene Datei und auf einen hängenden Symlink
  wirft `FileExistsError`.
- **flock(2)**: <https://man7.org/linux/man-pages/man2/flock.2.html> — die Sperre gehört zur offenen
  Dateibeschreibung; ein zweites `open()` im selben Prozess konkurriert wie ein fremder Prozess, das Schließen des
  letzten Deskriptors (auch durch Prozessende) gibt sie frei. Probe (Python 3.13, tmpfs): zweites
  `flock(LOCK_EX|LOCK_NB)` im selben Prozess → `BlockingIOError`, nach `close` des ersten erfolgreich; `os.open` liefert
  einen nicht vererbbaren Deskriptor (PEP 446, `os.get_inheritable` → `False`).
- **fsync(2)**: <https://man7.org/linux/man-pages/man2/fsync.2.html> — Zitat oben. Probe: `fsync` auf einen
  `O_RDONLY|O_DIRECTORY`-Deskriptor gelingt (tmpfs).
- **SQLAlchemy 2.0.50** (`requirements.txt:773`), `with_for_update` und `populate_existing`:
  <https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html> (Populate Existing: „ensures that, for all rows loaded,
  the corresponding instances in the Session will be fully refreshed … (including pending changes)“); Vorbild im Code
  `main.py:295-300`.
- **Nicht verifiziert:** Hardlinks und `flock` auf Bind-Mounts von Docker Desktop (macOS/Windows) und auf
  Netzwerk-Dateisystemen; beide Wege fallen bei einem `OSError` auf das heutige Verhalten zurück (Risiken).

## Trade-offs & Alternativen

1. **Schlüssel (R-0761): Veröffentlichen per `os.link` — Empfehlung.** Temp-Datei im selben Verzeichnis (0600 ab der
   Erzeugung, schreiben, `fsync`), dann `os.link(tmp, ".secret_key")`: Der Name entsteht atomar und nur einmal, und er
   zeigt von Anfang an auf eine vollständige Datei. Wer `FileExistsError` bekommt, liest den Schlüssel des Gewinners.
   Kein Sperren, keine neue Datei, keine Wartezeit. Rückfall: Liegt am Namen eine leere Datei oder ein hängender Symlink,
   oder kennt das Dateisystem keine Hardlinks, schreibt der Prozess wie heute mit `write_private_file`.
   - *`O_CREAT|O_EXCL` direkt auf `.secret_key`* (Vorschlag der Zeile): ebenso exklusiv, aber zwischen Anlegen und
     Schreiben sieht ein Leser eine leere oder halbe Datei und müsste warten oder raten. `link` hat dieses Fenster nicht.
   - *Blockierende Sperre um Prüfen und Schreiben:* deckt auch die leere Altdatei ab, braucht aber eine Sperrdatei, und
     ein deterministischer Test müsste beobachten, dass ein Thread im `flock` wartet. Verworfen.
   - *`SECRET_KEY` zur Pflicht machen:* neue Pflicht für Betreiber; Kevins Entscheidung und nicht nötig. Verworfen.
2. **Bootstrap (R-0762): Leiter per `flock`, gehalten bis zum Prozessende — Empfehlung.** `_emit_bootstrap_token`
   öffnet `data/.bootstrap.lock` und versucht `flock(LOCK_EX|LOCK_NB)`. Wer die Sperre bekommt, behält den Deskriptor
   bis zum Prozessende und schreibt Hash und Setup-Datei; wer sie nicht bekommt, schreibt nichts und loggt eine
   INFO-Zeile. Eine Sperre, die schon dieser Prozess hält, schreibt wie heute neu. Je Start genau ein Token, ein Banner,
   und ein Neustart würfelt weiter neu, weil die Sperre mit dem Prozess endet. Stirbt der Leiter und uvicorn startet den
   Worker neu, übernimmt der neue Worker die Sperre und schreibt ein neues, wieder stimmiges Paar.
   - *Blockierende Sperre nur um das Schreiben:* Paare stimmig, aber N Tokens nacheinander und N Banner; der Betreiber
     liest womöglich ein Token, das gleich danach ersetzt wird. Verworfen.
   - *`link` wie beim Schlüssel:* kann ein Token dieses Starts nicht von einem des letzten Starts unterscheiden. Verworfen.
   - *Postgres-Advisory-Lock:* hielte eine DB-Verbindung je Worker für die Laufzeit. Verworfen.
   - *Token im Entrypoint vorab erzeugen:* nur im Docker-Weg wirksam. Verworfen.
   Die Sperrdatei wird nie gelöscht: Würde sie gelöscht, während ein Leiter sie hält, könnte ein späterer Prozess eine
   neue Datei anlegen und sperren, und es gäbe zwei Leiter. Sie ist leer und kostet nichts. Ihr Pfad ist eine
   Modul-Konstante neben den Bootstrap-Dateien; sie wird nicht beim Aufruf aus `BOOTSTRAP_TOKEN_FILE` abgeleitet, damit
   Tests, die die Bootstrap-Dateien nach `tmp_path` umlenken und dort den Inhalt prüfen (SH
   `tests/test_bootstrap.py:141-150`, `:173-192`), keine fremde Datei finden.
3. **Hochstufung (R-0768): Zielzeile nur bei `is_admin: true` sperren — Empfehlung.** Bei jedem Körper zu sperren
   kehrte die Sperr-Reihenfolge gegenüber der Herabstufung um (erst das Ziel, dann alle Admins, `router.py:132`): A
   stuft B herab, B stuft A herab → Deadlock, Postgres bricht eine Transaktion ab, die Route antwortet 500. Bei einer
   Hochstufung sperrt der Pfad sonst nichts, also gibt es keinen Zyklus. `populate_existing()` sorgt dafür, dass die
   Entscheidung den gesperrt gelesenen Stand nutzt, auch wenn die Session den Benutzer schon kennt (wie `main.py:295-300`);
   es ist der erste Zugriff der Route, also verwirft es keine offenen Änderungen. Ein nachträgliches
   `db.refresh(user, with_for_update=True)` würde eine schon gesetzte Passwortänderung verwerfen. Verworfen.
4. **Verzeichnis-`fsync` (R-0767): ein Helfer `fsync_dir` in `config.py`.** `config.py` kann nichts aus den Modulen
   importieren, `docker_manager.py` importiert schon aus `config.py` (`docker_manager.py:14`). Ein Fehler beim
   Verzeichnis-`fsync` wird mit Typ als WARNING geloggt und nicht geworfen: Die Datei steht zu diesem Zeitpunkt schon an
   ihrem Platz, ein Wurf ließe den Aufrufer einen gelungenen Tausch als gescheitert behandeln.
5. **Log-Stufe beim Entfernen der `frps.toml` (R-0766):** ERROR bleibt (`logger.error` statt `logger.exception`); nur
   Traceback und Fehlertext fallen weg. So bleibt der bestehende Test `test_remove_logs_an_oserror_instead_of_raising`
   (`tests/test_frp_docker_manager.py:150-156`, fängt auf ERROR) unverändert gültig. `stream_hub.start` (R-0776) wird
   WARNING: Der Server läuft weiter, der Push fällt auf Polling zurück, wie beim Startabgleich in SH.

## Risiken & Rollback

- **Rest bei R-0761, wie heute:** Liegt eine leere `.secret_key` (nur aus einem Absturz während des alten
  `write_text`) oder ein hängender Symlink am Namen, und starten gleichzeitig mehrere Prozesse, ersetzen sie die Datei
  wie heute nacheinander. Dasselbe gilt auf einem Dateisystem ohne Hardlinks (Rückfall mit WARNING). Der neue Code
  erzeugt nie eine leere Datei; der Fall tritt höchstens einmal nach dem Update auf. Auch der Vorschlag der Zeile
  (`O_EXCL`) hätte ihn.
- **Rest bei R-0762:** Kennt das Dateisystem kein `flock` (`OSError` außer `BlockingIOError`), schreibt jeder Worker
  wie heute und loggt eine WARNING mit Typ. Ein Dateisystem, das `flock` scheinbar gewährt, aber nicht zwischen
  Prozessen durchsetzt, fiele unbemerkt auf das heutige Verhalten zurück (nicht verifiziert für Docker-Desktop-Mounts).
- **R-0768:** Eine zweite Hochstufung wartet, bis die erste committet; die Route hält die Sperre nur für ihre eigene
  Transaktion.
- **R-0767:** Ein zusätzlicher `fsync` je Schreibvorgang; geschrieben wird selten (Start, Änderung der FRP-Config).
- **Rollback:** jede Task ist ein eigener Commit und einzeln revertierbar. `data/.bootstrap.lock` darf nach einem
  Rollback liegen bleiben oder bei gestopptem Server gelöscht werden.

## Doku-Impact

- `CHANGELOG.md`: Fixed für R-0761 (T2), R-0762 (T3), R-0768 (T8); ein Changed-Eintrag für die Log-Zeilen
  (T5, T6, T7 ergänzen ihn nacheinander). T1 und T4 (Haltbarkeit) intern.
- `docs/admin/betrieb.html` und `docs/en/admin/operations.html`: neue Zeile `data/.bootstrap.lock` in der Tabelle der
  Datendateien (`betrieb.html:75-76`, `operations.html:42-43`) — leer, sorgt dafür, dass nur ein Worker das Setup-Token
  erzeugt, darf bei gestopptem Server gelöscht werden.

## Offene Fragen

1. **Ein Stack-Lauf mit mehreren Workern?** Kein schwerer Lauf startet den Server mit `WEB_CONCURRENCY>1`; T2 und T3
   sind nur durch Unit-Tests mit simulierten Prozessen belegt. Ein Lauf mit zwei Workern und leerem `ADMIN_PASSWORD`
   (ein Banner, Token aus der Setup-Datei passt) änderte einen Harness-Pfad. Empfehlung: als eigene, zurückgestellte
   Roadmap-Zeile führen, nicht in diesem Vorhaben. Keine Task hängt daran.
