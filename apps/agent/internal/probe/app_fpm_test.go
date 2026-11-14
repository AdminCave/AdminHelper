// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

// fpmPage is the status page of PHP-FPM 8.4.27 with ?json, its counters set by the test.
func fpmPage(pool string, queue, maxChildren, slow int) string {
	return fmt.Sprintf(`{"pool":%q,"process manager":"dynamic","start time":1794607985,"start since":87,`+
		`"accepted conn":1,"listen queue":%d,"max listen queue":0,"listen queue len":0,"idle processes":1,`+
		`"active processes":1,"total processes":2,"max active processes":1,"max children reached":%d,`+
		`"slow requests":%d,"memory peak":0}`, pool, queue, maxChildren, slow)
}

// fpmPoolFiles writes the files of a pool directory and makes it the directory of every unit.
func fpmPoolFiles(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	for name, body := range files {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	old := fpmPoolDir
	fpmPoolDir = func(string) (string, error) { return dir, nil }
	t.Cleanup(func() { fpmPoolDir = old })
	return dir
}

// fpmServer stands in PHP-FPM: pages by SCRIPT_NAME, asked what each request named.
type fpmServer struct {
	pages map[string]string
	mu    sync.Mutex
	asked []string
}

// serve answers the one request of conn as PHP-FPM does: the page of its SCRIPT_NAME with the query
// json, else 404.
func (f *fpmServer) serve(conn net.Conn) {
	defer func() { _ = conn.Close() }()
	r := bufio.NewReader(conn)
	var params []byte
	for {
		var h [8]byte
		if _, err := io.ReadFull(r, h[:]); err != nil {
			return
		}
		body := make([]byte, int(binary.BigEndian.Uint16(h[4:6]))+int(h[6]))
		if _, err := io.ReadFull(r, body); err != nil {
			return
		}
		if h[1] == fcgiParams {
			params = append(params, body...)
		}
		if h[1] == fcgiStdin {
			break
		}
	}
	p := fcgiPairs(params)
	script, query := fmt.Sprint(p["SCRIPT_NAME"]), fmt.Sprint(p["QUERY_STRING"])
	f.mu.Lock()
	f.asked = append(f.asked, script+"?"+query)
	f.mu.Unlock()
	out := "Status: 404 Not Found\r\nContent-type: text/html; charset=UTF-8\r\n\r\nFile not found.\n"
	if page, ok := f.pages[script]; ok && query == "json" {
		out = "X-Powered-By: PHP/8.4.27\r\nContent-Type: application/json\r\n\r\n" + page
	}
	_, _ = conn.Write(fcgiRecord(fcgiStdout, []byte(out)))
	_, _ = conn.Write(fcgiRecord(fcgiStdout, nil))
	_, _ = conn.Write(fcgiRecord(fcgiEndRequest, make([]byte, 8)))
}

// stubFPMSocket serves the unix socket path with f; another path has nobody behind it.
func stubFPMSocket(t *testing.T, path string, f *fpmServer) *[]string {
	t.Helper()
	var mu sync.Mutex
	dialed := &[]string{}
	old := fpmDialUnix
	fpmDialUnix = func(_ context.Context, p string) (net.Conn, error) {
		mu.Lock()
		*dialed = append(*dialed, p)
		mu.Unlock()
		if p != path {
			return nil, errNoListener
		}
		client, server := net.Pipe()
		go f.serve(server)
		return client, nil
	}
	t.Cleanup(func() { fpmDialUnix = old })
	return dialed
}

// serveFPMPort serves f on a port of 127.0.0.1 and makes it where the unit listens: the port it
// returns, or listening on another port when elsewhere.
func serveFPMPort(t *testing.T, f *fpmServer, elsewhere bool) (port int, hints *[]int) {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			go f.serve(c)
		}
	}()
	port = l.Addr().(*net.TCPAddr).Port
	hints = &[]int{}
	old := fpmEndpoint
	fpmEndpoint = func(_ context.Context, t Target) (endpoint, error) {
		*hints = append(*hints, t.PortHint)
		p := port
		if elsewhere {
			p++
		}
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: uint16(p)}, nil
	}
	t.Cleanup(func() { fpmEndpoint = old })
	return port, hints
}

