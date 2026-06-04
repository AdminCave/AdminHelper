# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test setup for the monitoring component.

Deliberately NO Postgres/testcontainers: only pure-logic tests run here
(line-protocol escaping, alert filter/cooldown, check status transitions).
The modules under test pull a writable DATA_DIR via app.core.config (creating
an .api_key there if needed) — so redirect it to a tmp directory before every
import.
"""

import os
import tempfile

os.environ.setdefault("DATA_DIR", os.path.join(tempfile.gettempdir(), "adminhelper-monitor-test"))
