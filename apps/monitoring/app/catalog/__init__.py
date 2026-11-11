# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The module catalog: what the monitoring knows how to recognise and check on a host."""

from app.catalog.loader import Catalog, get_catalog, load_catalog

__all__ = ["Catalog", "get_catalog", "load_catalog"]
