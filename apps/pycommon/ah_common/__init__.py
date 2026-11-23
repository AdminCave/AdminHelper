# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Code shared by the server and the monitoring service (apps/pycommon).

Both images copy this package next to their own `app` package (/app/ah_common); the
test suites put apps/pycommon on sys.path in their conftest.
"""
