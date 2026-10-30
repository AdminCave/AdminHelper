# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DB-backed token store against sqlite: atomic one-time consume + revocation."""

import datetime
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app import db
from app.tokens import CertRecord, EnrollmentGrant, RenewalRefused


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db.metadata.create_all(eng)
    return eng


def _mint(engine, raw_token, subject_id, scope, *, browser=False, ttl_minutes=15):
    expires = datetime.datetime.now(datetime.timezone.utc).replace(
        tzinfo=None
    ) + datetime.timedelta(minutes=ttl_minutes)
    with engine.begin() as conn:
        conn.execute(
            db.enrollment_tokens.insert().values(
                id=str(uuid.uuid4()),
                hashed_token=db._hash(raw_token),
                subject_id=subject_id,
                scope=scope,
                browser=browser,
                expires_at=expires,
            )
        )


def test_consume_valid_token_once(engine):
    _mint(engine, "raw-1", "agent-01", "tunnel", browser=False)
    store = db.DbTokenStore(engine)
    grant = store.consume("raw-1")
    assert grant == EnrollmentGrant(subject_id="agent-01", scope="tunnel", browser=False)
    # one-time: second consume yields nothing
    assert store.consume("raw-1") is None


def test_consume_unknown_token(engine):
    assert db.DbTokenStore(engine).consume("nope") is None


def test_consume_expired_token(engine):
    _mint(engine, "old", "a", "access", ttl_minutes=-5)  # already expired
    assert db.DbTokenStore(engine).consume("old") is None


def test_browser_flag_roundtrips(engine):
    _mint(engine, "b", "admin", "access", browser=True)
    grant = db.DbTokenStore(engine).consume("b")
    assert grant.browser is True


def test_is_active_until_revoked(engine):
    store = db.DbTokenStore(engine)
    assert store.is_active("agent-09", "tunnel") is True
    revoked_at = datetime.datetime(2026, 10, 1, 12, 0, 0)
    with engine.begin() as conn:
        conn.execute(
            db.revoked_identities.insert().values(
                id=str(uuid.uuid4()), subject_id="agent-09", scope="tunnel", revoked_at=revoked_at
            )
        )
    # The revocation is a point in time: certificates up to it are out, later ones are in.
    hour = datetime.timedelta(hours=1)
    assert store.is_active("agent-09", "tunnel", revoked_at - hour) is False
    assert store.is_active("agent-09", "tunnel", revoked_at) is False
    assert store.is_active("agent-09", "tunnel", revoked_at + hour) is True
    assert store.is_active("agent-09", "tunnel") is False  # without notBefore: revoked
    # a different identity stays active
    assert store.is_active("agent-09", "access") is True


def test_make_engine_forces_psycopg_driver():
    # make_engine rewrites legacy driver URLs to psycopg3 (the bundled one), db.py:64-70 (6.24).
    for url in ("postgresql://u:p@h/db", "postgresql+psycopg2://u:p@h/db"):
        eng = db.make_engine(url)
        assert eng.url.drivername == "postgresql+psycopg", url
        eng.dispose()
    # An already-psycopg URL is left as-is.
    eng = db.make_engine("postgresql+psycopg://u:p@h/db")
    assert eng.url.drivername == "postgresql+psycopg"
    eng.dispose()


@pytest.fixture()
def pg_engine():
    url = os.environ.get("AH_TEST_DB")
    if not url or "postgres" not in url:
        pytest.skip("kein Postgres (AH_TEST_DB) — der TOCTOU-Test braucht echte Nebenläufigkeit")
    eng = db.make_engine(url)
    # The tables belong to the server; the shared test DB may lack them, so they come
    # from the issuer's own view here.
    db.metadata.create_all(eng)
    yield eng
    db.metadata.drop_all(eng)
    eng.dispose()


def test_concurrent_consume_only_one_wins(pg_engine):
    # The TOCTOU claim (db.py:86-87): N concurrent consume() of the SAME token, exactly one wins —
    # Postgres UPDATE..RETURNING with `used_at IS NULL` is atomic. sqlite (StaticPool, one
    # connection) cannot demonstrate this, so it must run against real Postgres (6.24).
    _mint(pg_engine, "race", "agent-01", "tunnel")
    store = db.DbTokenStore(pg_engine)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: store.consume("race"), range(8)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"erwartet genau 1 Gewinner, {len(winners)}"
    assert winners[0].subject_id == "agent-01"


def _self_signed(cn: str, scope: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, scope),
        ]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=90))
        .sign(key, hashes.SHA256())
    )


