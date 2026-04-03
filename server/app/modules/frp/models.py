import json
import secrets
from typing import Any

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class FrpServerConfig(Base):
    __tablename__ = "frp_server_config"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    server_addr = Column(String, nullable=False)  # z.B. "frps.example.net"
    bind_port = Column(Integer, default=7000)
    vhost_https_port = Column(Integer, nullable=True)  # z.B. 443
    auth_token = Column(String, nullable=False)
    subdomain_host = Column(String, nullable=True)  # z.B. "ops.example.net"
    max_ports_per_client = Column(Integer, nullable=True)
    dashboard_port = Column(Integer, nullable=True)  # frps Web-Dashboard
    dashboard_user = Column(String, nullable=True)
    dashboard_password = Column(String, nullable=True)
    extra_config = Column(String, nullable=True)  # JSON fuer zusaetzliche frps.toml-Felder
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    tunnels = relationship(
        "FrpTunnel",
        backref="frp_config",
        lazy="selectin",
        foreign_keys="FrpTunnel.frp_config_id",
    )

    def to_dict(self, include_tunnels: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "serverAddr": self.server_addr,
            "bindPort": self.bind_port,
            "vhostHttpsPort": self.vhost_https_port,
            "authToken": self.auth_token,
            "subdomainHost": self.subdomain_host,
            "maxPortsPerClient": self.max_ports_per_client,
            "dashboardPort": self.dashboard_port,
            "dashboardUser": self.dashboard_user,
            "dashboardPassword": self.dashboard_password,
            "extraConfig": json.loads(self.extra_config) if self.extra_config else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_tunnels:
            result["tunnels"] = [t.to_dict() for t in self.tunnels]
        return result


class FrpTunnel(Base):
    __tablename__ = "frp_tunnels"

    id = Column(String, primary_key=True)
    server_id = Column(String, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    frp_config_id = Column(String, ForeignKey("frp_server_config.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, unique=True, nullable=False)  # Proxy-Name, z.B. "k01-lnx1-ssh"
    tunnel_type = Column(String, nullable=False)  # "stcp" oder "https"
    protocol = Column(String, nullable=False)  # "ssh", "rdp", "web"
    local_ip = Column(String, default="127.0.0.1")
    local_port = Column(Integer, nullable=False)
    secret_key = Column(String, nullable=True)  # nur fuer STCP
    custom_domains = Column(String, nullable=True)  # nur fuer HTTPS, komma-separiert
    visitor_port = Column(Integer, nullable=True)  # lokaler Port am Admin-PC (STCP)
    connection_id = Column(String, ForeignKey("connections.id", ondelete="SET NULL"), nullable=True)
    enabled = Column(Boolean, default=True)
    extra_config = Column(String, nullable=True)  # JSON
    created_at = Column(DateTime, server_default=func.now())

    @staticmethod
    def generate_secret() -> str:
        return secrets.token_urlsafe(32)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "serverId": self.server_id,
            "frpConfigId": self.frp_config_id,
            "name": self.name,
            "tunnelType": self.tunnel_type,
            "protocol": self.protocol,
            "localIp": self.local_ip,
            "localPort": self.local_port,
            "secretKey": self.secret_key,
            "customDomains": self.custom_domains,
            "visitorPort": self.visitor_port,
            "connectionId": self.connection_id,
            "enabled": self.enabled,
            "extraConfig": json.loads(self.extra_config) if self.extra_config else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
