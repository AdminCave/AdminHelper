# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later


def test_spa_fallback_returns_404_without_frontend_build(test_client, monkeypatch, tmp_path):
    # 2.125: with no index.html present (API-only deployment or an un-built
    # frontend), the SPA fallback must return a clean 404 — not a 500 from
    # FileResponse trying to send a missing file.
    monkeypatch.setattr("app.main.static_dir", tmp_path)
    res = test_client.get("/some-spa-route")
    assert res.status_code == 404


def test_spa_fallback_api_path_still_404(test_client):
    # An /api/ path that no router handled must stay a 404 (not fall through to
    # index.html), independent of the frontend build.
    res = test_client.get("/api/definitely-not-a-route")
    assert res.status_code == 404
