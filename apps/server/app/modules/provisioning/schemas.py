# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Optional

from pydantic import BaseModel


class ProvisionTokenCreatedOut(BaseModel):
    """A new provision token; token is the raw value, handed out only here."""

    token: str
    expiresAt: Optional[str]
    serverId: str
    serverName: str


class ProvisionTokenOut(BaseModel):
    """A provision token as ProvisionToken.to_dict hands it out."""

    id: str
    serverId: str
    expiresAt: Optional[str]
    usedAt: Optional[str]
    isValid: bool
    createdAt: Optional[str]


class FrpBundleOut(BaseModel):
    config: str
    pkiBundle: str


class ActivateEnrollmentOut(BaseModel):
    token: str
    subjectId: str
    scope: str
    enrollPort: int


class ActivateOut(BaseModel):
    serverName: str
    apiKey: str
    monitorApiKey: Optional[str]
    monitorUrl: Optional[str]
    frp: Optional[FrpBundleOut]
    enrollment: ActivateEnrollmentOut
