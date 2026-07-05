# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test setup for the ca-issuer. Config is read lazily at boot (lifespan calls
ensure_hierarchy with config.pki_dir()/root_passphrase()), so CA_DATA_DIR + the
root passphrase only need to be set before the app boots — done here once, up
front, so the PKI lands in a tmp dir rather than /app/data."""

import os
import tempfile

os.environ.setdefault("CA_DATA_DIR", tempfile.mkdtemp(prefix="ca-issuer-test-"))
os.environ.setdefault("CA_ROOT_PASSPHRASE", "test-passphrase-not-for-production")
# Tests run without a DATABASE_URL — opt into the in-memory token store (4.17).
os.environ.setdefault("CA_ALLOW_MEMORY_STORE", "1")
