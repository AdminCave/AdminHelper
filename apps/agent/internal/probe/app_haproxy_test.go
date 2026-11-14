// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

// The answers of HAProxy 3.4.7 to a configuration with three backends: be_up with a server up, one
// down and one disabled; be_down with both servers down; be_nocheck with a server without checks.
// show stat is cut after its status column; servers state adds a drained server, one in maintenance
// through the server it tracks, one starting (srv_op_state 1) and one stopping softly (3).
const (
	haproxyStatAnswer = `# pxname,svname,qcur,qmax,scur,smax,slim,stot,bin,bout,dreq,dresp,ereq,econ,eresp,wretr,wredis,status,weight,act
be_up,BACKEND,0,0,0,0,26212,0,0,0,0,0,,0,0,0,0,UP,1,1
be_down,BACKEND,0,0,0,0,1,0,0,0,0,0,,0,0,0,0,DOWN,0,0
be_nocheck,BACKEND,0,0,0,0,1,0,0,0,0,0,,0,0,0,0,UP,1,1

`
	haproxyStateAnswer = `1
# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state srv_uweight srv_iweight srv_time_since_last_change srv_check_status srv_check_result srv_check_health srv_check_state srv_agent_state bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl srv_check_port srv_check_addr srv_agent_addr srv_agent_port
3 be_up 1 a 127.0.0.1 2 0 1 1 6 6 3 4 6 0 0 0 - 8080 - 0 0 - - 0
3 be_up 2 b 127.0.0.1 0 0 1 1 6 8 2 0 6 0 0 0 - 1 - 0 0 - - 0
3 be_up 3 m 127.0.0.1 0 5 1 1 6 1 0 0 8 0 0 0 - 8080 - 0 0 - - 0
3 be_up 4 d 127.0.0.1 2 8 1 1 44 6 3 4 6 0 0 0 - 8080 - 0 0 - - 0
3 be_up 5 t 127.0.0.1 0 2 1 1 44 6 3 4 6 0 0 0 - 8080 - 0 0 - - 0
3 be_up 6 s 127.0.0.1 1 0 1 1 44 6 3 4 6 0 0 0 - 8080 - 0 0 - - 0
3 be_up 7 g 127.0.0.1 3 0 1 1 44 6 3 4 6 0 0 0 - 8080 - 0 0 - - 0
4 be_down 1 x 127.0.0.1 0 0 1 1 6 8 2 0 6 0 0 0 - 2 - 0 0 - - 0
4 be_down 2 y 127.0.0.1 0 0 1 1 6 8 2 0 6 0 0 0 - 3 - 0 0 - - 0
5 be_nocheck 1 n 127.0.0.1 2 0 1 1 6 1 0 0 0 0 0 0 - 4 - 0 0 - - 0

`
)

