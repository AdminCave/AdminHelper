# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Monitoring-service routers — split by domain."""

from app.routers.admin import router as admin_router
from app.routers.agent import router as agent_router
from app.routers.alerts import router as alerts_router
from app.routers.checks import router as checks_router
from app.routers.maintenance import router as maintenance_router
from app.routers.templates import router as templates_router

all_routers = [
    checks_router,
    agent_router,
    alerts_router,
    templates_router,
    maintenance_router,
    admin_router,
]
