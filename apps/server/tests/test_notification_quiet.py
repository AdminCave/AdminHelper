# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The clock of a person (R-1081): quiet hours and the digest time in their zone
(notifications.quiet), and revision a4b6c8d0e2f4 that adds the columns.

The migration tests follow test_notification_settings.py: a throwaway database on the
session's Postgres, migrated up to the revision before, seeded, then upgraded."""

import uuid
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.core.config as app_config
from app.modules.notifications.models import NotificationSettings
from app.modules.notifications.quiet import in_quiet, next_digest_at, quiet_end
from app.modules.notifications.schemas import _ZONES, NotificationPrefsUpdate

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "a4b6c8d0e2f4"
PREVIOUS = "f3a5c7e9b1d2"


def _settings(start="22:00", end="07:00", tz=None, enabled=True, digest="daily"):
    return NotificationSettings(
        user_id=1,
        matrix="{}",
        timezone=tz,
        quiet_enabled=enabled,
        quiet_start=start,
        quiet_end=end,
        digest=digest,
    )


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class TestQuietHours:
    @pytest.mark.parametrize(
        "now, end",
        [
            # 22:00-07:00 UTC across midnight: before, at the start, after midnight, at the end.
            (_utc(2026, 11, 7, 21, 59), None),
            (_utc(2026, 11, 7, 22, 0), _utc(2026, 11, 8, 7, 0)),
            (_utc(2026, 11, 8, 3, 0), _utc(2026, 11, 8, 7, 0)),
            (_utc(2026, 11, 8, 6, 59), _utc(2026, 11, 8, 7, 0)),
            (_utc(2026, 11, 8, 7, 0), None),
            (_utc(2026, 11, 8, 12, 0), None),
        ],
    )
    def test_across_midnight_in_utc(self, now, end):
        settings = _settings()
        assert quiet_end(settings, now) == end
        assert in_quiet(settings, now) is (end is not None)

    def test_within_a_day(self):
        settings = _settings("12:00", "13:30")
        assert quiet_end(settings, _utc(2026, 11, 7, 11, 59)) is None
        assert quiet_end(settings, _utc(2026, 11, 7, 12, 0)) == _utc(2026, 11, 7, 13, 30)
        assert quiet_end(settings, _utc(2026, 11, 7, 13, 30)) is None
        # Before the start on a day-window is outside, unlike the overnight branch.
        assert quiet_end(settings, _utc(2026, 11, 7, 0, 30)) is None

    def test_off_empty_or_without_settings(self):
        now = _utc(2026, 11, 7, 23, 0)
        assert quiet_end(_settings(enabled=False), now) is None
        assert quiet_end(_settings("22:00", "22:00"), now) is None
        assert quiet_end(None, now) is None

    def test_in_the_persons_zone(self):
        # 22:00-07:00 Berlin in winter (UTC+1) is 21:00-06:00 UTC.
        settings = _settings(tz="Europe/Berlin")
        assert quiet_end(settings, _utc(2026, 11, 7, 20, 59)) is None
        assert quiet_end(settings, _utc(2026, 11, 7, 21, 0)) == _utc(2026, 11, 8, 6, 0)

    def test_a_zone_without_dst(self):
        # Asia/Kolkata is UTC+5:30 all year.
        settings = _settings(tz="Asia/Kolkata")
        assert quiet_end(settings, _utc(2026, 7, 1, 16, 29)) is None
        assert quiet_end(settings, _utc(2026, 7, 1, 16, 30)) == _utc(2026, 7, 2, 1, 30)

    def test_spring_forward_night_is_one_hour_shorter(self):
        # 2026-03-29 Berlin: 02:00 CET -> 03:00 CEST. 22:00 CET = 21:00 UTC, 07:00 CEST = 05:00.
        settings = _settings(tz="Europe/Berlin")
        assert quiet_end(settings, _utc(2026, 3, 28, 21, 0)) == _utc(2026, 3, 29, 5, 0)
        assert quiet_end(settings, _utc(2026, 3, 29, 4, 59)) == _utc(2026, 3, 29, 5, 0)
        assert quiet_end(settings, _utc(2026, 3, 29, 5, 0)) is None

    def test_fall_back_night_is_one_hour_longer(self):
        # 2026-10-25 Berlin: 03:00 CEST -> 02:00 CET. 22:00 CEST = 20:00 UTC, 07:00 CET = 06:00.
        settings = _settings(tz="Europe/Berlin")
        assert quiet_end(settings, _utc(2026, 10, 24, 20, 0)) == _utc(2026, 10, 25, 6, 0)
        assert quiet_end(settings, _utc(2026, 10, 25, 5, 59)) == _utc(2026, 10, 25, 6, 0)
        assert quiet_end(settings, _utc(2026, 10, 25, 6, 0)) is None

    def test_an_end_in_the_repeated_hour(self):
        # 2026-10-25 Berlin repeats 02:00-03:00. The end 02:30 is 00:30 UTC on the first
        # pass (CEST) and 01:30 UTC on the second (CET).
        settings = _settings("22:00", "02:30", tz="Europe/Berlin")
        assert quiet_end(settings, _utc(2026, 10, 25, 0, 10)) == _utc(2026, 10, 25, 0, 30)
        assert quiet_end(settings, _utc(2026, 10, 25, 1, 10)) == _utc(2026, 10, 25, 1, 30)
        assert quiet_end(settings, _utc(2026, 10, 25, 1, 30)) is None

    def test_a_start_in_the_skipped_hour(self):
        # 02:30 does not exist on 2026-03-29 in Berlin; at 01:30 UTC (03:30 CEST) the
        # window 02:30-04:00 is on, and ends at 04:00 CEST = 02:00 UTC.
        settings = _settings("02:30", "04:00", tz="Europe/Berlin")
        assert quiet_end(settings, _utc(2026, 3, 29, 0, 59)) is None
        assert quiet_end(settings, _utc(2026, 3, 29, 1, 30)) == _utc(2026, 3, 29, 2, 0)

    def test_an_unknown_stored_zone_counts_as_utc(self):
        settings = _settings(tz="Mars/Olympus")
        assert quiet_end(settings, _utc(2026, 11, 7, 22, 0)) == _utc(2026, 11, 8, 7, 0)


