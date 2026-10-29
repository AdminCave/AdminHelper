# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One Postgres role per service (app.db_roles). The SQL is checked without a database; the
roles themselves against a throwaway postgres:17-alpine the test starts, because the
developers' test database may not create roles and every worktree shares its cluster."""

import shutil
import subprocess
import time
import uuid

import psycopg
import pytest
from psycopg import errors, sql

from app import db_roles

PG_IMAGE = "postgres:17-alpine"
SUPERUSER, SUPERPASS = "adminhelper", "super-pw"
PASSWORDS = {
    "SERVER_DB_PASSWORD": "server-pw",
    "SCHEDULER_DB_PASSWORD": "scheduler-pw",
    "MONITOR_DB_PASSWORD": "monitor-pw",
    "CA_DB_PASSWORD": "ca-pw",
}


def _text(stmt) -> str:
    return stmt.as_string(None)


# --- the SQL, without a database ---------------------------------------------------------


def test_role_statement_gives_no_reaching_attributes_and_quotes_both_parts():
    text = _text(db_roles.role_statement('we"ird', "SCRAM-SHA-256$x'y", exists=False))
    assert text.startswith(
        'CREATE ROLE "we""ird" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION '
        "NOBYPASSRLS"
    )
    assert text.endswith("PASSWORD 'SCRAM-SHA-256$x''y'")
    assert _text(db_roles.role_statement("r", "v", exists=True)).startswith('ALTER ROLE "r"')


def test_owner_statements_put_sequences_last_and_skip_owned_objects():
    stmts = [
        _text(s)
        for s in db_roles.owner_statements(
            [
                ("S", "seq", "adminhelper"),
                ("r", "users", "adminhelper"),
                ("v", "done", "ah_server"),
            ],
            "ah_server",
        )
    ]
    assert stmts == [
        'ALTER TABLE public."users" OWNER TO "ah_server"',
        'ALTER SEQUENCE public."seq" OWNER TO "ah_server"',
    ]


def test_ca_grants_follow_what_the_ca_issuer_does_per_table():
    stmts = [
        _text(s)
        for s in db_roles.ca_grant_statements(
            ["device_lines", "revoked_identities", "users"], ["s1"]
        )
    ]
    assert stmts == [
        'GRANT SELECT, INSERT, UPDATE ON public."device_lines" TO "ah_ca"',
        'GRANT SELECT ON public."revoked_identities" TO "ah_ca"',
        'GRANT USAGE, SELECT ON SEQUENCE public."s1" TO "ah_ca"',
    ]


# --- the roles, against a cluster of the test's own ---------------------------------------


@pytest.fixture(scope="module")
def cluster():
    if shutil.which("docker") is None:
        pytest.skip("docker is not available")
    name = f"ah-db-roles-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", f"POSTGRES_USER={SUPERUSER}", "-e", f"POSTGRES_PASSWORD={SUPERPASS}",
            "-e", "POSTGRES_DB=adminhelper",
            "-p", "127.0.0.1::5432", PG_IMAGE,
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        port = (
            subprocess.run(
                ["docker", "port", name, "5432"], check=True, capture_output=True, text=True
            )
            .stdout.strip()
            .rsplit(":", 1)[1]
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS), connect_timeout=2).close()
                break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        yield port
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _dsn(port: str, user: str, password: str, db: str = "adminhelper") -> str:
    return f"host=127.0.0.1 port={port} dbname={db} user={user} password={password}"


@pytest.fixture()
def as_superuser(cluster, monkeypatch):
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", cluster)
    monkeypatch.setenv("PGUSER", SUPERUSER)
    monkeypatch.setenv("PGPASSWORD", SUPERPASS)
    for var, value in PASSWORDS.items():
        monkeypatch.setenv(var, value)
    return cluster


def _seed_an_existing_install(port: str) -> None:
    # What a release before this one left: every object created by the superuser.
    with psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS), autocommit=True) as conn:
        conn.execute(
            "DROP TABLE IF EXISTS users, enrollment_tokens, revoked_identities, counters, later "
            "CASCADE"
        )
        conn.execute("DROP TYPE IF EXISTS hook_kind")
        conn.execute("CREATE TYPE hook_kind AS ENUM ('webhook', 'event')")
        conn.execute("CREATE TABLE users (id serial PRIMARY KEY, username text, kind hook_kind)")
        conn.execute("INSERT INTO users (username) VALUES ('admin')")
        conn.execute("CREATE TABLE enrollment_tokens (id text PRIMARY KEY, used_at timestamp)")
        conn.execute("CREATE TABLE revoked_identities (id text PRIMARY KEY, scope text)")
        conn.execute("INSERT INTO revoked_identities VALUES ('r1', 'agent')")
        conn.execute("CREATE TABLE counters (id bigint GENERATED ALWAYS AS IDENTITY, n int)")


def _owners(port: str, db: str = "adminhelper") -> set[str]:
    with psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS, db)) as conn:
        rows = conn.execute(
            """
            SELECT pg_get_userbyid(relowner) FROM pg_class
            WHERE relnamespace = 'public'::regnamespace
            UNION SELECT pg_get_userbyid(typowner) FROM pg_type
            WHERE typnamespace = 'public'::regnamespace AND typtype IN ('e', 'd')
            """
        ).fetchall()
    return {r[0] for r in rows}


def _connect_as(port: str, name: str, db: str = "adminhelper") -> psycopg.Connection:
    pw = PASSWORDS[db_roles.ROLES[name][1]]
    return psycopg.connect(_dsn(port, db_roles.role(name), pw, db), autocommit=True)


