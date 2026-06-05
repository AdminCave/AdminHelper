# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP module: combines all sub-routers into one shared router."""

from fastapi import APIRouter

from app.modules.frp.config_router import router as config_router
from app.modules.frp.tunnel_router import router as tunnel_router
from app.modules.frp.generate_router import router as generate_router
from app.modules.frp.status_router import router as status_router
from app.modules.frp.pki_router import router as pki_router
from app.modules.frp.provision_router import router as provision_router

router = APIRouter()
router.include_router(config_router)
router.include_router(tunnel_router)
router.include_router(generate_router)
router.include_router(status_router)
router.include_router(pki_router)
router.include_router(provision_router)
