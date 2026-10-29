<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server mit mehreren Prozessen: ein Schlüssel, ein Bootstrap-Token, gesperrte Hochstufung, Haltbarkeit, Log-Hygiene — Task-Ledger
Status: erledigt · Branch: feature/server-multiworker · Review: pro Task
Spec: docs/features/server-multiworker.md (Roadmap R-0761, R-0762, R-0768, R-0767, R-0766, R-0776)
Heavy: linux-full — der Server-Start erzeugt `.secret_key` und die Bootstrap-Dateien neu abgestimmt (T2, T3), `PUT /api/users/{id}` sperrt bei einer Hochstufung die Zielzeile (T8), Server-API und Startpfad also; der Stack-Lauf fährt einen frischen Server-Start neben dem Scheduler-Container und die Web-E2E. T4/T5 ändern an `frps.toml` nur Haltbarkeit und eine Log-Zeile, nicht Inhalt oder Tunnel-Datenpfad; keine PKI, kein Install-/Compose-Pfad: kein `scenario`, kein `windows`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Je `DATA_DIR` genau ein automatisch erzeugter Schlüssel, auch wenn Worker und Scheduler gleichzeitig
starten. (2) Je Start erzeugt genau ein Worker das Bootstrap-Token; Hash und Setup-Datei passen immer zusammen.
(3) Zwei gleichzeitige Hochstufungen legen eine Standardregel an und feuern ein `user.promoted`. (4) Nach jedem
atomaren Tausch ist auch das Verzeichnis gesynct. (5) Die genannten Log-Zeilen nennen vom Fehler nur den Typ.

Für alle Tasks:
- **Start erst nach dem Merge von `feature/server-hardening` nach `main`** (T1, T2, T3, T6 bauen auf
  `write_private_file`, den neuen Bootstrap-Schreibwegen, `_redis_target` und `tests/test_secret_key_file.py`); T8
  zusätzlich erst nach dem Merge von PR #268 (`origin/feature/audit-coverage`: `was_admin`, `user.promoted`,
  `tests/test_users_promotion_event.py`). Vor der ersten Task `origin/main` in den Branch mergen. Zeilenangaben ohne
  Zusatz: `origin/main@53a7dbc5`; mit „SH“: `feature/server-hardening@88e0ad98`; mit „AC“:
  `origin/feature/audit-coverage@62c24174`. Der builder greppt jede Stelle vor dem Schreiben neu.
- Reihenfolge: T1 vor T2 und T4 (beide nutzen `fsync_dir`); T4 vor T5 (dieselben Dateien); T3 vor T7 (beide
  `main.py`). T6 und T8 unabhängig.
- `security` zusätzlich: T5, T4 (`apps/server/app/modules/frp/*`), T6 (`apps/server/app/core/rate_limit.py`), T7 und
  T8 (`apps/server/app/modules/users/*`) stehen auf `scripts/dev/review-risk.txt`; T1, T2 und T3 bekommen `security`
  ebenfalls (Schlüssel- und Bootstrap-Dateien).
- Nebenläufigkeits-Tests sind deterministisch: Synchronisation über `threading.Barrier`/`Event` oder über eine Sperre,
  die der Test selbst hält, nie über `sleep`; ein Timeout dient nur als Schutz gegen Hängen und lässt den Test scheitern.
- Neue Log-Strings englisch; bestehende deutsche Texte, die eine Task nicht ändern muss, bleiben. Vom Fehler nur
  `type(exc).__name__`, kein `exc_info`, kein Text.
- Docstrings von Routen bleiben unverändert (sie sind die OpenAPI-Beschreibung, `tests/openapi.snapshot.json`).
- Platzhalter: Hosts unter `.example`, IPv4 aus RFC 5737, IPv6 aus `2001:db8::/32` (RFC 3849). Erfundene
  Zugangsdaten sind offensichtliche Platzhalter (`s3cr3t-pw`).
