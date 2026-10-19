# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every ORM model of the server, imported in one place.

Relationships name their targets as strings ("Server", "Connection.server_id"), and
SQLAlchemy resolves them only when the first query configures the mappers; a model no
import reached by then is unknown, and that query fails. The processes import different
parts of the app, so each imports this module before its first query: the web process
(app/main.py), the scheduler (app/scheduler_main.py), the hook worker
(app/modules/hooks/script_worker.py) and the CLI (app/cli.py).

Base.metadata knows only the tables of the models imported by then, so alembic/env.py
(target_metadata) and tests/conftest.py (create_all) import this module as well.

A new models.py belongs here (tests/test_model_registry.py, tests/test_conftest_models.py).
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