def test_setup_hands_an_existing_install_to_the_service_roles(as_superuser):
    port = as_superuser
    _seed_an_existing_install(port)

    db_roles.setup()
    db_roles.setup()  # idempotent: a second start changes nothing and does not fail

    assert _owners(port) == {"ah_server"}
    with psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS)) as conn:
        flags = conn.execute(
            "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles "
            "WHERE rolname IN ('ah_server', 'ah_scheduler', 'ah_monitor', 'ah_ca')"
        ).fetchall()
    assert sorted(flags) == [
        (name, False, False, False) for name in ("ah_ca", "ah_monitor", "ah_scheduler", "ah_server")
    ]
    with _connect_as(port, "server") as conn:
        assert conn.execute("SELECT username FROM users").fetchone() == ("admin",)
        conn.execute("INSERT INTO counters (n) VALUES (1)")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS note text")


def test_the_ca_issuer_reaches_only_its_tables(as_superuser):
    port = as_superuser
    _seed_an_existing_install(port)
    db_roles.setup()
    dsn = _dsn(port, "ah_server", PASSWORDS["SERVER_DB_PASSWORD"])
    db_roles.grant_ca(dsn)

    with psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS), autocommit=True) as conn:
        conn.execute("INSERT INTO enrollment_tokens (id) VALUES ('t1')")
    with _connect_as(port, "ca") as conn:
        conn.execute("UPDATE enrollment_tokens SET used_at = now() WHERE id = 't1'")
        assert conn.execute("SELECT scope FROM revoked_identities").fetchone() == ("agent",)
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("UPDATE revoked_identities SET scope = 'none'")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("INSERT INTO enrollment_tokens (id) VALUES ('t2')")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM users")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM enrollment_tokens")
    for db in (db_roles.MONITOR_DB, "postgres"):
        with pytest.raises(psycopg.OperationalError):
            _connect_as(port, "ca", db)


def test_monitoring_owns_its_database_and_nothing_else(as_superuser):
    port = as_superuser
    db_roles.setup()

    with _connect_as(port, "monitor", db_roles.MONITOR_DB) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS checks (id int)")
    assert _owners(port, db_roles.MONITOR_DB) == {"ah_monitor"}
    with pytest.raises(psycopg.OperationalError):
        _connect_as(port, "monitor")


def test_the_scheduler_writes_but_does_not_change_the_schema(as_superuser):
    port = as_superuser
    _seed_an_existing_install(port)
    db_roles.setup()
    with _connect_as(port, "server") as conn:
        # A table a later migration adds: the default privileges reach it.
        conn.execute("CREATE TABLE later (id serial PRIMARY KEY, v int)")

    with _connect_as(port, "scheduler") as conn:
        conn.execute("INSERT INTO later (v) VALUES (1)")
        conn.execute("UPDATE users SET username = username")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE mine (id int)")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("DROP TABLE later")
    with _connect_as(port, "server") as conn:
        conn.execute(sql.SQL("DROP TABLE later"))


def test_a_service_role_cannot_turn_the_next_setup_into_its_own(as_superuser):
    # The databases stay the superuser's, so no service role can attach a search_path to
    # one; and should one carry such a setting anyway (here set by the superuser, as an
    # owner could have before), setup still reads the real catalog, not a look-alike that
    # runs with the rights of the session.
    port = as_superuser
    _seed_an_existing_install(port)
    db_roles.setup()
    with _connect_as(port, "server") as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("ALTER DATABASE adminhelper SET search_path = public, pg_catalog")
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION public.escalate() RETURNS SETOF pg_catalog.pg_class
            LANGUAGE plpgsql AS $$
            BEGIN
                EXECUTE 'ALTER ROLE ah_server SUPERUSER';
                RETURN QUERY SELECT * FROM pg_catalog.pg_class;
            END $$
            """
        )
        conn.execute("CREATE OR REPLACE VIEW public.pg_class AS SELECT * FROM public.escalate()")
    with psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS), autocommit=True) as conn:
        conn.execute("ALTER DATABASE adminhelper SET search_path = public, pg_catalog")
    try:
        db_roles.setup()
        with psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS)) as conn:
            owner = conn.execute(
                "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database "
                "WHERE datname = 'adminhelper'"
            ).fetchone()
            superuser = conn.execute(
                "SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = 'ah_server'"
            ).fetchone()
        assert owner == (SUPERUSER,)
        assert superuser == (False,)
    finally:
        with psycopg.connect(_dsn(port, SUPERUSER, SUPERPASS), autocommit=True) as conn:
            conn.execute("ALTER DATABASE adminhelper RESET search_path")
            conn.execute("DROP VIEW IF EXISTS public.pg_class")
            conn.execute("DROP FUNCTION IF EXISTS public.escalate()")
            conn.execute("ALTER ROLE ah_server NOSUPERUSER")


def test_setup_stops_before_any_change_without_every_password(as_superuser, monkeypatch):
    monkeypatch.delenv("CA_DB_PASSWORD")
    with pytest.raises(SystemExit, match="CA_DB_PASSWORD"):
        db_roles.setup()


def test_a_failed_setup_names_no_password():
    # libpq quotes parts of the conninfo in its errors; the command prints the type only.
    # A password of its own as the probe, checked without printing the values.
    import os
    import secrets
    import sys

    sentinel = secrets.token_hex(16)
    env = {
        **os.environ,
        "PGHOST": "127.0.0.1",
        "PGPORT": "1",
        "PGUSER": SUPERUSER,
        "PGPASSWORD": sentinel,
        **{var: sentinel for var in PASSWORDS},
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.db_roles", "setup"],
        env=env,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    leaked = sentinel in result.stdout + result.stderr
    assert not leaked, "the output of the failed setup names a password"
    assert result.returncode == 1, result.stderr
    assert "OperationalError" in result.stderr