- Ein Test, der die umask ändert, setzt sie im `finally` zurück; ein Test, der `DATA_DIR` oder Dateipfade umlenkt,
  nutzt `monkeypatch.setattr` und `tmp_path`, nie das echte Datenverzeichnis. `SECRET_KEY` leeren mit
  `monkeypatch.setenv("SECRET_KEY", "")` (conftest setzt einen Default; `delenv` hätte kein Undo).
- Proben gegen eine Datenbank drucken nur Exception-Typen.

### T1 — `write_private_file` synct nach dem Tausch das Verzeichnis  [x]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/tests/test_secret_key_file.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @18fa95d3 2026-10-29T09:27:35+01:00
Review: approve (.ah-out/review/server-multiworker/T1.verdict.json)
Änderung: Neu in `apps/server/app/core/config.py` neben `write_private_file` (SH `:17-33`): `fsync_dir(path: Path) -> None` — `os.open(path, os.O_RDONLY | os.O_DIRECTORY)`, `os.fsync`, `os.close` im `finally`; ein `OSError` (beim Öffnen oder beim `fsync`) wird als `logger.warning("directory %s not synced (%s)", path, type(exc).__name__)` geloggt und nicht geworfen. Kommentar fürs Warum: der Verzeichniseintrag eines `os.replace` ist erst nach einem `fsync` des Verzeichnisses haltbar (fsync(2)); die Datei steht schon an ihrem Platz, ein Wurf ließe den Aufrufer einen gelungenen Tausch als gescheitert behandeln. `write_private_file` ruft nach `os.replace(tmp, path)` (SH `:30`) `fsync_dir(path.parent)`, außerhalb des `except`, das die Temp-Datei entfernt. Neue Tests in `test_secret_key_file.py`: (a) `os.fsync` und `os.replace` per `monkeypatch` als Spione, die je Aufruf `("fsync", stat.S_ISDIR(os.fstat(fd).st_mode), os.fstat(fd).st_ino)` bzw. `("replace",)` festhalten und das Original rufen → nach `write_private_file(tmp_path / "f", "x")` ist die Folge `fsync` (Datei), `replace`, `fsync` (Verzeichnis, `st_ino == tmp_path.stat().st_ino`). (b) Der `fsync`-Spion wirft für Verzeichnis-Deskriptoren `OSError(errno.EINVAL, "Invalid argument")` → `write_private_file` wirft nicht, die Datei hält den Inhalt, genau eine WARNING von `adminhelper.config` nennt `OSError`, `Invalid argument` steht nicht in `caplog.text`, kein Record mit `exc_info`. Zuerst rot: (a) und (b) auf dem Stand vor dem Fix (kein Verzeichnis-`fsync`, keine WARNING).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_secret_key_file.py tests/test_bootstrap.py
Doku: keine (intern)
Beweis: Code-Lesung feature/server-hardening@88e0ad98 apps/server/app/core/config.py:24-33 (`fsync` der Datei, `os.replace`, kein `fsync` des Verzeichnisses); der Test (a) dieser Task ist vor dem Fix rot (`1 failed`)
Orakel: contract — nach dem Tausch folgt ein `fsync` des Elternverzeichnisses
Dedup-Key: ref:server:config.py:no-dir-fsync
HEAD: 53a7dbc5

