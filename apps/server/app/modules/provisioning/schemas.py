# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Literal, Optional

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


# --- Platform catalog (GET /api/provisioning/platforms) ---------------------
# Commands are a fixed head plus named arguments; the desktop inserts the values and
# quotes them per shell, so no value ever travels inside server-built text (R-1595).


class ProvisionCommandArgOut(BaseModel):
    flag: str
    value: Literal["serverUrl", "serverId", "caFp", "token", "flag", "insecure"]
    optional: bool
    mode: Optional[Literal["interactive", "automation"]]


class ProvisionCommandOut(BaseModel):
    action: Literal["install", "update", "reregister", "remove"]
    shell: Literal["bash", "sh", "powershell"]
    base: str
    args: list[ProvisionCommandArgOut]


class ProvisionPortOut(BaseModel):
    port: int
    purpose: Literal["api", "enroll", "repo", "tunnel"]
    tunnelOnly: bool


class ProvisionPrerequisitesOut(BaseModel):
    systems: list[str]
    ports: list[ProvisionPortOut]


class ProvisionDocOut(BaseModel):
    de: str
    en: str


class ProvisionPlatformOut(BaseModel):
    id: Literal["linux", "windows", "freebsd", "opnsense"]
    available: bool
    reason: Optional[Literal["noRepo", "notYet"]]
    versions: list[str]
    arch: list[str]
    abis: list[str]
    prerequisites: ProvisionPrerequisitesOut
    commands: list[ProvisionCommandOut]
    doc: ProvisionDocOut


class ProvisionPlatformsOut(BaseModel):
    platforms: list[ProvisionPlatformOut]