def test_a_line_revoked_during_a_renewal_waits_and_covers_the_successor(pg_engine):
    # R-0224: the renewal locks its line. A revocation of that line waits for it, and
    # because the successor stays on the line, the revocation covers the successor too:
    # no certificate leaves the line unrevoked. sqlite has no row locks; Postgres does.
    store = db.DbTokenStore(pg_engine)
    _mint(pg_engine, "race-renew", "agent-11", "tunnel")
    first = _self_signed("agent-11", "tunnel")
    store.enroll("race-renew", lambda grant: (first, {}))
    current = CertRecord.of(first)
    line_id = store.line_of(current.fingerprint).line_id

    signing, release = threading.Event(), threading.Event()
    successor = _self_signed("agent-11", "tunnel")

    def sign(_kind):
        signing.set()  # the line is locked by now
        release.wait(10)
        return successor, {}

    def revoke_line():
        with pg_engine.begin() as conn:
            conn.execute(
                db.device_lines.update()
                .where(db.device_lines.c.id == line_id)
                .values(revoked_at=db._now_naive(), revoked_reason="admin")
            )

    with ThreadPoolExecutor(max_workers=2) as ex:
        renewal = ex.submit(store.renew, current, "agent-11", "tunnel", "agent", sign)
        assert signing.wait(10)
        revocation = ex.submit(revoke_line)
        time.sleep(0.5)
        assert not revocation.done(), "the revocation must wait for the locked line"
        release.set()
        renewal.result(10)
        revocation.result(10)

    assert store.line_of(CertRecord.of(successor).fingerprint).revoked_reason == "admin"
    # Once revoked, the line renews nothing more.
    with pytest.raises(RenewalRefused):
        store.renew(
            CertRecord.of(successor), "agent-11", "tunnel", "agent", lambda _kind: (successor, {})
        )


def test_a_deprovisioning_while_signing_refuses_the_renewal(pg_engine):
    # The line lock does not hold off a deprovisioning of the identity; the renewal looks
    # once more after signing, so a revocation committed meanwhile still refuses it.
    store = db.DbTokenStore(pg_engine)
    _mint(pg_engine, "race-deprov", "agent-13", "tunnel")
    first = _self_signed("agent-13", "tunnel")
    store.enroll("race-deprov", lambda grant: (first, {}))
    current = CertRecord.of(first)
    successor = _self_signed("agent-13", "tunnel")

    def sign(_kind):
        with pg_engine.begin() as conn:
            conn.execute(
                db.revoked_identities.insert().values(
                    id=str(uuid.uuid4()),
                    subject_id="agent-13",
                    scope="tunnel",
                    revoked_at=current.not_before,
                )
            )
        return successor, {}

    with pytest.raises(RenewalRefused):
        store.renew(current, "agent-13", "tunnel", "agent", sign)
    assert store.line_of(CertRecord.of(successor).fingerprint) is None, "nothing was recorded"


# --- R-0292: renewing and revoking one identity go one after the other ------------------


def _transition_open(engine) -> None:
    # The register was installed a day from now: an unrecorded certificate is taken over.
    with engine.begin() as conn:
        conn.execute(
            db.certificate_register_state.insert().values(
                id=1, installed_at=db._now_naive() + datetime.timedelta(days=1)
            )
        )


def _revoke(conn, subject_id: str, scope: str) -> None:
    """What the server's revoke_identity does, from the issuer's view of the tables."""
    conn.execute(text(db.IDENTITY_LOCK_SQL), {"subject_id": subject_id, "scope": scope})
    now = db._now_naive()
    conn.execute(
        db.revoked_identities.insert().values(
            id=str(uuid.uuid4()), subject_id=subject_id, scope=scope, revoked_at=now
        )
    )
    conn.execute(
        db.device_lines.update()
        .where(
            db.device_lines.c.subject_id == subject_id,
            db.device_lines.c.scope == scope,
            db.device_lines.c.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoked_reason="admin")
    )


def _blocked(engine, pid: int, timeout: float = 10.0) -> bool:
    # A fresh connection per look: pg_stat_activity keeps its snapshot for a transaction.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as probe:
            waiting = probe.execute(
                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            ).scalar()
        if waiting:
            return True
        time.sleep(0.05)
    return False