func TestFPMPoolsAddsUpTheStatusPagesOfThePoolsWithoutNames(t *testing.T) {
	f := &fpmServer{pages: map[string]string{"/st2": fpmPage("www", 2, 5, 1), "/status-api": fpmPage("api", 1, 0, 3)}}
	port, hints := serveFPMPort(t, f, false)
	dialed := stubFPMSocket(t, "/run/php/www.sock", f)
	fpmPoolFiles(t, map[string]string{
		"www.conf": "[global]\nerror_log = /var/log/php-fpm.log\n\n[www]\nuser = www-data\n" +
			"listen = /run/php/$pool.sock\npm.status_path = /status ; overridden below\nlisten.allowed_clients =\n\n" +
			"[open]\nlisten = 9000\n",
		"api.conf": fmt.Sprintf("; the API pool\n[api]\nlisten = \"127.0.0.1:%d\"\npm.status_path = '/status-$pool'\n\n"+
			"[guarded]\nlisten = [::]:9002\nlisten.allowed_clients = 192.0.2.10\n", port),
		"zz-override.conf":         "[www]\npm.status_path = /st2\n",
		"www.conf.dpkg-dist":       "[stale]\nlisten = 9100\npm.status_path = /status\n",
		"zz-override.conf.disable": "[www]\npm.status_path = /never\n",
	})

	res := Run(context.Background(), appProbe("fpm_pools", unitTarget("php8.4-fpm.service"),
		"pools", "pools_read", "pools_exposed", "listen_queue", "max_children_reached", "slow_requests"), time.Now(), nil)

	if res.Status != StatusOK {
		t.Fatalf("result = %+v, want ok", res)
	}
	// The pools api, guarded, www and open; api and www set a status path (www's from the last file),
	// open listens on every address without allowed clients.
	want := map[string]any{"listen_queue": 3, "max_children_reached": 5, "pools": 4, "pools_exposed": 1,
		"pools_read": 2, "slow_requests": 4}
	got, _ := json.Marshal(res.Values)
	wantJSON, _ := json.Marshal(want)
	if string(got) != string(wantJSON) {
		t.Errorf("values = %s, want %s", got, wantJSON)
	}
	noneOf(t, res.Values, "www", "api", "/run/php", "status", "127.0.0.1")
	if strings.Join(*dialed, " ") != "/run/php/www.sock" || fmt.Sprint(*hints) != fmt.Sprint([]int{port}) {
		t.Errorf("dialed %q and ports %v, want the socket of www and the port of api", *dialed, *hints)
	}
	if strings.Join(f.asked, " ") != "/status-api?json /st2?json" {
		t.Errorf("asked %q, want each pool's status path with json", f.asked)
	}
}

func TestFPMPoolsWithoutAStatusPathCountsThePoolsOnly(t *testing.T) {
	dialed := stubFPMSocket(t, "", &fpmServer{})
	fpmPoolFiles(t, map[string]string{"www.conf": "[www]\nlisten = /run/php/php8.4-fpm.sock\n[tcp]\nlisten = 0.0.0.0:9001\n"})

	got, err := fpmPools(context.Background(), Target{Kind: kindUnit, Name: "php8.4-fpm.service"})

	if err != nil || fmt.Sprint(got) != "map[listen_queue:0 max_children_reached:0 pools:2 pools_exposed:1 pools_read:0 slow_requests:0]" {
		t.Errorf("fpmPools = %v, %v; want two pools, one exposed, none read", got, err)
	}
	if len(*dialed) != 0 {
		t.Errorf("dialed %q, want no socket without a status path", *dialed)
	}
}

func TestPoolDirIsThePlaceOfThePackages(t *testing.T) {
	want := map[string]string{"php8.4-fpm.service": "", "php-fpm.service": "", "php_fpm": "", "php-fpm": "",
		"php84-php-fpm.service": "", "nginx.service": "", "php-fpm8.4.service": ""}
	switch runtime.GOOS {
	case "linux":
		want["php8.4-fpm.service"], want["php-fpm.service"], want["php-fpm"] = "/etc/php/8.4/fpm/pool.d", "/etc/php-fpm.d", "/etc/php-fpm.d"
	case "freebsd":
		want["php_fpm"], want["php-fpm"] = "/usr/local/etc/php-fpm.d", "/usr/local/etc/php-fpm.d"
	}
	for unit, dir := range want {
		got, err := poolDirOf(unit)
		if got != dir || (dir == "") != errors.Is(err, ErrUnsupported) {
			t.Errorf("poolDirOf(%s) = %q, %v; want %q", unit, got, err, dir)
		}
	}
}

