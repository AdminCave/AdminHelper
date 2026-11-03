# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The snapshot of the infrastructure certificates (app/inventory.py, R-1022): what the
ca-issuer writes at start, and that a failure does not stop the start."""

import datetime
import logging

import pytest
from cryptography.hazmat.primitives import hashes
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

from app import db, inventory, main, pki
from app.storage import ensure_frps_cert, ensure_gateway_cert, ensure_hierarchy
from tests import renewal

_OLD = datetime.datetime(2026, 1, 1)


def _sqlite(create: bool = True):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    if create:
        db.metadata.create_all(eng)
    return eng


@pytest.fixture()
def pki_tree(tmp_path):
    pki_dir = tmp_path / "pki"
    intermediates = ensure_hierarchy(pki_dir, b"pw")
    gateway_dir = tmp_path / "gateway"
    ensure_gateway_cert(gateway_dir, intermediates["access"], "gw.example")
    frps_dir = tmp_path / "frps"
    ensure_frps_cert(frps_dir, intermediates["tunnel"], "frp.example")
    return pki_dir, gateway_dir, frps_dir


def _rows(engine) -> dict[str, dict]:
    with engine.connect() as conn:
        return {r.name: r._asdict() for r in conn.execute(select(db.infra_certificates)).all()}


def test_records_root_intermediates_and_server_certs(pki_tree):
    pki_dir, gateway_dir, frps_dir = pki_tree
    engine = _sqlite()

    inventory.record(engine, inventory.collect(pki_dir, gateway_dir, frps_dir))

    rows = _rows(engine)
    assert set(rows) == {
        "root",
        *(f"intermediate:{s}" for s in pki.SCOPES),
        "gateway",
        "frps",
    }
    root = pki.cert_from_pem((pki_dir / "root.crt").read_bytes())
    assert rows["root"]["fingerprint"] == root.fingerprint(hashes.SHA256()).hex()
    assert rows["root"]["subject"] == root.subject.rfc4514_string()
    assert rows["root"]["not_after"] == root.not_valid_after_utc.replace(tzinfo=None)
    assert rows["root"]["not_after"].tzinfo is None
    # The leaf of the gateway's fullchain, not the access intermediate behind it.
    assert "gw.example" in rows["gateway"]["subject"]
    assert rows["frps"]["fingerprint"] != rows["intermediate:tunnel"]["fingerprint"]


def test_a_server_cert_that_is_not_there_gets_no_row(pki_tree, tmp_path):
    pki_dir, gateway_dir, _ = pki_tree
    engine = _sqlite()

    certs = inventory.collect(pki_dir, gateway_dir, tmp_path / "no-frps")
    inventory.record(engine, certs)
    assert "frps" not in _rows(engine)

    inventory.record(engine, inventory.collect(pki_dir, None, None))
    assert {"gateway", "frps"}.isdisjoint(_rows(engine))


def test_a_new_start_replaces_the_old_snapshot(pki_tree):
    pki_dir, gateway_dir, frps_dir = pki_tree
    engine = _sqlite()
    with engine.begin() as conn:
        conn.execute(
            insert(db.infra_certificates),
            [
                {
                    "name": "intermediate:gone",
                    "subject": "CN=old",
                    "fingerprint": "00" * 32,
                    "not_before": _OLD,
                    "not_after": _OLD,
                    "recorded_at": _OLD,
                }
            ],
        )

    inventory.record(engine, inventory.collect(pki_dir, gateway_dir, frps_dir))

    rows = _rows(engine)
    assert "intermediate:gone" not in rows
    assert len(rows) == 1 + len(pki.SCOPES) + 2


def test_a_row_keeps_the_start_that_first_recorded_its_certificate(monkeypatch, pki_tree):
    # R-1021: rotate-root finish counts a device from the first start under the root on.
    pki_dir, gateway_dir, frps_dir = pki_tree
    engine = _sqlite()
    first = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
    later = first + datetime.timedelta(days=1)
    monkeypatch.setattr(pki, "_now", lambda: first)
    inventory.record(engine, inventory.collect(pki_dir, gateway_dir, frps_dir))

    monkeypatch.setattr(pki, "_now", lambda: later)
    certs = inventory.collect(pki_dir, gateway_dir, frps_dir)
    certs["gateway"] = certs["frps"]  # another certificate under the same name
    inventory.record(engine, certs)

    rows = _rows(engine)
    assert rows["root"]["recorded_at"] == first.replace(tzinfo=None)
    assert rows["intermediate:tunnel"]["recorded_at"] == first.replace(tzinfo=None)
    assert rows["gateway"]["recorded_at"] == later.replace(tzinfo=None)


def _fingerprint(cert) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


@pytest.mark.parametrize("phase", renewal.PHASES)
def test_records_the_roots_of_a_root_renewal(monkeypatch, tmp_path, phase):
    # R-1021: "root" is root.crt, the root that signs; beside it the staged new root, or
    # after the switch the old root and the cross certificate, until finish.
    pki_dir = tmp_path / "pki"
    r = renewal.renewed(monkeypatch, pki_dir, phase)
    engine = _sqlite()

    inventory.record(engine, inventory.collect(pki_dir, None, None))

    rows = _rows(engine)
    switched = phase in ("switched", "no-cross", "compromised", "expired")
    signing = r.old_root if phase in ("none", "staged") else r.new_root
    assert rows["root"]["fingerprint"] == _fingerprint(signing)
    expected = {"root:next": r.new_root} if phase == "staged" else {}
    if switched:
        expected["root:retired"] = r.old_root
        if r.cross is not None:
            expected["root:cross"] = r.cross
    assert {n: row["fingerprint"] for n, row in rows.items() if n.startswith("root:")} == {
        n: _fingerprint(c) for n, c in expected.items()
    }
    assert {n for n in rows if n.startswith("intermediate:")} == {
        f"intermediate:{s}" for s in pki.SCOPES
    }


def _configure(monkeypatch, tmp_path, pki_tree, url):
    pki_dir, gateway_dir, frps_dir = pki_tree
    assert pki_dir == tmp_path / "pki"
    monkeypatch.setenv("CA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CA_GATEWAY_CERT_DIR", str(gateway_dir))
    monkeypatch.setenv("CA_FRPS_CERT_DIR", str(frps_dir))
    monkeypatch.setenv("DATABASE_URL", url)


def test_record_inventory_writes_through_the_configured_db(monkeypatch, tmp_path, pki_tree):
    engine = _sqlite()
    _configure(monkeypatch, tmp_path, pki_tree, "postgresql://ca:pw@db.invalid/ah")
    monkeypatch.setattr(db, "make_engine", lambda url: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)

    main.record_inventory()

    assert len(_rows(engine)) == 1 + len(pki.SCOPES) + 2


def test_record_inventory_without_db_store_writes_nothing(monkeypatch, tmp_path, pki_tree):
    _configure(monkeypatch, tmp_path, pki_tree, "")

    def _no_engine(url):
        raise AssertionError("no engine without a DB store")

    monkeypatch.setattr(db, "make_engine", _no_engine)
    main.record_inventory()


def test_a_db_failure_is_logged_without_the_url_and_does_not_raise(
    monkeypatch, tmp_path, pki_tree, caplog
):
    # An engine without the table: the write fails like a DB without the migration.
    engine = _sqlite(create=False)
    _configure(monkeypatch, tmp_path, pki_tree, "postgresql://ca:s3cret-pw@db.invalid/ah")
    monkeypatch.setattr(db, "make_engine", lambda url: engine)

    with caplog.at_level(logging.WARNING):
        main.record_inventory()

    messages = [r.getMessage() for r in caplog.records]
    assert any("Certificate overview not written" in m for m in messages)
    assert all("s3cret-pw" not in m and "db.invalid" not in m for m in messages)
