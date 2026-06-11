# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test setup for the ca-issuer. The PKI material is created in a tmp dir on
first import (lifespan calls ensure_hierarchy), so CA_DATA_DIR + the root
passphrase must be set BEFORE app.main is imported."""

import os
import tempfile

os.environ.setdefault("CA_DATA_DIR", tempfile.mkdtemp(prefix="ca-issuer-test-"))
os.environ.setdefault("CA_ROOT_PASSPHRASE", "test-passphrase-not-for-production")