func TestAPoolIsExposedOnTCPBeyondLoopbackWithoutAllowedClients(t *testing.T) {
	for listen, want := range map[string]bool{
		"9000": true, "0.0.0.0:9000": true, "*:9000": true, "[::]:9000": true, "192.0.2.5:9000": true,
		"127.0.0.1:9000": false, "[::1]:9000": false, "localhost:9000": false, "127.0.0.2:9000": false,
		"/run/php/php8.4-fpm.sock": false, "": false, "99999": false,
	} {
		if got := fpmExposed(fpmPool{listen: listen}); got != want {
			t.Errorf("fpmExposed(%q) = %v, want %v", listen, got, want)
		}
		if fpmExposed(fpmPool{listen: listen, allowedClients: "127.0.0.1"}) {
			t.Errorf("fpmExposed(%q) with allowed clients, want not exposed", listen)
		}
	}
}

func TestIniValueDropsQuotesAndComments(t *testing.T) {
	for in, want := range map[string]string{
		` /status `: "/status", ` "/a;b" ; c`: "/a;b", ` '/x' `: "/x", ` /y ; comment`: "/y", ` "open`: `"open`, ``: "",
	} {
		if got := iniValue(in); got != want {
			t.Errorf("iniValue(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestFPMPoolsWithoutAReadablePoolIsUnsupported(t *testing.T) {
	ctx := context.Background()
	unit := Target{Kind: kindUnit, Name: "php8.4-fpm.service"}
	if _, err := fpmPools(ctx, Target{Kind: kindUnit, Name: "nginx.service"}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("another unit = %v, want ErrUnsupported", err)
	}

	old := fpmPoolDir
	fpmPoolDir = func(string) (string, error) { return filepath.Join(t.TempDir(), "pool.d"), nil }
	if _, err := fpmPools(ctx, unit); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no pool directory = %v, want ErrUnsupported", err)
	}
	fpmPoolDir = old

	for name, conf := range map[string]string{
		"no pool":               "[global]\npid = /run/php-fpm.pid\n",
		"nobody on the socket":  "[www]\nlisten = /run/php/gone.sock\npm.status_path = /status\n",
		"a relative socket":     "[www]\nlisten = php.sock\npm.status_path = /status\n",
		"an unknown expression": "[www]\nlisten = ${FPM_LISTEN}\npm.status_path = /status\n",
	} {
		t.Run(name, func(t *testing.T) {
			stubFPMSocket(t, "/run/php/www.sock", &fpmServer{})
			fpmPoolFiles(t, map[string]string{"www.conf": conf})
			if _, err := fpmPools(ctx, unit); !errors.Is(err, ErrUnsupported) {
				t.Errorf("fpmPools = %v, want ErrUnsupported", err)
			}
		})
	}

	t.Run("a port the unit does not listen on", func(t *testing.T) {
		f := &fpmServer{pages: map[string]string{"/status": fpmPage("www", 0, 0, 0)}}
		port, _ := serveFPMPort(t, f, true)
		fpmPoolFiles(t, map[string]string{"www.conf": fmt.Sprintf("[www]\nlisten = %d\npm.status_path = /status\n", port)})
		if _, err := fpmPools(ctx, unit); !errors.Is(err, ErrUnsupported) || len(f.asked) != 0 {
			t.Errorf("fpmPools = %v after %q, want ErrUnsupported without a request", err, f.asked)
		}
	})
}

func TestFPMPoolsFailsOnAStatusPageItDoesNotKnow(t *testing.T) {
	unit := Target{Kind: kindUnit, Name: "php-fpm.service"}
	for name, c := range map[string]struct{ path, page, want string }{
		"no page at the path": {"/status", "", "status 404"},
		"a page without slow requests": {"/status", `{"listen queue":0,"max children reached":0}`,
			"no status page of php-fpm"},
		"no JSON":                {"/status", "pool: www", "no status page of php-fpm"},
		"a path it does not ask": {"/sta tus", fpmPage("www", 0, 0, 0), "does not ask for"},
		"a path too long":        {"/" + strings.Repeat("s", 122), fpmPage("www", 0, 0, 0), "does not ask for"},
	} {
		t.Run(name, func(t *testing.T) {
			pages := map[string]string{}
			if c.page != "" {
				pages[c.path] = c.page
			}
			stubFPMSocket(t, "/run/php-fpm/www.sock", &fpmServer{pages: pages})
			fpmPoolFiles(t, map[string]string{"www.conf": "[www]\nlisten = /run/php-fpm/www.sock\npm.status_path = \"" + c.path + "\"\n"})
			_, err := fpmPools(context.Background(), unit)
			if err == nil || errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), c.want) || strings.Contains(err.Error(), c.path) {
				t.Errorf("fpmPools = %v, want an error naming %q and not the path", err, c.want)
			}
		})
	}
}
