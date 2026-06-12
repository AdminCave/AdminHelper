# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP module: combines all sub-routers into one shared router."""

from fastapi import APIRouter, Depends

from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT, require_scope
from app.modules.frp.config_router import router as config_router
from app.modules.frp.generate_router import router as generate_router
from app.modules.frp.provision_router import router as provision_router
from app.modules.frp.status_router import router as status_router
from app.modules.frp.tunnel_router import router as tunnel_router

# mTLS scope (ADR 0001 D8, permissive this phase). The interactive management
# sub-routers are human/admin (access). provision_router is the agent's frpc-sync
# and is dual-use: the agent (tunnel cert) AND an interactive admin (access) read
# the same config, so it accepts either scope.
_admin = [Depends(require_scope(SCOPE_ACCESS))]
_agent_or_admin = [Depends(require_scope(SCOPE_AGENT, SCOPE_ACCESS))]

router = APIRouter()
router.include_router(config_router, dependencies=_admin)
router.include_router(tunnel_router, dependencies=_admin)
router.include_router(generate_router, dependencies=_admin)
router.include_router(status_router, dependencies=_admin)
router.include_router(provision_router, dependencies=_agent_or_admin)
