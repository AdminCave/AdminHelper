from pydantic import BaseModel
from typing import Optional


# --- FRP Server Config ---

class FrpServerConfigCreate(BaseModel):
    name: str
    server_addr: str  # z.B. "frps.example.net"
    bind_port: int = 7000
    vhost_https_port: Optional[int] = None
    auth_token: Optional[str] = None  # wird auto-generiert wenn leer
    subdomain_host: Optional[str] = None
    max_ports_per_client: Optional[int] = None
    dashboard_port: Optional[int] = None
    dashboard_user: Optional[str] = None
    dashboard_password: Optional[str] = None
    extra_config: Optional[dict] = None
    tls_force: bool = False


class FrpServerConfigUpdate(BaseModel):
    name: Optional[str] = None
    server_addr: Optional[str] = None
    bind_port: Optional[int] = None
    vhost_https_port: Optional[int] = None
    auth_token: Optional[str] = None
    subdomain_host: Optional[str] = None
    max_ports_per_client: Optional[int] = None
    dashboard_port: Optional[int] = None
    dashboard_user: Optional[str] = None
    dashboard_password: Optional[str] = None
    tls_force: Optional[bool] = None
    extra_config: Optional[dict] = None


# --- FRP Tunnel ---

class FrpTunnelCreate(BaseModel):
    server_id: str
    frp_config_id: str
    name: str  # Proxy-Name, z.B. "k01-lnx1-ssh"
    tunnel_type: str  # "stcp" oder "https"
    protocol: str  # "ssh", "rdp", "web"
    local_ip: str = "127.0.0.1"
    local_port: int
    secret_key: Optional[str] = None  # auto-generiert fuer STCP wenn leer
    custom_domains: Optional[str] = None  # nur fuer HTTPS
    visitor_port: Optional[int] = None  # nur fuer STCP
    connection_id: Optional[str] = None
    enabled: bool = True
    extra_config: Optional[dict] = None
    tags: Optional[list[str]] = []
    auto_create_connection: bool = False  # automatisch passende Connection erstellen


class FrpTunnelUpdate(BaseModel):
    name: Optional[str] = None
    tunnel_type: Optional[str] = None
    protocol: Optional[str] = None
    local_ip: Optional[str] = None
    local_port: Optional[int] = None
    secret_key: Optional[str] = None
    custom_domains: Optional[str] = None
    visitor_port: Optional[int] = None
    connection_id: Optional[str] = None
    enabled: Optional[bool] = None
    extra_config: Optional[dict] = None
    tags: Optional[list[str]] = None


# --- Visitors ---

class VisitorCreate(BaseModel):
    name: str  # z.B. "tech-kevin" (wird als frpc user verwendet)
    display_name: Optional[str] = None
    notes: Optional[str] = None
    server_ids: list[str] = []  # zugewiesene Server


class VisitorUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    notes: Optional[str] = None
    server_ids: Optional[list[str]] = None
