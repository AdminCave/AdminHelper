# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One Postgres role per service instead of the image's bootstrap superuser.

    python -m app.db_roles setup     # db-init service: as the superuser (libpq PG* variables)
    python -m app.db_roles grant-ca  # server entrypoint after `alembic upgrade head`, as ah_server

`setup` is idempotent and runs on every start: it creates the roles or resets their
passwords, creates the monitoring database if it is missing, hands the `public` schema of
both databases and every object in it to its service's role (also on an install whose tables
the superuser created) and limits CONNECT. The databases themselves stay the superuser's: an
owner could attach settings to its database (`ALTER DATABASE … SET search_path`) that every
later superuser session, this one included, would run under. `grant-ca` gives the ca-issuer
exactly what it does on its tables; the server runs it as their owner after its migrations,
so a migration that recreates one of them does not leave the ca-issuer without rights until
the next setup.
"""

import os
import sys

import psycopg
from psycopg import sql

SERVER_DB = os.environ.get("ADMIN_DB", "adminhelper")
MONITOR_DB = os.environ.get("MONITOR_DB", "adminhelper_monitor")

# Role name (overridable: tests share one cluster) and the variable holding its password.
ROLES = {
    "server": (os.environ.get("SERVER_DB_ROLE", "ah_server"), "SERVER_DB_PASSWORD"),
    "scheduler": (os.environ.get("SCHEDULER_DB_ROLE", "ah_scheduler"), "SCHEDULER_DB_PASSWORD"),
    "monitor": (os.environ.get("MONITOR_DB_ROLE", "ah_monitor"), "MONITOR_DB_PASSWORD"),
    "ca": (os.environ.get("CA_DB_ROLE", "ah_ca"), "CA_DB_PASSWORD"),
}

# What the ca-issuer does on the tables of the server's database it works on
# (apps/ca-issuer/app/db.py): it reads revocations and the register's install time, it never
# changes them; it deletes nothing and changes no schema.
CA_TABLE_PRIVILEGES = {
    "enrollment_tokens": "SELECT, UPDATE",
    "device_lines": "SELECT, INSERT, UPDATE",
    "issued_certificates": "SELECT, INSERT",
    "revoked_identities": "SELECT",
    "certificate_register_state": "SELECT",
}
CA_TABLES = tuple(CA_TABLE_PRIVILEGES)
SCHEDULER_TABLE_PRIVILEGES = sql.SQL("SELECT, INSERT, UPDATE, DELETE")

# Relations in `public` by pg_class.relkind; sequences come last: one a table owns follows the
# table's owner and refuses an ALTER of its own.
_RELATION_KINDS = {
    "r": "TABLE",
    "p": "TABLE",
    "f": "FOREIGN TABLE",
    "v": "VIEW",
    "m": "MATERIALIZED VIEW",
    "S": "SEQUENCE",
}

# Every superuser session of setup resolves names in pg_catalog only: the service roles own
# the `public` schemas, and an object there named like a catalog would otherwise run with
# superuser rights. Client options win over settings stored for a role or database.
_SUPERUSER_OPTIONS = "-c search_path=pg_catalog"


def role(name: str) -> str:
    return ROLES[name][0]


def _passwords() -> dict[str, str]:
    # All four read before anything changes: a missing one stops setup before the first role.
    missing = [var for _, var in ROLES.values() if not os.environ.get(var)]
    if missing:
        raise SystemExit(f"db_roles: not set: {', '.join(missing)}")
    return {name: os.environ[var] for name, (_, var) in ROLES.items()}


def role_statement(role_name: str, verifier: str, exists: bool) -> sql.Composed:
    """CREATE or ALTER a login role without any of the attributes that reach past its own
    objects. `verifier` is the SCRAM verifier, never the password: a failed statement lands
    in the server log with its text."""
    verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
    return sql.SQL(
        "{} {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
    ).format(verb, sql.Identifier(role_name), sql.Literal(verifier))


def _verifier(conn: psycopg.Connection, role_name: str, password: str) -> str:
    return conn.pgconn.encrypt_password(
        password.encode(), role_name.encode(), b"scram-sha-256"
    ).decode()


def owner_statements(objects: list[tuple[str, str, str]], owner: str) -> list[sql.Composed]:
    """ALTER … OWNER TO for (relkind, name, current owner) in `public`, sequences last, those
    already owned by `owner` skipped."""
    ordered = sorted(objects, key=lambda o: o[0] == "S")
    return [
        sql.SQL("ALTER {} public.{} OWNER TO {}").format(
            sql.SQL(_RELATION_KINDS[kind]), sql.Identifier(name), sql.Identifier(owner)
        )
        for kind, name, current in ordered
        if current != owner
    ]


def _relations(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    kinds = list(_RELATION_KINDS)
    return conn.execute(
        """
        SELECT c.relkind::pg_catalog.text, c.relname, pg_catalog.pg_get_userbyid(c.relowner)
        FROM pg_catalog.pg_class c
        WHERE c.relnamespace = 'public'::pg_catalog.regnamespace
          AND c.relkind::pg_catalog.text = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend d
              WHERE d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass AND d.objid = c.oid
                AND d.deptype IN ('a', 'i') AND c.relkind = 'S'
          )
        """,
        (kinds,),
    ).fetchall()


def _types(conn: psycopg.Connection) -> list[tuple[str, str]]:
    # Enums and domains a migration created; a table's row type follows the table.
    return conn.execute(
        """
        SELECT t.typname, pg_catalog.pg_get_userbyid(t.typowner)
        FROM pg_catalog.pg_type t
        WHERE t.typnamespace = 'public'::pg_catalog.regnamespace AND t.typtype IN ('e', 'd')
        """
    ).fetchall()


def _hand_over(conn: psycopg.Connection, owner: str) -> None:
    conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(owner)))
    for stmt in owner_statements(_relations(conn), owner):
        conn.execute(stmt)
    for name, current in _types(conn):
        if current != owner:
            conn.execute(
                sql.SQL("ALTER TYPE public.{} OWNER TO {}").format(
                    sql.Identifier(name), sql.Identifier(owner)
                )
            )


def _connect_superuser(dbname: str) -> psycopg.Connection:
    # libpq takes host, port, user and password from the PG* variables.
    return psycopg.connect(dbname=dbname, autocommit=True, options=_SUPERUSER_OPTIONS)


def setup() -> None:
    passwords = _passwords()
    with _connect_superuser(SERVER_DB) as conn:
        for name in ROLES:
            exists = (
                conn.execute(
                    "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s", (role(name),)
                ).fetchone()
                is not None
            )
            verifier = _verifier(conn, role(name), passwords[name])
            conn.execute(role_statement(role(name), verifier, exists))
        if (
            conn.execute(
                "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (MONITOR_DB,)
            ).fetchone()
            is None
        ):
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(MONITOR_DB)))
        # The databases stay the superuser's (see the module doc), also where a former run
        # of this very module handed them to a service role.
        for db, guests in (
            (SERVER_DB, (role("server"), role("scheduler"), role("ca"))),
            (MONITOR_DB, (role("monitor"),)),
            ("postgres", ()),
        ):
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO CURRENT_USER").format(sql.Identifier(db))
            )
            conn.execute(
                sql.SQL("REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(db)
                )
            )
            for guest in guests:
                conn.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(db), sql.Identifier(guest)
                    )
                )

    with _connect_superuser(SERVER_DB) as conn:
        _hand_over(conn, role("server"))
        server, scheduler = sql.Identifier(role("server")), sql.Identifier(role("scheduler"))
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}").format(
                scheduler, sql.Identifier(role("ca"))
            )
        )
        conn.execute(
            sql.SQL("GRANT {} ON ALL TABLES IN SCHEMA public TO {}").format(
                SCHEDULER_TABLE_PRIVILEGES, scheduler
            )
        )
        conn.execute(
            sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                scheduler
            )
        )
        conn.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT {} ON TABLES TO {}"
            ).format(server, SCHEDULER_TABLE_PRIVILEGES, scheduler)
        )
        conn.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}"
            ).format(server, scheduler)
        )

    with _connect_superuser(MONITOR_DB) as conn:
        _hand_over(conn, role("monitor"))


def ca_grant_statements(existing: list[str], sequences: list[str]) -> list[sql.Composed]:
    ca = sql.Identifier(role("ca"))
    stmts = [
        sql.SQL("GRANT {} ON public.{} TO {}").format(
            sql.SQL(CA_TABLE_PRIVILEGES[t]), sql.Identifier(t), ca
        )
        for t in CA_TABLES
        if t in existing
    ]
    stmts += [
        sql.SQL("GRANT USAGE, SELECT ON SEQUENCE public.{} TO {}").format(sql.Identifier(s), ca)
        for s in sequences
    ]
    return stmts


def grant_ca(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        existing = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' AND tablename = ANY(%s)",
                (list(CA_TABLES),),
            ).fetchall()
        ]
        sequences = [
            r[0]
            for r in conn.execute(
                """
                SELECT s.relname FROM pg_catalog.pg_class s
                JOIN pg_catalog.pg_depend d
                  ON d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass AND d.objid = s.oid
                JOIN pg_catalog.pg_class t ON t.oid = d.refobjid
                WHERE s.relkind = 'S' AND t.relnamespace = 'public'::pg_catalog.regnamespace
                  AND t.relname = ANY(%s)
                """,
                (list(CA_TABLES),),
            ).fetchall()
        ]
        for stmt in ca_grant_statements(existing, sequences):
            conn.execute(stmt)


def _libpq_dsn(url: str) -> str:
    # DATABASE_URL carries SQLAlchemy's driver suffix; libpq wants the plain scheme.
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def main(argv: list[str]) -> int:
    try:
        if argv[1:] == ["setup"]:
            setup()
            print("[db_roles] roles, ownership and CONNECT in place")
            return 0
        if argv[1:] == ["grant-ca"]:
            grant_ca(_libpq_dsn(os.environ["DATABASE_URL"]))
            print("[db_roles] ca-issuer rights in place")
            return 0
    except psycopg.Error as exc:
        # The type only: libpq quotes parts of the conninfo, the password among them.
        print(f"[db_roles] failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("usage: python -m app.db_roles setup|grant-ca", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