// haproxyConfigFile writes a configuration with body and makes it the only one haproxySocket reads.
func haproxyConfigFile(t *testing.T, body string) string {
	t.Helper()
	name := filepath.Join(t.TempDir(), "haproxy.cfg")
	if err := os.WriteFile(name, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	old := haproxyConfigs
	haproxyConfigs = []string{name}
	t.Cleanup(func() { haproxyConfigs = old })
	return name
}

// stubHAProxy answers each command on the stats socket from answers and records the sockets dialed
// and the commands sent; a socket missing from served has no listener.
func stubHAProxy(t *testing.T, served string, answers map[string]string) (dialed, sent *[]string) {
	t.Helper()
	var mu sync.Mutex
	dialed, sent = &[]string{}, &[]string{}
	old := haproxyDial
	haproxyDial = func(_ context.Context, path string) (net.Conn, error) {
		mu.Lock()
		*dialed = append(*dialed, path)
		mu.Unlock()
		if path != served {
			return nil, errNoListener
		}
		client, server := net.Pipe()
		go func() {
			defer func() { _ = server.Close() }()
			buf := make([]byte, 512)
			n, _ := server.Read(buf)
			mu.Lock()
			*sent = append(*sent, string(buf[:n]))
			mu.Unlock()
			_, _ = server.Write([]byte(answers[strings.TrimSuffix(string(buf[:n]), "\n")]))
		}()
		return client, nil
	}
	t.Cleanup(func() { haproxyDial = old })
	return dialed, sent
}

var haproxyAnswers = map[string]string{"show stat -1 2 -1": haproxyStatAnswer, "show servers state": haproxyStateAnswer}

func TestHAProxyServersCountsBackendsAndServersWithoutNames(t *testing.T) {
	haproxyConfigFile(t, "global\n    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners\n")
	dialed, sent := stubHAProxy(t, "/run/haproxy/admin.sock", haproxyAnswers)

	res := Run(context.Background(), appProbe("haproxy_servers", unitTarget("haproxy.service"),
		"backends", "backends_down", "servers", "servers_down", "servers_maint"), time.Now(), nil)

	if res.Status != StatusOK {
		t.Fatalf("result = %+v, want ok", res)
	}
	// Down are b, x and y; m (disabled) and t (tracking a server in maintenance) are in maintenance;
	// the drained d, the starting s and the softly stopping g still serve.
	want := map[string]any{"backends": 3, "backends_down": 1, "servers": 10, "servers_down": 3, "servers_maint": 2}
	got, _ := json.Marshal(res.Values)
	wantJSON, _ := json.Marshal(want)
	if string(got) != string(wantJSON) {
		t.Errorf("values = %s, want %s", got, wantJSON)
	}
	for _, name := range []string{"be_up", "be_down", "127.0.0.1"} {
		if strings.Contains(string(got), name) {
			t.Errorf("values %s name %s", got, name)
		}
	}
	if strings.Join(*dialed, " ") != "/run/haproxy/admin.sock /run/haproxy/admin.sock" {
		t.Errorf("dialed %q, want the socket of the configuration twice", *dialed)
	}
	if strings.Join(*sent, "|") != "show stat -1 2 -1\n|show servers state\n" {
		t.Errorf("sent %q, want show stat of the backends, then show servers state", *sent)
	}
}

func TestStatsSocketIsTheFirstAbsoluteUnixSocketOfTheConfiguration(t *testing.T) {
	for name, tc := range map[string]struct{ cfg, want string }{
		"plain":            {"global\n\tstats socket /run/haproxy/admin.sock mode 660 level admin\n", "/run/haproxy/admin.sock"},
		"unix@":            {"global\n  stats socket unix@/var/run/haproxy.sock\n", "/var/run/haproxy.sock"},
		"quoted":           {"global\n  stats socket \"/run/hap.sock\" level user\n", "/run/hap.sock"},
		"OPNsense":         {"global\n    stats socket /var/run/haproxy.socket group proxy mode 775 level admin\n", "/var/run/haproxy.socket"},
		"after tcp":        {"global\n stats socket ipv4@127.0.0.1:9999 level admin\n stats socket /run/b.sock\n", "/run/b.sock"},
		"comment after":    {"global\n stats socket /run/a.sock # the admin socket\n", "/run/a.sock"},
		"commented out":    {"global\n# stats socket /run/a.sock\n #stats socket /run/b.sock\n", ""},
		"relative":         {"global\n stats socket haproxy.sock\n", ""},
		"abstract":         {"global\n stats socket abns@haproxy\n", ""},
		"too long":         {"global\n stats socket /" + strings.Repeat("a", maxSocketPath) + "\n", ""},
		"other stats line": {"listen stats\n stats uri /stats\n stats socket\n", ""},
	} {
		got, ok := statsSocket([]byte(tc.cfg))
		if got != tc.want || ok != (tc.want != "") {
			t.Errorf("%s: statsSocket = %q, %v; want %q", name, got, ok, tc.want)
		}
	}
}

func TestHAProxyServersReadsTheConfigurationOfThePorts(t *testing.T) {
	name := filepath.Join(t.TempDir(), "haproxy.conf")
	if err := os.WriteFile(name, []byte("global\n stats socket /var/run/haproxy.socket level admin\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	old := haproxyConfigs
	haproxyConfigs = []string{filepath.Join(t.TempDir(), "missing.cfg"), name}
	t.Cleanup(func() { haproxyConfigs = old })
	dialed, _ := stubHAProxy(t, "/var/run/haproxy.socket", haproxyAnswers)

	if _, err := haproxyServers(context.Background(), Target{Kind: kindUnit, Name: "haproxy"}); err != nil {
		t.Fatalf("haproxyServers = %v, want the counts", err)
	}
	if (*dialed)[0] != "/var/run/haproxy.socket" {
		t.Errorf("dialed %q, want the socket of the second configuration", *dialed)
	}
}

func TestHAProxyServersWithoutASocketIsUnsupported(t *testing.T) {
	ctx := context.Background()
	haproxy := Target{Kind: kindUnit, Name: "haproxy.service"}

	// A configuration without a stats socket: the view adds none. On FreeBSD it asks the socket of
	// the OPNsense plugin, which nobody serves here.
	haproxyConfigFile(t, "global\n  maxconn 100\nfrontend fe\n  bind :80\n")
	dialed, _ := stubHAProxy(t, "/run/served.sock", haproxyAnswers)
	if _, err := haproxyServers(ctx, haproxy); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no stats socket = %v, want ErrUnsupported", err)
	}
	wantDialed := ""
	if runtime.GOOS == "freebsd" {
		wantDialed = opnsenseHAProxySocket
	}
	if strings.Join(*dialed, " ") != wantDialed {
		t.Errorf("dialed %q, want %q", *dialed, wantDialed)
	}

	// A declared socket that nobody serves.
	haproxyConfigFile(t, "global\n stats socket /run/haproxy/admin.sock\n")
	if _, err := haproxyServers(ctx, haproxy); !errors.Is(err, ErrUnsupported) {
		t.Errorf("socket without a listener = %v, want ErrUnsupported", err)
	}

	// No configuration at all.
	old := haproxyConfigs
	haproxyConfigs = []string{filepath.Join(t.TempDir(), "missing.cfg")}
	t.Cleanup(func() { haproxyConfigs = old })
	if _, err := haproxyServers(ctx, haproxy); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no configuration = %v, want ErrUnsupported", err)
	}

	// Another unit.
	if _, err := haproxyServers(ctx, Target{Kind: kindUnit, Name: "nginx.service"}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("nginx = %v, want ErrUnsupported", err)
	}
}

func TestHAProxyServersRefusesAnAnswerItDoesNotKnow(t *testing.T) {
	haproxyConfigFile(t, "global\n stats socket /run/haproxy/admin.sock\n")
	for name, answers := range map[string]map[string]string{
		"stat denied":  {"show stat -1 2 -1": "Permission denied\n\n", "show servers state": haproxyStateAnswer},
		"state denied": {"show stat -1 2 -1": haproxyStatAnswer, "show servers state": "Permission denied\n\n"},
		"version 2":    {"show stat -1 2 -1": haproxyStatAnswer, "show servers state": strings.Replace(haproxyStateAnswer, "1\n", "2\n", 1)},
		"no op state": {"show stat -1 2 -1": haproxyStatAnswer,
			"show servers state": strings.Replace(haproxyStateAnswer, "srv_op_state", "srv_state", 1)},
		"short line": {"show stat -1 2 -1": haproxyStatAnswer, "show servers state": "1\n# be_id srv_op_state srv_admin_state\n3 2\n"},
		"no number":  {"show stat -1 2 -1": haproxyStatAnswer, "show servers state": "1\n# be_id srv_op_state srv_admin_state\n3 up 0\n"},
	} {
		stubHAProxy(t, "/run/haproxy/admin.sock", answers)
		values, err := haproxyServers(context.Background(), Target{Kind: kindUnit, Name: "haproxy.service"})
		if err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("%s = %v, %v; want an error of the view", name, values, err)
		}
	}
}

func TestHAProxyMaintenanceFlags(t *testing.T) {
	// The flags of srv_admin_state: FMAINT, IMAINT, CMAINT, RMAINT and HMAINT put a server in
	// maintenance, FDRAIN and IDRAIN do not.
	for admin, maint := range map[int]bool{0x01: true, 0x02: true, 0x04: true, 0x05: true, 0x08: false, 0x10: false, 0x20: true, 0x40: true} {
		if got := admin&haproxyMaint != 0; got != maint {
			t.Errorf("srv_admin_state %#x in maintenance = %v, want %v", admin, got, maint)
		}
	}
}