def _waits_for(engine, blocker_pid: int, timeout: float = 10.0) -> bool:
    """Whether some session waits for a lock that ``blocker_pid`` holds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as probe:
            waiting = probe.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": blocker_pid},
            ).scalar()
        if waiting:
            return True
        time.sleep(0.05)
    return False


def test_a_renewal_that_takes_over_waits_for_a_revocation_and_is_refused(pg_engine):
    _transition_open(pg_engine)
    store = db.DbTokenStore(pg_engine)
    current, successor = _self_signed("agent-21", "tunnel"), _self_signed("agent-21", "tunnel")
    revocation = pg_engine.connect()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        tx = revocation.begin()
        revocation_pid = revocation.execute(text("SELECT pg_backend_pid()")).scalar()
        _revoke(revocation, "agent-21", "tunnel")
        renewing = ex.submit(
            store.renew,
            CertRecord.of(current),
            "agent-21",
            "tunnel",
            "agent",
            lambda _kind: (successor, {}),
        )
        assert _waits_for(pg_engine, revocation_pid), "the renewal must wait for the revocation"
        assert not renewing.done()
        tx.commit()
        with pytest.raises(RenewalRefused):
            renewing.result(10)
    finally:
        revocation.close()
        ex.shutdown(wait=True)
    assert store.line_of(CertRecord.of(successor).fingerprint) is None, "nothing was recorded"


def test_a_revocation_waits_for_a_renewal_that_takes_over_and_covers_its_line(pg_engine):
    _transition_open(pg_engine)
    store = db.DbTokenStore(pg_engine)
    current, successor = _self_signed("agent-22", "tunnel"), _self_signed("agent-22", "tunnel")
    signing, release = threading.Event(), threading.Event()

    def sign(_kind):
        signing.set()  # the new line exists, not yet committed
        release.wait(10)
        return successor, {}

    revocation = pg_engine.connect()
    revocation_pid = revocation.execute(text("SELECT pg_backend_pid()")).scalar()
    revocation.commit()

    def revoke():
        with revocation.begin():
            _revoke(revocation, "agent-22", "tunnel")

    ex = ThreadPoolExecutor(max_workers=2)
    try:
        renewing = ex.submit(
            store.renew, CertRecord.of(current), "agent-22", "tunnel", "agent", sign
        )
        assert signing.wait(10)
        revoking = ex.submit(revoke)
        assert _blocked(pg_engine, revocation_pid), "the revocation must wait for the renewal"
        assert not revoking.done()
        release.set()
        renewing.result(10)
        revoking.result(10)
    finally:
        release.set()
        ex.shutdown(wait=True)
        revocation.close()
    assert store.line_of(CertRecord.of(successor).fingerprint).revoked_reason == "admin"


# --- R-0306: a token minted before the revocation of its identity enrolls nothing ------


def _mint_at(engine, raw_token: str, subject_id: str, scope: str, minted_at) -> None:
    _mint(engine, raw_token, subject_id, scope)
    with engine.begin() as conn:
        conn.execute(
            db.enrollment_tokens.update()
            .where(db.enrollment_tokens.c.hashed_token == db._hash(raw_token))
            .values(created_at=minted_at)
        )


def test_a_token_minted_up_to_the_revocation_enrolls_nothing(engine):
    now = db._now_naive()
    revoked_at = now - datetime.timedelta(minutes=1)
    with engine.begin() as conn:
        conn.execute(
            db.revoked_identities.insert().values(
                id=str(uuid.uuid4()), subject_id="alice", scope="access", revoked_at=revoked_at
            )
        )
    _mint_at(engine, "before", "alice", "access", revoked_at - datetime.timedelta(minutes=1))
    _mint_at(engine, "at", "alice", "access", revoked_at)
    _mint_at(engine, "after", "alice", "access", now)
    store = db.DbTokenStore(engine)
    signed = []

    def sign(grant):
        signed.append(grant)
        return _self_signed("alice", "access"), {"cert": "x"}

    assert store.enroll("before", sign) is None
    assert store.enroll("at", sign) is None
    assert signed == []
    assert store.consume("before") is None, "the refused token is spent"
    leaf = _self_signed("alice", "access")
    assert store.enroll("after", lambda grant: (leaf, {"cert": "y"})) == {"cert": "y"}
    assert store.line_of(CertRecord.of(leaf).fingerprint).revoked_reason is None


def test_an_enrollment_waits_for_a_revocation_and_enrolls_nothing(pg_engine):
    _mint_at(
        pg_engine, "racing", "agent-31", "tunnel", db._now_naive() - datetime.timedelta(minutes=1)
    )
    store = db.DbTokenStore(pg_engine)
    signed = []

    def sign(grant):
        signed.append(grant)
        return _self_signed("agent-31", "tunnel"), {"cert": "x"}

    revocation = pg_engine.connect()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        tx = revocation.begin()
        revocation_pid = revocation.execute(text("SELECT pg_backend_pid()")).scalar()
        _revoke(revocation, "agent-31", "tunnel")
        enrolling = ex.submit(store.enroll, "racing", sign)
        assert _waits_for(pg_engine, revocation_pid), "the enrollment must wait for the revocation"
        assert not enrolling.done()
        tx.commit()
        assert enrolling.result(10) is None
    finally:
        revocation.close()
        ex.shutdown(wait=True)
    assert signed == [], "nothing was signed"
