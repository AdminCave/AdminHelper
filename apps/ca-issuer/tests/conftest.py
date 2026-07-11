# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test setup for the ca-issuer. Config is read lazily at boot (lifespan calls
ensure_hierarchy with config.pki_dir()/root_passphrase()), so CA_DATA_DIR + the
root passphrase only need to be set before the app boots — done here once, up
front, so the PKI lands in a tmp dir rather than /app/data."""

import atexit
import os
import shutil
import tempfile

# Force a hermetic environment: the suite must NEVER write into a real PKI dir or use a real passphrase,
# even on a machine where CA_DATA_DIR/CA_ROOT_PASSPHRASE already point at production material (e.g. a
# crabbox/CI box with ca-issuer env). Hard-set (not setdefault) so the ambient env can't win, and clean
# the tmp dir up at exit rather than leaking it (6.103).
_ca_data_dir = tempfile.mkdtemp(prefix="ca-issuer-test-")
os.environ["CA_DATA_DIR"] = _ca_data_dir
os.environ["CA_ROOT_PASSPHRASE"] = "test-passphrase-not-for-production"
atexit.register(lambda: shutil.rmtree(_ca_data_dir, ignore_errors=True))
# Tests run without a DATABASE_URL — opt into the in-memory token store (4.17).
os.environ.setdefault("CA_ALLOW_MEMORY_STORE", "1")
