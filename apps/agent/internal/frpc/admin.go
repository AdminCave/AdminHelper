// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"adminhelper-agent/internal/config"
)

// adminUser is the user of frpc's local admin API; the password is the secret.
const adminUser = "adminhelper"

// adminPasswordBytes is the length of the admin API password in random bytes, written as hex.
const adminPasswordBytes = 32

// adminAPI is frpc's admin API, which the agent reloads frpc through: on 127.0.0.1 only and
// never without a password. Without user and password frp serves it to every local process,
// GET /api/config with the frps token included.
type adminAPI struct {
	port     int
	password string
}

// adminConfFile keeps the admin API's port and password (0600 like frpc.toml): the agent runs as
// a oneshot, and a reload has to reach the frpc that started on them.
func adminConfFile() string { return filepath.Join(config.FrpDir(), "admin.conf") }

// loadAdminAPI reads admin.conf. A missing file, or one not as the agent writes it, gets a new
// port and password.
func loadAdminAPI() (adminAPI, error) {
	kv, err := config.LoadKeyValue(adminConfFile())
	if err == nil {
		if api, ok := parseAdminAPI(kv); ok {
			return api, nil
		}
		logger.Warnf("%s is not as the agent writes it, the frpc admin API gets a new port and password", adminConfFile())
	} else if !os.IsNotExist(err) {
		return adminAPI{}, fmt.Errorf("read %s: %w", adminConfFile(), err)
	}
	return renewAdminAPI()
}

// adminAPIListens reports whether frpc listens on the admin port admin.conf names, without
// writing a new one.
func adminAPIListens() bool {
	kv, err := config.LoadKeyValue(adminConfFile())
	if err != nil {
		return false
	}
	api, ok := parseAdminAPI(kv)
	return ok && ownsAdminPort(api.port)
}

// renewAdminAPI writes admin.conf with a free port on loopback and a new password. Sync also
// calls it when frpc does not start: after a reboot another process may hold the old port, and
// frpc does not start without it. The old password goes with the old port.
func renewAdminAPI() (adminAPI, error) {
	raw := make([]byte, adminPasswordBytes)
	if _, err := rand.Read(raw); err != nil {
		return adminAPI{}, fmt.Errorf("draw the frpc admin API password: %w", err)
	}
	password := hex.EncodeToString(raw)
	port, err := freeLoopbackPort()
	if err != nil {
		return adminAPI{}, err
	}
	if err := config.WriteKeyValue(adminConfFile(), []config.KeyValue{
		{Key: "PORT", Value: strconv.Itoa(port)},
		{Key: "PASSWORD", Value: password},
	}); err != nil {
		return adminAPI{}, fmt.Errorf("write %s: %w", adminConfFile(), err)
	}
	return adminAPI{port: port, password: password}, nil
}

// parseAdminAPI accepts admin.conf only as the agent writes it. Its values go into frpc.toml
// unescaped, so the password must be hex of the full length.
func parseAdminAPI(kv map[string]string) (adminAPI, bool) {
	port, err := strconv.Atoi(kv["PORT"])
	if err != nil || port < 1 || port > 65535 {
		return adminAPI{}, false
	}
	password := kv["PASSWORD"]
	if raw, err := hex.DecodeString(password); err != nil || len(raw) != adminPasswordBytes {
		return adminAPI{}, false
	}
	return adminAPI{port: port, password: password}, true
}

// freeLoopbackPort asks the kernel for a port free on 127.0.0.1 now. Another process can take it
// before frpc does; Sync then renews the admin API (renewAdminAPI).
func freeLoopbackPort() (int, error) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0, fmt.Errorf("find a free port for the frpc admin API: %w", err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port, nil
}

// head is the part of frpc.toml's local head that opens the admin API on loopback for the reload.
func (a adminAPI) head() string {
	return fmt.Sprintf("webServer.addr = \"127.0.0.1\"\nwebServer.port = %d\nwebServer.user = \"%s\"\n"+
		"webServer.password = \"%s\"\n", a.port, adminUser, a.password)
}

// loopbackAddr is 127.0.0.1:port as /proc/net/tcp writes it: the address as a 32-bit number in
// host byte order, then the port, both in hex.
func loopbackAddr(port int) string {
	return fmt.Sprintf("%08X:%04X", binary.NativeEndian.Uint32([]byte{127, 0, 0, 1}), port)
}

// listensOnLoopback reports whether procNetTCP (the content of /proc/net/tcp) has a socket
// listening on 127.0.0.1:port owned by uid, and none of another user there. The reload goes only
// to the agent's own frpc, which frpc.service runs as root.
func listensOnLoopback(procNetTCP []byte, port, uid int) bool {
	local := loopbackAddr(port)
	found := false
	for _, line := range strings.Split(string(procNetTCP), "\n") {
		// sl, local_address, rem_address, st, tx_queue:rx_queue, tr:tm->when, retrnsmt, uid, ...
		f := strings.Fields(line)
		if len(f) < 8 || !strings.EqualFold(f[1], local) || f[3] != "0A" { // 0A: TCP_LISTEN
			continue
		}
		if owner, err := strconv.Atoi(f[7]); err != nil || owner != uid {
			return false
		}
		found = true
	}
	return found
}
