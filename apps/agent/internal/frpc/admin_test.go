// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"context"
	"encoding/hex"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
)

// checkAdminConf fails t unless kv is an admin.conf as the agent writes it: a port, and a
// password of 32 random bytes in hex.
func checkAdminConf(t *testing.T, kv map[string]string) {
	t.Helper()
	if port, err := strconv.Atoi(kv["PORT"]); err != nil || port < 1 || port > 65535 {
		t.Errorf("admin.conf PORT = %q, want a TCP port", kv["PORT"])
	}
	if raw, err := hex.DecodeString(kv["PASSWORD"]); err != nil || len(raw) != 32 {
		t.Errorf("admin.conf PASSWORD = %q, want 32 bytes in hex", kv["PASSWORD"])
	}
}

// R-0398: the agent runs as a oneshot, and a reload has to reach the frpc that started on the
// admin API's port and password; admin.conf keeps them. It is private like frpc.toml, since the
// password guards the admin API (GET /api/config answers with the frps token), and it stays the
// same over runs. frpc.toml carries the same values, the API on loopback only.
func TestReloadAdminConfIsPrivateAndStable(t *testing.T) {
	setupSyncTest(t, "https://unused.example")
	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the first tunnel: %v", err)
	}
	adminConf := filepath.Join(config.FrpDir(), "admin.conf")
	first, err := os.ReadFile(adminConf)
	if err != nil {
		t.Fatalf("admin.conf after the first tunnel: %v", err)
	}
	if runtime.GOOS != "windows" {
		if info, err := os.Stat(adminConf); err != nil || info.Mode().Perm() != 0o600 {
			t.Errorf("admin.conf stat = %v, %v, want mode 0600 (it holds the admin API password)", info, err)
		}
	}
	kv, err := config.LoadKeyValue(adminConf)
	if err != nil {
		t.Fatal(err)
	}
	checkAdminConf(t, kv)
	head := readFile(t, config.FrpConfigFile())
	for _, line := range []string{`webServer.addr = "127.0.0.1"`, "webServer.port = " + kv["PORT"],
		`webServer.user = "adminhelper"`, `webServer.password = "` + kv["PASSWORD"] + `"`} {
		if !strings.Contains(head, line+"\n") {
			t.Errorf("frpc.toml %q is missing the line %q", head, line)
		}
	}

	serveToml(t, twoTunnelsToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a second tunnel: %v", err)
	}
	if second := readFile(t, adminConf); second != string(first) {
		t.Errorf("admin.conf after the next run = %q, want it unchanged %q", second, first)
	}

	// Each host draws its own password.
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	other, err := loadAdminAPI()
	if err != nil {
		t.Fatalf("admin API of another host: %v", err)
	}
	if other.password == kv["PASSWORD"] {
		t.Errorf("another host got the same password %q", other.password)
	}
}

// The values of admin.conf go into frpc.toml unescaped by the agent: a file not as the agent
// writes it (cut off, edited) gets a new port and password instead of reaching frpc.toml.
func TestReloadAdminConfReplacesABrokenOne(t *testing.T) {
	cases := map[string]string{
		"short password":        "PORT=\"7400\"\nPASSWORD=\"abc\"\n",
		"password not hex":      "PORT=\"7400\"\nPASSWORD=\"" + strings.Repeat("a", 63) + "\\\"\n",
		"port out of range":     "PORT=\"70000\"\nPASSWORD=\"" + strings.Repeat("a", 64) + "\"\n",
		"no port":               "PASSWORD=\"" + strings.Repeat("a", 64) + "\"\n",
		"cut off while writing": "PORT=\"74",
	}
	for name, content := range cases {
		t.Run(name, func(t *testing.T) {
			t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
			adminConf := filepath.Join(config.FrpDir(), "admin.conf")
			if err := os.WriteFile(adminConf, []byte(content), 0o600); err != nil {
				t.Fatal(err)
			}

			api, err := loadAdminAPI()
			if err != nil {
				t.Fatalf("loadAdminAPI: %v", err)
			}
			kv, err := config.LoadKeyValue(adminConf)
			if err != nil {
				t.Fatal(err)
			}
			checkAdminConf(t, kv)
			if kv["PORT"] != strconv.Itoa(api.port) || kv["PASSWORD"] != api.password {
				t.Errorf("admin.conf = %v, want the values loadAdminAPI returned (%d, %q)", kv, api.port, api.password)
			}
		})
	}
}

// procNetTCPLine is a /proc/net/tcp line for a socket at local in state st, owned by uid.
func procNetTCPLine(local, st string, uid int) string {
	return "   0: " + local + " 00000000:0000 " + st + " 00000000:00000000 00:00000000 00000000 " +
		strconv.Itoa(uid) + "        0 4711 1 0000000000000000 100 0 0 10 0\n"
}

// The reload goes only to frpc on its own admin port: a socket listening (state 0A) on
// 127.0.0.1 at that port, owned by root, and none of another user there.
func TestReloadAdminListenerInProcNetTCP(t *testing.T) {
	const header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
	const port = 7400
	own := loopbackAddr(port)
	cases := map[string]struct {
		table string
		want  bool
	}{
		"root listens":                {header + procNetTCPLine(own, "0A", 0), true},
		"another user listens":        {header + procNetTCPLine(own, "0A", 1000), false},
		"root and another user":       {header + procNetTCPLine(own, "0A", 0) + procNetTCPLine(own, "0A", 1000), false},
		"connection, not a listener":  {header + procNetTCPLine(own, "01", 0), false},
		"another port":                {header + procNetTCPLine(loopbackAddr(port+1), "0A", 0), false},
		"all addresses, not loopback": {header + procNetTCPLine("00000000:1CE8", "0A", 0), false},
		"nothing":                     {header, false},
		"cut off":                     {header + "   0: " + own + " 00000000:0000 0A\n", false},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			if got := listensOnLoopback([]byte(tc.table), port, 0); got != tc.want {
				t.Errorf("listensOnLoopback = %v, want %v", got, tc.want)
			}
		})
	}

	// The address as the kernel writes it: a real listener of this test's user.
	if runtime.GOOS == "linux" {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		real := l.Addr().(*net.TCPAddr).Port
		table, err := os.ReadFile("/proc/net/tcp")
		if err != nil {
			t.Fatal(err)
		}
		if !listensOnLoopback(table, real, os.Getuid()) || listensOnLoopback(table, real, os.Getuid()+1) {
			t.Errorf("listener on 127.0.0.1:%d of uid %d not found as such in /proc/net/tcp", real, os.Getuid())
		}
		_ = l.Close()
	}
}