### T2 — `.secret_key` wird einmal veröffentlicht; wer verliert, übernimmt den Schlüssel  [x]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/tests/test_secret_key_file.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3b41f1be 2026-10-29T09:30:55+01:00
Review: approve (.ah-out/review/server-multiworker/T2.verdict.json)
Änderung: Neu in `config.py`: `publish_private_file_once(path: Path, text: str) -> str` — Temp-Datei per `tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")` (0600 ab der Erzeugung), schreiben (UTF-8), `flush`, `os.fsync`, dann `os.link(tmp, path)`; gelingt der Link: `fsync_dir(path.parent)` (T1), Rückgabe `text`. `FileExistsError`: den Inhalt von `path` lesen (`read_text().strip()`); ist er nicht leer, ihn zurückgeben (ein anderer Prozess hat gewonnen; der Inhalt ist vollständig, weil der Gewinner erst nach dem `fsync` verlinkt). Ist er leer oder `path` ein hängender Symlink (`FileNotFoundError` beim Lesen): `write_private_file(path, text)` wie heute, Rückgabe `text`. Ein anderer `OSError` beim `os.link` (Dateisystem ohne Hardlinks): `logger.warning("%s not published exclusively (%s); writing it in place", path, type(exc).__name__)`, dann `write_private_file(path, text)`, Rückgabe `text`. Die Temp-Datei wird in jedem Fall im `finally` entfernt (`unlink(missing_ok=True)`). Kommentar fürs Warum: `link` legt den Namen atomar und nur einmal an und zeigt von Anfang an auf eine vollständige Datei, anders als `O_EXCL` (Spec, Trade-off 1); Worker und Scheduler starten gleichzeitig. `_resolve_secret_key` (SH `:36-55`) schreibt den erzeugten Schlüssel mit `publish_private_file_once` statt `write_private_file` (SH `:53`) und gibt dessen Rückgabe zurück; stammt sie nicht vom eigenen Aufruf, `logger.info("SECRET_KEY of another process adopted from %s", key_file)` statt der bestehenden Zeile „auto-generiert“. Env-Variable, Lesen einer vorhandenen Datei und die Default-Warnung bleiben. Neue Tests in `test_secret_key_file.py` mit `SECRET_KEY` leer und `config.DATA_DIR` auf `tmp_path`: (a) zwei Threads rufen `config._resolve_secret_key()`; `monkeypatch.setattr(config, "secrets", types.SimpleNamespace(token_urlsafe=<Stand-in>))` (das Stdlib-Modul bleibt unberührt), der Stand-in je Aufruf einen eigenen Wert liefert und vorher an `threading.Barrier(2, timeout=10)` wartet — beide Threads haben die Existenzprüfung hinter sich, bevor einer schreibt → beide liefern denselben Schlüssel, und `.secret_key` hält ihn (Assertion nennt beide Werte). (b) Der Stand-in schreibt `.secret_key` mit `competitor-key` (ein anderer Prozess veröffentlicht nach der Prüfung) und liefert `own-key` → Rückgabe `competitor-key`, die Datei bleibt `competitor-key`. (c) eine leere `.secret_key` wird durch den erzeugten Schlüssel ersetzt, Modus `0o600`. (d) `os.link` wirft `PermissionError(errno.EPERM, "Operation not permitted")` → Rückgabe des erzeugten Schlüssels, die Datei hält ihn, genau eine WARNING nennt `PermissionError`. In (a) bis (d) bleibt im Verzeichnis nur `.secret_key`. Zuerst rot: (a) und (b) auf dem Stand vor dem Fix (verschiedene Schlüssel; `own-key` überschreibt).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_secret_key_file.py
Doku: CHANGELOG.md (Fixed, umlautfrei: ohne gesetztes `SECRET_KEY` erzeugen Server-Worker und Scheduler beim ersten Start nur noch einen gemeinsamen Schluessel; wer ihn nicht zuerst schreibt, uebernimmt den des anderen Prozesses — vorher konnte jeder Prozess einen eigenen erzeugen und JWTs galten nicht prozessuebergreifend)
Abhängt von: T1
Beweis: Code-Lesung origin/main@53a7dbc5 apps/server/app/core/config.py:23-34 und feature/server-hardening@88e0ad98 :43-53 (Prüfen, dann Schreiben, nicht atomar); Mehrprozess-Start: apps/server/docker-entrypoint.sh:44, :54-58, docker-compose.yml:137-176; der Test (a) dieser Task ist vor dem Fix dreimal identisch rot (`1 failed`, zwei verschiedene Schlüssel)
Orakel: contract — gleichzeitige Erzeuger liefern denselben Schlüssel, die Datei hält ihn
Dedup-Key: bug:server:config.py:secret-key-per-worker
HEAD: 53a7dbc5

