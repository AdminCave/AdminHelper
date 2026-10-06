# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ansible playbook module — previously untested. Covers: admin-only authz, the
filename allowlist (a path-traversal boundary — the filename becomes a disk path
component), YAML validation on write, and the create → read-content → update →
delete roundtrip (content is persisted on disk under DATA_DIR/ansible/playbooks)."""

import pytest

from app.modules.ansible.schemas import PlaybookCreate

VALID = {"name": "Site", "filename": "site.yml", "content": "- hosts: all\n  tasks: []\n"}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestAnsibleAuthz:
    def test_nonadmin_cannot_list(self, test_client, db_session, normal_user):
        h = _login(test_client, "viewer", "viewerpass")
        assert test_client.get("/api/ansible/playbooks", headers=h).status_code == 403

    def test_nonadmin_cannot_create(self, test_client, db_session, normal_user):
        h = _login(test_client, "viewer", "viewerpass")
        assert test_client.post("/api/ansible/playbooks", json=VALID, headers=h).status_code == 403

    def test_unauthenticated_cannot_list(self, test_client, db_session):
        assert test_client.get("/api/ansible/playbooks").status_code == 401


class TestFilenameValidation:
    @pytest.mark.parametrize("fn", ["site.yml", "my-playbook.yaml", "deploy 1.yml"])
    def test_valid_filenames_accepted(self, fn):
        assert PlaybookCreate(name="x", filename=fn, content="[]").filename == fn

    @pytest.mark.parametrize(
        "fn",
        ["../etc/passwd.yml", "a/b.yml", r"evil\x.yml", "site.txt", "noext", "..", "site.yml.txt"],
    )
    def test_path_separators_and_bad_extensions_rejected(self, fn):
        with pytest.raises(ValueError):
            PlaybookCreate(name="x", filename=fn, content="[]")


class TestPlaybookCrud:
    def test_create_read_update_delete_roundtrip(self, test_client, db_session, admin_user):
        h = _login(test_client, "admin", "adminpass")

        created = test_client.post("/api/ansible/playbooks", json=VALID, headers=h)
        assert created.status_code == 201, created.text
        pid = created.json()["id"]

        listed = test_client.get("/api/ansible/playbooks", headers=h).json()
        assert any(p["id"] == pid for p in listed)

        # content is read back from disk
        content = test_client.get(f"/api/ansible/playbooks/{pid}/content", headers=h)
        assert content.status_code == 200
        assert content.json()["content"] == VALID["content"]

        upd = test_client.put(
            f"/api/ansible/playbooks/{pid}", json={"content": "- hosts: web\n"}, headers=h
        )
        assert upd.status_code == 200, upd.text
        reread = test_client.get(f"/api/ansible/playbooks/{pid}/content", headers=h)
        assert reread.json()["content"] == "- hosts: web\n"

        assert test_client.delete(f"/api/ansible/playbooks/{pid}", headers=h).status_code == 204
        assert test_client.get(f"/api/ansible/playbooks/{pid}", headers=h).status_code == 404

    def test_timestamps_are_rfc3339_utc(self, test_client, db_session, admin_user):
        # format: date-time promises an offset (R-0064): the API writes UTC with Z.
        h = _login(test_client, "admin", "adminpass")
        created = test_client.post("/api/ansible/playbooks", json=VALID, headers=h)
        assert created.status_code == 201, created.text
        assert created.json()["createdAt"].endswith("Z"), created.text
        pid = created.json()["id"]
        # A changed column sets updated_at (onupdate); a content-only PUT writes none.
        upd = test_client.put(f"/api/ansible/playbooks/{pid}", json={"name": "Renamed"}, headers=h)
        assert upd.status_code == 200, upd.text
        assert upd.json()["updatedAt"].endswith("Z"), upd.text
        assert test_client.delete(f"/api/ansible/playbooks/{pid}", headers=h).status_code == 204

    def test_invalid_yaml_rejected_before_write(self, test_client, db_session, admin_user):
        h = _login(test_client, "admin", "adminpass")
        bad = {"name": "x", "filename": "bad.yml", "content": "foo: [unclosed"}
        assert test_client.post("/api/ansible/playbooks", json=bad, headers=h).status_code == 422

    def test_path_traversal_filename_rejected_at_endpoint(
        self, test_client, db_session, admin_user
    ):
        h = _login(test_client, "admin", "adminpass")
        r = test_client.post(
            "/api/ansible/playbooks", json={**VALID, "filename": "../escape.yml"}, headers=h
        )
        assert r.status_code == 422, r.text