@pytest.fixture()
def without_system_zones():
    # The server image's Debian tzdata lacks the backward links (Asia/Calcutta, US/Eastern)
    # that Intl may report; the tzdata package carries them. An empty TZPATH leaves only it.
    zoneinfo.reset_tzpath(to=[])
    _ZONES.cache_clear()
    zoneinfo.ZoneInfo.clear_cache()
    try:
        yield
    finally:
        zoneinfo.reset_tzpath()
        _ZONES.cache_clear()
        zoneinfo.ZoneInfo.clear_cache()


@pytest.mark.parametrize("name", ["Asia/Calcutta", "Europe/Kiev", "US/Eastern", "Europe/Berlin"])
def test_zone_names_do_not_depend_on_the_system_database(without_system_zones, name):
    assert NotificationPrefsUpdate(subscriptions=[], timezone=name).timezone == name
    assert str(zoneinfo.ZoneInfo(name)) == name


def test_a_legacy_name_counts_like_its_target(without_system_zones):
    # 22:00 Asia/Calcutta (UTC+5:30) = 16:30 UTC, as in test_a_zone_without_dst.
    assert quiet_end(_settings(tz="Asia/Calcutta"), _utc(2026, 7, 1, 16, 30)) == _utc(
        2026, 7, 2, 1, 30
    )


