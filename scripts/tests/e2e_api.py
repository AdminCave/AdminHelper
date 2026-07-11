# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tiny admin-API client for the E2E orchestrators: seed + query over the
self-signed test gateway (cert verification is intentionally skipped — this only
ever talks to a throwaway local stack). Used via lib_e2e_stack.sh's e2e_api().

    e2e_api.py <base_url> <token> <op> [args...]

ops:
    server <name> <hostname>                       -> prints the new server id
    config <name> <server_addr> <bind_port>        -> prints the new FRP config id
    tunnel <server_id> <config_id> <name> <port>   -> prints the new tunnel id
    count-tunnels <server_id>                       -> prints the tunnel count
    provision-token <server_id>                    -> prints a fresh provision token
    connection <name> <kind> <host> <port> <user>  -> prints the new connection id
    web-connection <name> <url>                    -> prints the new web connection id
"""

import json
import ssl
import sys
import urllib.request


def _call(base, token, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return json.load(resp)


def main(argv):
    base, token, op, *rest = argv
    if op == "server":
        name, hostname = rest
        print(
            _call(base, token, "POST", "/api/servers", {"name": name, "hostname": hostname})["id"]
        )
    elif op == "config":
        name, server_addr, bind_port = rest
        print(
            _call(
                base,
                token,
                "POST",
                "/api/frp/server-config",
                {"name": name, "server_addr": server_addr, "bind_port": int(bind_port)},
            )["id"]
        )
    elif op == "tunnel":
        server_id, config_id, name, local_port = rest
        print(
            _call(
                base,
                token,
                "POST",
                "/api/frp/tunnels",
                {
                    "server_id": server_id,
                    "frp_config_id": config_id,
                    "name": name,
                    "tunnel_type": "stcp",
                    "protocol": "ssh",
                    "local_port": int(local_port),
                },
            )["id"]
        )
    elif op == "count-tunnels":
        (server_id,) = rest
        tunnels = _call(base, token, "GET", "/api/frp/tunnels")
        print(sum(1 for t in tunnels if server_id in (t.get("serverId"), t.get("server_id"))))
    elif op == "tunnel-conn":
        # STCP tunnel linked to a connection (so the desktop resolves the
        # connection through it). protocol is ssh/rdp/web.
        server_id, config_id, name, local_port, protocol, connection_id = rest
        print(
            _call(
                base,
                token,
                "POST",
                "/api/frp/tunnels",
                {
                    "server_id": server_id,
                    "frp_config_id": config_id,
                    "name": name,
                    "tunnel_type": "stcp",
                    "protocol": protocol,
                    "local_port": int(local_port),
                    "connection_id": connection_id,
                },
            )["id"]
        )
    elif op == "provision-token":
        (server_id,) = rest
        print(_call(base, token, "POST", f"/api/servers/{server_id}/provision/token", {})["token"])
    elif op == "connection":
        name, kind, host, port, user = rest
        print(
            _call(
                base,
                token,
                "POST",
                "/api/connections",
                # trustCert=True so an RDP open passes /cert:ignore to xfreerdp3
                # (otherwise the headless TLS handshake stalls on a cert prompt).
                {
                    "name": name,
                    "kind": kind,
                    "host": host,
                    "port": int(port),
                    "username": user,
                    "trustCert": True,
                },
            )["id"]
        )
    elif op == "web-connection":
        name, url = rest
        print(
            _call(
                base, token, "POST", "/api/connections", {"name": name, "kind": "web", "url": url}
            )["id"]
        )
    else:
        sys.exit(f"unknown op: {op}")


if __name__ == "__main__":
    main(sys.argv[1:])
