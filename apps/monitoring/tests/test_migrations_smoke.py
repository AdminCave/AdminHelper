# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Migration-chain smoke test (audit T1), monitoring variant.

The monitoring suite is deliberately DB-free, so this test only runs when a
Postgres is available via DATABASE_URL (CI provides a service container; local
runs skip). It builds a fresh database via `alembic upgrade head` and asserts
the result matches the models exactly."""

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

DB_URL = os.environ.get("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason="DATABASE_URL nicht gesetzt — Migrations-Smoke laeuft in CI (Postgres-Service)",
)

MONITORING_DIR = Path(__file__).resolve().parents[1]


def _drop_database(admin_engine, dbname: str) -> None:
    """Drop a throwaway database without the FORCE option.

    FORCE terminates every other backend on that database and needs the privilege to
    do so. An autovacuum worker that happens to be on the freshly migrated database
    advertises no role at all (its roleId is invalid), so FORCE from a plain test role
    fails with "permission denied to terminate process" unless the role has
    pg_signal_backend — the flake seen in the 2026-09-10 weekly run. A plain DROP lets
    Postgres retire its own autovacuum workers (it signals them and waits up to 5 s).
    Our own connections are disposed by the caller before this runs, so there is
    nothing else to wait for.
    """
    from sqlalchemy import text

    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{dbname}"'))


def _normalize(url: str) -> str:
    for old in ("postgresql+psycopg2://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old) :]
    return url


@contextmanager
def scratch_db(monkeypatch, tag: str):
    """A throwaway database plus a ready alembic Config, yielded as (cfg, engine).

    Every test here needs the same four steps — CREATE DATABASE, point
    app.core.config.DATABASE_URL at it (env.py reads that attribute at
    execution time, so patching the ini would not take), build the Config, and
    DROP it afterwards.

    The caller decides how far to migrate: `command.upgrade(cfg, "head")` for
    the parity check, or a specific revision to plant data at an intermediate
    state before applying the next one.
    """
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    import app.core.config as app_config

    admin_engine = create_engine(_normalize(DB_URL), isolation_level="AUTOCOMMIT")
    dbname = f"alembic_{tag}_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))

    smoke_url = admin_engine.url.set(database=dbname).render_as_string(hide_password=False)
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(MONITORING_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(MONITORING_DIR / "alembic"))

    engine = create_engine(smoke_url)
    try:
        yield cfg, engine
    finally:
        engine.dispose()
        _drop_database(admin_engine, dbname)
        admin_engine.dispose()


@pytest.fixture()
def migrated_engine(monkeypatch):
    from alembic import command

    with scratch_db(monkeypatch, "smoke") as (cfg, engine):
        command.upgrade(cfg, "head")
        yield engine


def test_migration_chain_matches_models(migrated_engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.models import Base

    with migrated_engine.connect() as conn:
        # Match env.py's autogenerate context (compare_server_default=True) so a model that loses or
        # changes a server_default no longer passes silently (6.151).
        ctx = MigrationContext.configure(conn, opts={"compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], (
        "Die Alembic-Kette erzeugt ein anderes Schema als die Modelle:\n"
        + "\n".join(str(d) for d in diff)
    )


def test_uniq_template_assignment_dedupes_before_constraint(monkeypatch):
    # 4.44: the migration must delete content-identical duplicate (template_id, server_id) rows
    # before adding the unique constraint — else ADD CONSTRAINT fails and the container
    # crash-loops on boot. Migrate to just before it, plant duplicates, then apply it.
    from alembic import command
    from sqlalchemy import text

    with scratch_db(monkeypatch, "dedupe") as (cfg, engine):
        command.upgrade(cfg, "c85e6dacd792")  # just before the uniq-constraint migration
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_templates (id, name, check_definitions, alert_definitions)"
                    " VALUES ('t1', 'T', '[]', '[]')"
                )
            )
            for aid in ("a1", "a2"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_template_assignments"
                        " (id, template_id, server_id, server_hostname, server_name)"
                        f" VALUES ('{aid}', 't1', 's1', 'h', 'n')"
                    )
                )
        command.upgrade(cfg, "b1a2c3d4e5f6")  # must dedupe + add the constraint without crashing
        with engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM monitor_template_assignments")).scalar()
        assert n == 1  # exactly one row per (template_id, server_id) pair survived


def test_notified_status_backfill_marks_existing_states_as_reported(monkeypatch):
    # alert-sent-state T1: the upgrade must backfill notified_status = status —
    # without it every pre-existing warning/critical state would count as a
    # discrepancy and trigger a catch-up notification storm on deploy.
    from alembic import command
    from sqlalchemy import text

    with scratch_db(monkeypatch, "sentstate") as (cfg, engine):
        command.upgrade(cfg, "b7d9f1a3c5e7")  # just before the sent-state migration
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_checks"
                    " (id, name, check_type, config, interval, severity)"
                    " VALUES ('c1', 'C', 'ping', '{}', '5m', 'critical')"
                )
            )
            conn.execute(
                text("INSERT INTO monitor_states (check_id, status) VALUES ('c1', 'critical')")
            )
        # A check standing on unknown at deploy time: the last SENT status
        # comes from the alert log (c2 -> critical, recovery after the deploy
        # must not be swallowed); without a log entry it stays unknown (c3).
        with engine.begin() as conn:
            for cid in ("c2", "c3"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_checks"
                        " (id, name, check_type, config, interval, severity)"
                        f" VALUES ('{cid}', 'C', 'ping', '{{}}', '5m', 'critical')"
                    )
                )
                conn.execute(
                    text(
                        f"INSERT INTO monitor_states (check_id, status) VALUES ('{cid}', 'unknown')"
                    )
                )
            conn.execute(
                text(
                    "INSERT INTO monitor_alert_rules (id, name, channel, channel_config)"
                    " VALUES ('r1', 'R', 'webhook', '{}')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO monitor_alert_log"
                    " (alert_rule_id, check_id, old_status, new_status, sent_at, success)"
                    " VALUES ('r1', 'c2', 'ok', 'critical', '2026-01-01 00:00:00', true)"
                )
            )
        command.upgrade(cfg, "c1d3e5f7a9b1")
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    text("SELECT check_id, notified_status FROM monitor_states")
                ).fetchall()
            )
        assert rows == {"c1": "critical", "c2": "critical", "c3": "unknown"}


def test_alert_quality_backfill_and_downgrade(monkeypatch):
    # alert-quality T1: every existing check gets consecutive_oks 2 and every state
    # ok_count 0. hub_status follows a REPORTED warning/critical (notified_status, not
    # status: c4 recovered, its recovery is not reported yet), else the bell would
    # never clear a problem it showed before the deploy; hub_sent_at starts empty, so
    # no bell cooldown runs. The downgrade must take all four columns away again.
    from alembic import command
    from sqlalchemy import inspect, text

    with scratch_db(monkeypatch, "alertquality") as (cfg, engine):
        command.upgrade(cfg, "b9d1f3a5c7e9")  # just before the alert-quality migration
        with engine.begin() as conn:
            for cid, status, notified in (
                ("c1", "critical", "critical"),
                ("c2", "ok", "ok"),
                ("c3", "unknown", "unknown"),
                ("c4", "ok", "warning"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO monitor_checks"
                        " (id, name, check_type, config, interval, severity)"
                        " VALUES (:id, 'C', 'ping', '{}', '5m', 'critical')"
                    ),
                    {"id": cid},
                )
                conn.execute(
                    text(
                        "INSERT INTO monitor_states (check_id, status, notified_status)"
                        " VALUES (:id, :status, :notified)"
                    ),
                    {"id": cid, "status": status, "notified": notified},
                )
        command.upgrade(cfg, "3c66308d11a7")
        with engine.connect() as conn:
            checks = dict(
                conn.execute(text("SELECT id, consecutive_oks FROM monitor_checks")).fetchall()
            )
            states = {
                row[0]: tuple(row[1:])
                for row in conn.execute(
                    text("SELECT check_id, ok_count, hub_status, hub_sent_at FROM monitor_states")
                ).fetchall()
            }
        assert checks == {"c1": 2, "c2": 2, "c3": 2, "c4": 2}
        assert states == {
            "c1": (0, "critical", None),
            "c2": (0, None, None),
            "c3": (0, None, None),
            "c4": (0, "warning", None),
        }

        command.downgrade(cfg, "b9d1f3a5c7e9")
        insp = inspect(engine)
        check_cols = {c["name"] for c in insp.get_columns("monitor_checks")}
        state_cols = {c["name"] for c in insp.get_columns("monitor_states")}
        assert "consecutive_oks" not in check_cols
        assert {"ok_count", "hub_status", "hub_sent_at"}.isdisjoint(state_cols)
        # Paired with the two negatives: the inspector does read both tables, and the
        # downgrade dropped only its own columns.
        assert {"consecutive_fails"} <= check_cols
        assert {"fail_count", "notified_status"} <= state_cols


def test_module_tombstones_upgrade_and_downgrade(monkeypatch):
    # kern-monitoring-20 T1: additive. A module check from before keeps its row with
    # no hash; one tombstone per (server, module, instance, check key); the
    # downgrade takes the table and the column away again.
    from alembic import command
    from sqlalchemy import exc, inspect, text

    with scratch_db(monkeypatch, "tombstones") as (cfg, engine):
        command.upgrade(cfg, "c1e3a5b7d9f0")  # just before the tombstone migration
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_checks"
                    " (id, name, check_type, config, interval, severity, module_id)"
                    " VALUES ('c1', 'C', 'tcp', '{}', '5m', 'critical', 'nginx')"
                )
            )
        command.upgrade(cfg, "a7c9e1f3b5d7")
        with engine.connect() as conn:
            hashes = conn.execute(text("SELECT id, module_check_hash FROM monitor_checks")).all()
        assert hashes == [("c1", None)]
        insert = text(
            "INSERT INTO monitor_module_tombstones"
            " (id, server_id, module_id, instance_key, check_key)"
            " VALUES (:id, 's1', 'nginx', '', 'port')"
        )
        with engine.begin() as conn:
            conn.execute(insert, {"id": "t1"})
        with pytest.raises(exc.IntegrityError), engine.begin() as conn:
            conn.execute(insert, {"id": "t2"})

        command.downgrade(cfg, "c1e3a5b7d9f0")
        insp = inspect(engine)
        assert "monitor_module_tombstones" not in insp.get_table_names()
        check_cols = {c["name"] for c in insp.get_columns("monitor_checks")}
        assert "module_check_hash" not in check_cols
        # Paired with the negatives: the inspector reads the schema, and the
        # downgrade dropped only what the migration added.
        assert {"module_id", "module_check_key"} <= check_cols
        assert "monitor_check_tombstones" in insp.get_table_names()


def test_status_log_takes_over_the_alert_log_and_downgrades(monkeypatch):
    # arch-monitoring-neu-p1 T2: every alert-log row becomes a check row of the status
    # change log (origin alert_log, at = sent_at), so the history does not go blank on
    # the update; the log follows its check; the downgrade drops only the new table.
    from datetime import datetime

    from alembic import command
    from sqlalchemy import inspect, text

    with scratch_db(monkeypatch, "statuslog") as (cfg, engine):
        command.upgrade(cfg, "a7c9e1f3b5d7")  # just before the status change log
        with engine.begin() as conn:
            for cid in ("c1", "c2"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_checks"
                        " (id, name, check_type, config, interval, severity)"
                        " VALUES (:id, 'C', 'ping', '{}', '5m', 'critical')"
                    ),
                    {"id": cid},
                )
            for rid in ("r1", "r2"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_alert_rules (id, name, channel, channel_config)"
                        " VALUES (:id, 'R', 'webhook', '{}')"
                    ),
                    {"id": rid},
                )
            conn.execute(
                text(
                    "INSERT INTO monitor_alert_log"
                    " (alert_rule_id, check_id, old_status, new_status, sent_at, success)"
                    " VALUES (:rule, :check, :old, :new, :at, :ok)"
                ),
                [
                    {
                        "rule": "r1",
                        "check": "c1",
                        "old": "ok",
                        "new": "critical",
                        "at": "2026-11-01 10:00:00",
                        "ok": True,
                    },
                    {
                        "rule": "r2",
                        "check": "c1",
                        "old": "ok",
                        "new": "critical",
                        "at": "2026-11-01 10:00:01",
                        "ok": False,
                    },
                    {
                        "rule": "r1",
                        "check": "c2",
                        "old": "critical",
                        "new": "ok",
                        "at": "2026-11-02 08:30:00",
                        "ok": True,
                    },
                ],
            )

        command.upgrade(cfg, "d2f4a6c8e0b1")
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT check_id, object_key, old_status, new_status, at, origin"
                    " FROM monitor_status_log ORDER BY at"
                )
            ).all()
        assert [tuple(r) for r in rows] == [
            ("c1", None, "ok", "critical", datetime(2026, 11, 1, 10, 0, 0), "alert_log"),
            ("c1", None, "ok", "critical", datetime(2026, 11, 1, 10, 0, 1), "alert_log"),
            ("c2", None, "critical", "ok", datetime(2026, 11, 2, 8, 30, 0), "alert_log"),
        ]

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM monitor_checks WHERE id = 'c2'"))
        with engine.connect() as conn:
            left = conn.execute(text("SELECT check_id FROM monitor_status_log")).scalars().all()
        assert sorted(left) == ["c1", "c1"]

        command.downgrade(cfg, "a7c9e1f3b5d7")
        insp = inspect(engine)
        assert "monitor_status_log" not in insp.get_table_names()
        # Paired with the negative: the inspector reads the schema, and the alert log
        # keeps its rows (c2's went with its check).
        assert "monitor_alert_log" in insp.get_table_names()
        with engine.connect() as conn:
            kept = conn.execute(text("SELECT count(*) FROM monitor_alert_log")).scalar()
        assert kept == 2


def test_object_state_upgrades_and_downgrades(monkeypatch):
    # arch-monitoring-neu-p1 T4: the object state starts empty, takes a key of the full
    # 200 characters and follows its check; the downgrade drops only the new table.
    from alembic import command
    from sqlalchemy import inspect, text

    with scratch_db(monkeypatch, "objstate") as (cfg, engine):
        command.upgrade(cfg, "d2f4a6c8e0b1")  # just before the object state
        with engine.begin() as conn:
            for cid in ("c1", "c2"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_checks"
                        " (id, name, check_type, config, interval, severity)"
                        " VALUES (:id, 'C', 'ping', '{}', '5m', 'critical')"
                    ),
                    {"id": cid},
                )
            conn.execute(
                text(
                    "INSERT INTO monitor_status_log (check_id, old_status, new_status, at, origin)"
                    " VALUES ('c1', 'ok', 'critical', '2026-11-01 10:00:00', 'state')"
                )
            )

        command.upgrade(cfg, "e3a5c7e9f1b2")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM monitor_object_state")).scalar() == 0

        long_key = "srv-1/disk/" + "a" * (200 - len("srv-1/disk/"))
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_object_state"
                    " (check_id, object_key, kind, name, status, reason, since, fail_count,"
                    " stable) VALUES (:check, :key, 'disk', 'n', 'ok', '',"
                    " '2026-11-19 12:00:00', 0, true)"
                ),
                [{"check": "c1", "key": long_key}, {"check": "c2", "key": "srv-1/disk/sdb"}],
            )
            conn.execute(text("DELETE FROM monitor_checks WHERE id = 'c2'"))
        with engine.connect() as conn:
            left = conn.execute(text("SELECT check_id, object_key FROM monitor_object_state")).all()
        assert [tuple(r) for r in left] == [("c1", long_key)]

        command.downgrade(cfg, "d2f4a6c8e0b1")
        insp = inspect(engine)
        assert "monitor_object_state" not in insp.get_table_names()
        # Paired with the negative: the status change log keeps its row.
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM monitor_status_log")).scalar() == 1


# arch-monitoring-neu-p1b T1 (R-1636): every maintenance window, of every form.
def _window(id, server_id, kind, **kw):
    row = dict(
        id=id,
        server_id=server_id,
        kind=kind,
        starts_at=None,
        ends_at=None,
        weekdays=None,
        start_time=None,
        duration_minutes=None,
        timezone="UTC",
        note=None,
        enabled=True,
    )
    row.update(kw)
    return row


_MARCH_29 = dict(starts_at="2026-03-29 00:00", ends_at="2026-03-29 03:00")
_WINDOWS = [
    _window("once-srv1", "srv-1", "once", note="Patch", **_MARCH_29),
    _window("once-all", None, "once", starts_at="2026-10-25 00:30", ends_at="2026-10-25 01:15"),
    # Saturday 23:30 for 90 minutes: across midnight.
    _window(
        "weekly-midnight", "srv-2", "weekly", weekdays="[5]", start_time="23:30",
        duration_minutes=90, note="Backup",
    ),
    # Sunday 02:30 Berlin: missing on 2026-03-29, twice on 2026-10-25.
    _window(
        "weekly-berlin", None, "weekly", weekdays="[6]", start_time="02:30",
        duration_minutes=60, timezone="Europe/Berlin",
    ),
    _window(
        "weekly-ny", "srv-1", "weekly", weekdays="[0, 6]", start_time="01:30",
        duration_minutes=60, timezone="America/New_York",
    ),
    # Saturday and Sunday 22:00 Berlin for three hours, across midnight and DST.
    _window(
        "weekly-days", "srv-3", "weekly", weekdays="[5, 6]", start_time="22:00",
        duration_minutes=180, timezone="Europe/Berlin",
    ),
    # An unknown zone falls back to UTC.
    _window(
        "bad-tz", "srv-3", "weekly", weekdays="[6]", start_time="03:00", duration_minutes=60,
        timezone="Mars/Olympus",
    ),
    _window("off", "srv-1", "once", enabled=False, **_MARCH_29),
    _window("null-enabled", "srv-2", "once", enabled=None, **_MARCH_29),
    _window("no-times-once", "srv-1", "once"),
    _window("no-times-weekly", None, "weekly", weekdays="[0]"),
]  # fmt: skip

# The windows the grid must find active, so the equivalence cannot pass on nothing.
_MUST_MUTE = {
    "once-srv1",
    "once-all",
    "weekly-midnight",
    "weekly-berlin",
    "weekly-ny",
    "weekly-days",
    "bad-tz",
}
_MAINTENANCE_COLUMNS = (
    "id, server_id, kind, starts_at, ends_at, weekdays, start_time, duration_minutes,"
    " timezone, note, enabled, created_at"
)


def _time_grid():
    """Every quarter hour around the DST changes of Berlin and New York in 2026 and the
    weekends they fall on: the window times sit on full and half hours."""
    from datetime import date, datetime, timedelta

    days = [
        date(2026, 3, 7),
        date(2026, 3, 8),
        date(2026, 3, 28),
        date(2026, 3, 29),
        date(2026, 10, 24),
        date(2026, 10, 25),
        date(2026, 10, 31),
        date(2026, 11, 1),
    ]
    grid = set()
    for d in days:
        start = datetime(d.year, d.month, d.day) - timedelta(hours=6)
        grid.update(start + timedelta(minutes=15 * i) for i in range(36 * 4))
    return sorted(grid)


def test_exceptions_take_over_the_maintenance_windows(monkeypatch):
    # Kevin 2026-11-25: the windows move 1:1 and an equivalence test accepts them. For
    # every window and server over the grid, the old evaluator on the old row and the
    # exception scope on the new row agree; the columns carry over; the way back writes
    # the facade's state into monitor_maintenance, and the way up again takes it over.
    from datetime import datetime

    from alembic import command
    from sqlalchemy import inspect, text
    from sqlalchemy.orm import sessionmaker

    from app.exception_scope import covers, in_force, narrowest
    from app.maintenance import is_in_maintenance
    from app.models import MonitorException, MonitorMaintenance

    with scratch_db(monkeypatch, "exceptions") as (cfg, engine):
        command.upgrade(cfg, "e3a5c7e9f1b2")  # just before the exceptions
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO monitor_maintenance ({_MAINTENANCE_COLUMNS})"
                    " VALUES (:id, :server_id, :kind, :starts_at, :ends_at, :weekdays,"
                    " :start_time, :duration_minutes, :timezone, :note, :enabled, :created_at)"
                ),
                [dict(w, created_at=f"2026-01-01 10:{i:02d}:00") for i, w in enumerate(_WINDOWS)],
            )
        select_old = text(f"SELECT {_MAINTENANCE_COLUMNS} FROM monitor_maintenance ORDER BY id")
        with engine.connect() as conn:
            old_rows = [tuple(r) for r in conn.execute(select_old)]
        db = sessionmaker(bind=engine)()
        old = {w.id: w for w in db.query(MonitorMaintenance).all()}
        db.close()
        assert len(old) == len(_WINDOWS)

        command.upgrade(cfg, "f4b6d8a0c2e4")
        with engine.connect() as conn:
            new_rows = conn.execute(
                text(
                    "SELECT id, server_id, duration_kind, starts_at, ends_at, weekdays,"
                    " start_time, duration_minutes, timezone, reason, enabled, created_at,"
                    " scope_kind, effect, origin, check_id, check_type, created_by,"
                    " created_by_id, updated_at, ended_at FROM monitor_exceptions ORDER BY id"
                )
            ).all()
            # monitor_maintenance stays as it is.
            assert [tuple(r) for r in conn.execute(select_old)] == old_rows
        assert [tuple(r) for r in new_rows] == [
            (
                *row[:10],
                bool(row[10]),  # NULL becomes false
                row[11],
                "all" if row[1] is None else "server",
                "no_notify",
                "migration",
                None,
                None,
                None,
                None,
                None,
                None,
            )
            for row in old_rows
        ]
        db = sessionmaker(bind=engine)()
        new = {e.id: e for e in db.query(MonitorException).all()}
        db.close()

        servers = ["srv-1", "srv-2", "srv-3", None]
        muted = set()
        for now in _time_grid():
            for server in servers:
                for wid, window in old.items():
                    before = is_in_maintenance([window], server, now)
                    after = covers(new[wid], None, None, server) and in_force(new[wid], now)
                    assert before == after, (wid, server, now)
                    if before:
                        muted.add(wid)
                assert is_in_maintenance(list(old.values()), server, now) == (
                    narrowest(new.values(), None, None, server, now) is not None
                ), (server, now)
        assert muted == _MUST_MUTE

        with engine.begin() as conn:
            for cid in ("c1", "c2"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_checks"
                        " (id, name, check_type, config, interval, severity)"
                        " VALUES (:id, 'C', 'ping', '{}', '5m', 'critical')"
                    ),
                    {"id": cid},
                )
            conn.execute(
                text(
                    "INSERT INTO monitor_exceptions"
                    " (id, scope_kind, server_id, check_id, effect, duration_kind, origin)"
                    " VALUES (:id, :scope, 'srv-1', :check, 'no_notify', 'permanent', 'api')"
                ),
                [
                    {"id": "on-c1", "scope": "check", "check": "c1"},
                    {"id": "on-c2", "scope": "check", "check": "c2"},
                    {"id": "srv1-permanent", "scope": "server", "check": None},
                ],
            )
            # Ended through the facade: gone from its list, and so from the way back.
            conn.execute(
                text("UPDATE monitor_exceptions SET ended_at = :at WHERE id = 'once-srv1'"),
                {"at": datetime(2026, 11, 25, 10, 0)},
            )
            conn.execute(
                text(
                    "INSERT INTO monitor_object_state"
                    " (check_id, object_key, kind, name, status, reason, since, fail_count,"
                    " stable, excluded) VALUES ('c1', 'srv-1/disk/tmpfs', 'disk', 'tmpfs',"
                    " 'not_collected', '', '2026-11-25 10:00:00', 0, true, :excluded)"
                ),
                {"excluded": "x" * 40},
            )
            conn.execute(text("DELETE FROM monitor_checks WHERE id = 'c2'"))
        with engine.connect() as conn:
            left = conn.execute(
                text("SELECT id FROM monitor_exceptions WHERE scope_kind = 'check'")
            ).scalars()
            assert list(left) == ["on-c1"]  # a check exception goes with its check
            assert (
                conn.execute(
                    text("SELECT enabled FROM monitor_exceptions WHERE id = 'on-c1'")
                ).scalar()
                is True
            )  # the server default

        command.downgrade(cfg, "e3a5c7e9f1b2")
        insp = inspect(engine)
        assert "monitor_exceptions" not in insp.get_table_names()
        assert "excluded" not in {c["name"] for c in insp.get_columns("monitor_object_state")}
        with engine.connect() as conn:
            back = [tuple(r) for r in conn.execute(select_old)]
            # Paired with the negatives: the object state keeps its row.
            assert conn.execute(text("SELECT count(*) FROM monitor_object_state")).scalar() == 1
        assert back == [
            (*row[:10], bool(row[10]), row[11]) for row in old_rows if row[0] != "once-srv1"
        ]

        command.upgrade(cfg, "f4b6d8a0c2e4")
        with engine.connect() as conn:
            again = conn.execute(
                text("SELECT id, scope_kind, origin, enabled FROM monitor_exceptions ORDER BY id")
            ).all()
        assert [tuple(r) for r in again] == [
            (row[0], "all" if row[1] is None else "server", "migration", bool(row[10]))
            for row in old_rows
            if row[0] != "once-srv1"
        ]