class TestDigestTime:
    def test_daily_at_eight_in_the_zone(self):
        settings = _settings(tz="Europe/Berlin")
        # 08:00 Berlin in winter = 07:00 UTC; strictly after `after`.
        assert next_digest_at(settings, _utc(2026, 11, 7, 6, 0)) == _utc(2026, 11, 7, 7, 0)
        assert next_digest_at(settings, _utc(2026, 11, 7, 7, 0)) == _utc(2026, 11, 8, 7, 0)
        # In summer = 06:00 UTC.
        assert next_digest_at(settings, _utc(2026, 7, 1, 0, 0)) == _utc(2026, 7, 1, 6, 0)

    def test_weekly_on_monday(self):
        settings = _settings(digest="weekly")
        # 2026-11-07 is a Saturday; the next Monday is 2026-11-09.
        assert next_digest_at(settings, _utc(2026, 11, 7, 12, 0)) == _utc(2026, 11, 9, 8, 0)
        assert next_digest_at(settings, _utc(2026, 11, 9, 7, 59)) == _utc(2026, 11, 9, 8, 0)
        assert next_digest_at(settings, _utc(2026, 11, 9, 8, 0)) == _utc(2026, 11, 16, 8, 0)

    def test_across_the_dst_change(self):
        settings = _settings(tz="Europe/Berlin")
        # Saturday 08:00 CET = 07:00 UTC, Sunday after the spring change 08:00 CEST = 06:00.
        assert next_digest_at(settings, _utc(2026, 3, 28, 7, 0)) == _utc(2026, 3, 29, 6, 0)


# --- migration ---------------------------------------------------------------------


@pytest.fixture()
def before_clock(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_clock_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    url = admin_url.set(database=dbname).render_as_string(hide_password=False)
    # env.py reads app.core.config.DATABASE_URL at execution time — patch the attribute.
    monkeypatch.setattr(app_config, "DATABASE_URL", url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    engine = create_engine(url)
    try:
        command.upgrade(cfg, PREVIOUS)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, username, hashed_password, is_admin)"
                    " VALUES (1, 'alice', 'x', true)"
                )
            )
            conn.execute(
                text("INSERT INTO notification_settings (user_id, matrix) VALUES (1, '{}')")
            )
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            )
        }


def test_upgrade_keeps_everything_off(before_clock):
    cfg, engine = before_clock

    command.upgrade(cfg, REVISION)

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT timezone, quiet_enabled, quiet_start, quiet_end, quiet_critical,"
                " escalation_enabled, escalation_minutes, escalation_channel, digest,"
                " digest_last_at, sound_critical FROM notification_settings"
            )
        ).one()
    assert tuple(row) == (None, False, "22:00", "07:00", True, False, 10, None, "off", None, False)
    assert "escalated_at" in _columns(engine, "notification")
    assert "critical_since" in _columns(engine, "notification_incident")


def test_downgrade_hands_digest_entries_back_to_the_drain(before_clock):
    cfg, engine = before_clock
    command.upgrade(cfg, REVISION)
    with engine.begin() as conn:
        nid = conn.execute(
            text(
                "INSERT INTO notification (user_id, severity, category, event_type, title)"
                " VALUES (1, 'info', 'monitoring', 'x', 't') RETURNING id"
            )
        ).scalar_one()
        for status in ("digest", "sent"):
            conn.execute(
                text(
                    "INSERT INTO notification_outbox (notification_id, user_id, channel,"
                    " address, status, attempts) VALUES (:n, 1, 'email', 'a@example.org', :s, 0)"
                ),
                {"n": nid, "s": status},
            )

    command.downgrade(cfg, PREVIOUS)

    with engine.connect() as conn:
        statuses = sorted(
            r[0] for r in conn.execute(text("SELECT status FROM notification_outbox"))
        )
    assert statuses == ["pending", "sent"]
    assert "quiet_enabled" not in _columns(engine, "notification_settings")
    assert "escalated_at" not in _columns(engine, "notification")
    assert "critical_since" not in _columns(engine, "notification_incident")