### T3 — Nur ein Worker erzeugt das Bootstrap-Token  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/tests/conftest.py, apps/server/tests/test_bootstrap_workers.py, CHANGELOG.md, docs/admin/betrieb.html, docs/en/admin/operations.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d3b8e0f3 2026-10-29T09:38:00+01:00
Review: approve (.ah-out/review/server-multiworker/T3.verdict.json)
Änderung: In `main.py` neben den Bootstrap-Imports (SH `:24-30`): Modul-Konstante `_BOOTSTRAP_LOCK_FILE = BOOTSTRAP_TOKEN_FILE.with_name(".bootstrap.lock")` und Modul-Variable `_bootstrap_lock_fd: int | None = None`. Neue Funktion `_hold_bootstrap_lock() -> bool`: hält dieser Prozess die Sperre schon (`_bootstrap_lock_fd is not None`) → `True`; sonst `os.open(_BOOTSTRAP_LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)` und `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`; Erfolg → `_bootstrap_lock_fd = fd`, `True`; `BlockingIOError` → `os.close(fd)`, `logger.info("bootstrap token left to another worker of this start")`, `False`; ein anderer `OSError` (Öffnen oder `flock`) → Deskriptor schließen, falls offen, `logger.warning("bootstrap lock unavailable (%s); writing the token anyway", type(exc).__name__)`, `True`. `_emit_bootstrap_token` (SH `:132-158`) kehrt am Anfang zurück, wenn `_hold_bootstrap_lock()` `False` liefert; sonst unverändert (Hash, dann Setup-Datei, Banner). Kommentar fürs Warum: jeder uvicorn-Worker fährt die Lifespan (Spec, Problem), die Sperre gehört dem Prozess bis zu seinem Ende, damit genau ein Worker je Start schreibt und ein Neustart neu würfelt; die Datei wird nie gelöscht (zwei Leiter, Spec Trade-off 2); der Pfad ist eine Konstante, nicht aus dem beim Aufruf gültigen `BOOTSTRAP_TOKEN_FILE` abgeleitet. `conftest.py`: am Ende ein `autouse`-Fixture mit `scope="session"`, das `app.main._BOOTSTRAP_LOCK_FILE` auf eine Datei in `tmp_path_factory.mktemp("bootstrap-lock")` setzt (mit `pytest.MonkeyPatch.context()`), Kommentar: `DATA_DIR` der Tests ist zwischen Worktrees geteilt (`conftest.py:15`), und der Prozess, der zuerst emittiert, hält die Sperre bis zum Ende der Session. Neue Testdatei `apps/server/tests/test_bootstrap_workers.py` mit SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`), ohne DB; ein Fixture lenkt `app.main.BOOTSTRAP_TOKEN_FILE`, `BOOTSTRAP_SETUP_FILE` und `_BOOTSTRAP_LOCK_FILE` nach `tmp_path` um und setzt `_bootstrap_lock_fd` auf `None` (`monkeypatch.setattr(..., raising=False)`, damit der Test vor dem Fix an der Assertion scheitert, nicht am Namen) und schließt nach dem Test einen dabei geholten Deskriptor. (a) Der Test hält die Sperre selbst (eigenes `os.open` plus `flock(LOCK_EX|LOCK_NB)` = ein anderer Worker; flock(2): Sperren hängen an der offenen Dateibeschreibung), die beiden Dateien sind mit `leader-hash`/`leader-token` vorbelegt → `_emit_bootstrap_token()` lässt beide unverändert, kein Banner (keine WARNING von `app.main`). (b) Danach gibt der Test seine Sperre frei (`os.close`) → `_emit_bootstrap_token()` schreibt ein Paar mit `hash_api_key(<Setup-Datei>) == <Hash-Datei>`; ein zweiter Aufruf im selben Prozess schreibt ein neues, wieder stimmiges Paar. (c) `fcntl.flock` wirft `OSError(errno.ENOLCK, "No locks available")` → ein stimmiges Paar wird geschrieben, genau eine WARNING nennt `OSError`, `No locks available` steht nicht in `caplog.text`. Zuerst rot: (a) auf dem Stand vor dem Fix (die vorbelegten Dateien werden überschrieben). Die bestehenden Tests in `test_bootstrap.py` bleiben grün (sie emittieren unter der Sperre aus dem Session-Fixture).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bootstrap_workers.py tests/test_bootstrap.py
Doku: CHANGELOG.md (Fixed, umlautfrei: mit `WEB_CONCURRENCY` > 1 erzeugt nur noch ein Worker das einmalige Setup-Token; Hash und `.bootstrap_setup` passen immer zusammen, der Hinweis steht einmal im Log; neue leere Datei `data/.bootstrap.lock`) · docs/admin/betrieb.html und docs/en/admin/operations.html: Zeile für die Sperrdatei in der Tabelle der Datendateien, im Stil der Nachbarzeilen (DE `data/.bootstrap.lock` bei `betrieb.html:75-76`, EN `/data/.bootstrap.lock` bei `operations.html:42-43`): leer, sorgt dafür, dass nur ein Worker das Setup-Token erzeugt, darf bei gestopptem Server gelöscht werden
Beweis: Code-Lesung origin/main@53a7dbc5 apps/server/app/main.py:83, :94, :132-148 (jeder Worker erzeugt und schreibt Hash und Setup-Datei ohne Abstimmung) und docker-entrypoint.sh:54-58 (`--workers`); der Test (a) dieser Task ist vor dem Fix dreimal identisch rot (`1 failed`, Dateien überschrieben)
Orakel: contract — ohne die Sperre schreibt ein Worker nichts; der Inhaber schreibt ein stimmiges Paar
Dedup-Key: bug:server:main.py:bootstrap-multi-worker
HEAD: 53a7dbc5

### T4 — `write_frps_config` synct nach dem Tausch das Verzeichnis  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/docker_manager.py, apps/server/tests/test_frp_docker_manager.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @12822668 2026-10-29T09:44:03+01:00
Review: approve (.ah-out/review/server-multiworker/T4.verdict.json)
Änderung: `write_frps_config` (`apps/server/app/modules/frp/docker_manager.py:26-54`) ruft nach `os.replace(tmp, path)` (`:47`) `fsync_dir(FRP_CONFIG_DIR)` aus `app.core.config` (Import neben `FRP_CONFIG_DIR`, `:14`), außerhalb des `except`, das die Temp-Datei entfernt; der Docstring (`:29-34`) nennt den Verzeichnis-`fsync`. Der bestehende Test `test_a_reader_never_sees_a_half_written_file` (`tests/test_frp_docker_manager.py:53-93`) erwartet heute `events == ["fsync", "replace"]` (`:88`); er wird auf den neuen Vertrag erweitert, nicht abgeschwächt: der Spion hält je `fsync` fest, ob der Deskriptor ein Verzeichnis ist, und die Assertion verlangt `fsync` (Datei), `replace`, `fsync` (Verzeichnis `frp_dir`). Neuer Test daneben: `os.fsync` wirft für Verzeichnis-Deskriptoren `OSError(errno.EINVAL, "Invalid argument")` → `write_frps_config` gibt den Pfad zurück, die Datei hält die neue Config, genau eine WARNING nennt `OSError`, kein `exc_info`. Zuerst rot: die erweiterte Assertion und der neue Test auf dem Stand vor dem Fix.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_docker_manager.py
Doku: keine (intern)
Abhängt von: T1
Beweis: Code-Lesung origin/main@53a7dbc5 apps/server/app/modules/frp/docker_manager.py:41-47 (`fsync` der Datei, `os.replace`, kein `fsync` des Verzeichnisses); die erweiterte Assertion ist vor dem Fix rot (`1 failed`)
Orakel: contract — nach dem Tausch folgt ein `fsync` von `FRP_CONFIG_DIR`
Dedup-Key: ref:server:config.py:no-dir-fsync
HEAD: 53a7dbc5

### T5 — `remove_frps_config` loggt einen Fehler nur mit Typ  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/docker_manager.py, apps/server/tests/test_frp_docker_manager.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @1c258c20 2026-10-29T10:00:57+01:00
Review: approve (.ah-out/review/server-multiworker/T5.verdict.json)
Änderung: In `remove_frps_config` (`docker_manager.py:89-101`) wird `except OSError: logger.exception("could not remove frps.toml (%s)", path)` (`:98-99`) zu `except OSError as exc: logger.error("could not remove frps.toml (%s): %s", path, type(exc).__name__)` — Stufe ERROR bleibt (Spec, Trade-off 5), Traceback und Fehlertext fallen weg, wie `:66` und `:82`. `test_remove_logs_an_oserror_instead_of_raising` (`tests/test_frp_docker_manager.py:150-156`) bleibt unverändert. Neuer Test daneben, Aufbau wie dort (`frps.toml` als Verzeichnis, `unlink` scheitert mit `IsADirectoryError`): genau ein ERROR-Record vom Logger von `docker_manager`, dessen Meldung `frps.toml` und `IsADirectoryError` nennt; kein Record mit `exc_info`; `Is a directory` steht nicht in `caplog.text`. Zuerst rot auf dem Stand vor dem Fix (`exc_info` gesetzt, Traceback samt Text im Log).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_docker_manager.py
Doku: CHANGELOG.md (Changed, umlautfrei: neuer Eintrag „Server-Log nennt bei weiteren Fehlern nur den Fehlertyp“ — scheitert das Entfernen der `frps.toml`, steht im Log der Fehlertyp ohne Traceback; T6 und T7 ergaenzen denselben Eintrag)
Abhängt von: T4
Beweis: Code-Lesung origin/main@53a7dbc5 apps/server/app/modules/frp/docker_manager.py:98-99 (`logger.exception`); Konvention :66, :82; der neue Test ist vor dem Fix rot (`1 failed`)
Orakel: contract — vom Fehler steht im Log nur sein Typ
Dedup-Key: ref:server:docker_manager.py:remove-logs-traceback
HEAD: 53a7dbc5

### T6 — Rate-Limit: Redis-Warnungen nur mit Typ, IPv6-Ziel in Klammern  [x]
Komponente: server · Dateien: apps/server/app/core/rate_limit.py, apps/server/tests/test_rate_limit.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @7267d0bc 2026-10-29T10:16:21+01:00
Review: approve (.ah-out/review/server-multiworker/T6.verdict.json)
Änderung: In `RedisBackend` (SH `apps/server/app/core/rate_limit.py:80-114`) loggen `get_count`, `increment` und `reset` statt `e` nur `type(e).__name__`, englisch: `"Redis get failed (%s), falling back to in-memory: %s"`, `"Redis incr failed (%s), falling back to in-memory: %s"`, `"Redis del failed (%s): %s"` mit `key` und Typ (SH `:95`, `:106`, `:113`); der Rückfall bleibt. `_redis_target` (SH `:125-142`) setzt einen Host mit `:` in eckige Klammern (SH `:141`): `redis://[2001:db8::1]:6379`. Tests in `test_rate_limit.py`: (a) ein Client-Stand-in, dessen `get`, `pipeline().execute()` und `delete` `ConnectionError("Error 111 connecting to redis.example:6379 password=s3cr3t-pw")` werfen → `get_count` liefert 0, `increment` 1, `reset` wirft nicht; je Aufruf genau eine WARNING von `adminhelper.rate_limit`, die `ConnectionError` nennt; `s3cr3t-pw` und `Error 111` stehen nicht in `caplog.text`; kein `exc_info`. (b) Die Parametrisierung von `test_redis_target_keeps_only_scheme_host_and_port` (SH `tests/test_rate_limit.py:172-188`) bekommt `("redis://:s3cr3t-pw@[2001:db8::1]:6379/0", "redis://[2001:db8::1]:6379")` und `("rediss://[2001:db8::1]", "rediss://[2001:db8::1]")`. Zuerst rot: (a) und (b) auf dem Stand vor dem Fix (Fehlertext im Log; Ziel ohne Klammern).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_rate_limit.py
Doku: CHANGELOG.md (Changed, umlautfrei: den Eintrag aus T5 ergaenzen — die Warnungen des Redis-Rate-Limits nennen nur den Fehlertyp; ein IPv6-Host steht im Log in Klammern)
Beweis: Code-Lesung feature/server-hardening@88e0ad98 apps/server/app/core/rate_limit.py:95, :106, :113 (Fehlertext), :141 (Host ohne Klammern); Probe `urllib.parse.urlsplit("redis://:pw@[2001:db8::1]:6379/0")` → `hostname='2001:db8::1'`; Test (b) ist vor dem Fix rot (`2 failed`)
Orakel: contract — vom Fehler steht im Log nur sein Typ; das Ziel ist eindeutig lesbar
Dedup-Key: ref:server:rate_limit.py:log-hygiene
HEAD: 53a7dbc5

