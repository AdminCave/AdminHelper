# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every ORM model of the server, imported in one place.

Relationships name their targets as strings ("Server", "Connection.server_id"), and
SQLAlchemy resolves them only when the first query configures the mappers; a model no
import reached by then is unknown, and that query fails. The web process and the
scheduler process import different parts of the app, so both import this module before
their first query. A new models.py belongs here (tests/test_model_registry.py).
"""

import app.modules.ansible.models  # noqa: F401
import app.modules.api_keys.models  # noqa: F401
import app.modules.audit.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.enrollment.models  # noqa: F401
import app.modules.frp.models  # noqa: F401
import app.modules.hooks.models  # noqa: F401
import app.modules.notifications.models  # noqa: F401
import app.modules.provisioning.models  # noqa: F401
import app.modules.servers.models  # noqa: F401
import app.modules.users.models  # noqa: F401