### T7 — SSE-Start und Bootstrap-Löschfehler: Log nur mit Typ, englisch  [x]
Komponente: server · Dateien: apps/server/app/main.py, apps/server/app/modules/users/auth_router.py, apps/server/tests/test_log_hygiene.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8e43e521 2026-10-29T10:20:53+01:00
Review: approve (.ah-out/review/server-multiworker/T7.verdict.json)
Änderung: In `lifespan` (`apps/server/app/main.py:374-381`; SH `:366-373`) wird `except Exception: logger.exception("SSE-Fan-out-Start fehlgeschlagen — Push deaktiviert (Polling-Fallback)")` zu `except Exception as exc: logger.warning("SSE fan-out not started (%s); push disabled, clients poll", type(exc).__name__)`; der Kommentar darüber bleibt. In der Bootstrap-Route (`apps/server/app/modules/users/auth_router.py:345-351`) wird `except OSError: logger.warning("Bootstrap-Datei konnte nicht geloescht werden: %s", f)` zu `except OSError as exc: logger.warning("bootstrap file %s not removed (%s)", f, type(exc).__name__)`; Docstring der Route unverändert. Neue Testdatei `apps/server/tests/test_log_hygiene.py` mit SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`): (a) Lifespan wie `test_lifespan_survives_redis_outage_at_boot` (SH `tests/test_bootstrap.py:246-277`: `_run_startup_tasks`, `events.fire_event`, `stream_hub.start`/`stop` ersetzt), `stream_hub.start` wirft `ConnectionError("redis://:s3cr3t-pw@redis.example:6379 unreachable")` → die Lifespan erreicht `yield`; genau eine WARNING von `app.main`, die `ConnectionError` nennt; `s3cr3t-pw` steht nicht in `caplog.text`; kein Record mit `exc_info`. (b) `test_client` mit leerer DB, `auth_router.BOOTSTRAP_TOKEN_FILE`/`BOOTSTRAP_SETUP_FILE` per `monkeypatch` nach `tmp_path` (Hash eines frischen Tokens, Setup-Datei vorhanden), `pathlib.Path.unlink` wirft für die Setup-Datei `PermissionError(errno.EACCES, "Permission denied", <pfad>)` → `POST /api/auth/bootstrap` antwortet 201, die Hash-Datei ist weg; genau eine WARNING von `adminhelper.auth_router` nennt `.bootstrap_setup` und `PermissionError`; `Permission denied` steht nicht in `caplog.text`. Zuerst rot: (a) und (b) auf dem Stand vor dem Fix (`exc_info` samt Text; Meldung ohne Typ).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_log_hygiene.py tests/test_bootstrap.py tests/test_openapi_snapshot.py
Doku: CHANGELOG.md (Changed, umlautfrei: den Eintrag aus T5 ergaenzen — ein gescheiterter Start des SSE-Push und ein Loeschfehler der Bootstrap-Dateien nach dem ersten Admin stehen mit Fehlertyp, ohne Traceback, im Log)
Abhängt von: T3
Beweis: Code-Lesung origin/main@53a7dbc5 apps/server/app/main.py:381 (`logger.exception`) und apps/server/app/modules/users/auth_router.py:351 (deutsch, ohne Typ); Test (b) ist vor dem Fix rot (`1 failed`)
Orakel: contract — vom Fehler steht im Log nur sein Typ
Dedup-Key: ref:server:rate_limit.py:log-hygiene
HEAD: 53a7dbc5

### T8 — Eine Hochstufung sperrt die Zielzeile  [x]
Komponente: server · Dateien: apps/server/app/modules/users/router.py, apps/server/tests/test_users_promotion_event.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2e6379b6 2026-10-29T10:26:56+01:00
Review: approve (.ah-out/review/server-multiworker/T8.verdict.json)
Änderung: In `update_user` (`apps/server/app/modules/users/router.py:97-152`; AC `:105`) wird die Zielzeile bei einer Hochstufung gesperrt gelesen: `query = db.query(User).filter(User.id == user_id)`; `if data.is_admin: query = query.with_for_update().populate_existing()`; `user = query.first()`. Nur bei `is_admin: true`, weil eine Sperre des Ziels vor der Admin-Sperre der Herabstufung (`:128-132`) die Sperr-Reihenfolge umkehrte (Deadlock bei A↔B-Herabstufung, Spec Trade-off 3); `populate_existing()` wie `apps/server/app/main.py:295-300`. Kommentar fürs Warum: zwei gleichzeitige Hochstufungen läsen sonst beide `is_admin = false` und legten zwei Standardregeln an und feuerten `user.promoted` zweimal. Kein `db.refresh(..., with_for_update=True)` nach Änderungen (verwürfe ein gesetztes Passwort). Docstring und Antwort der Route unverändert. Neuer Test in `test_users_promotion_event.py` (Helfer `fired`, `_headers`, `_promoted` aus AC; `_a_session_waits_for` aus `tests/test_identity_revocation.py:234-248` importiert, wie dort `from tests.test_certificate_check import …`): ein Fixture legt den Zielbenutzer (`promo-race-<uuid>`, kein Admin) über `sessionmaker(bind=pg_engine)` committet an und löscht im Teardown seine `NotificationSubscription`-Zeilen und ihn selbst; es steht in der Signatur vor `test_client`/`db_session`, damit sein Teardown nach dem Rollback von `db_session` läuft (bis dahin hält dessen offene Transaktion die Zeilensperre). Ablauf: Login im Haupt-Thread; eine zweite Session sperrt die Zielzeile (`with_for_update().one()`, `pg_backend_pid()`); der `PUT {"is_admin": true}` läuft in einem `ThreadPoolExecutor`; `_a_session_waits_for(pg_engine, pid)` muss `True` liefern; dann setzt die zweite Session `is_admin = True`, legt `default_admin_subscription(<id>)` an und committet (die erste Hochstufung); der `PUT` antwortet 200. Erwartet: über `db_session` genau eine `NotificationSubscription` des Ziels, `_promoted(fired) == []`; die Assertion nennt die gezählte Zahl. `finally`: zweite Session schließen, Executor beenden. Zuerst rot auf dem Stand vor dem Fix: der `PUT` wartet dort erst beim `UPDATE`, nachdem er ungesperrt `is_admin = false` gelesen hat → zwei Regeln und ein `user.promoted`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_users_promotion_event.py tests/test_users_last_admin.py tests/test_users.py tests/test_openapi_snapshot.py
Doku: CHANGELOG.md (Fixed, umlautfrei: zwei gleichzeitige Hochstufungen desselben Benutzers zum Admin legen nur noch eine Standard-Benachrichtigungsregel an und loesen `user.promoted` einmal aus)
Beweis: Code-Lesung origin/feature/audit-coverage@62c24174 apps/server/app/modules/users/router.py:105 (ohne Sperre), :108 (`was_admin`), :146-147 (`user.promoted`); origin/main@53a7dbc5 :117-125 (Standardregel ohne Eindeutigkeit, apps/server/app/modules/notifications/models.py:39-80); der Test dieser Task ist vor dem Fix dreimal identisch rot (`1 failed`, zwei Regeln)
Orakel: contract — eine nebenläufige zweite Hochstufung ändert nichts mehr
Dedup-Key: bug:server:users/router.py:promote-without-row-lock
HEAD: 53a7dbc5
