// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func webUnit(name string) Target { return Target{Kind: kindUnit, Name: name} }

func stubHAProxyConfigured(t *testing.T, ok bool) {
	t.Helper()
	old := haproxyConfigured
	haproxyConfigured = func() bool { return ok }
	t.Cleanup(func() { haproxyConfigured = old })
}

func TestWebConfigRunsTheTestOfTheServerOfTheUnit(t *testing.T) {
	stubHAProxyConfigured(t, true)
	for unit, want := range map[string][]string{
		"nginx.service":   {"nginx", "-t"},
		"apache2.service": {"apache2ctl", "-t"},
		"httpd":           {"apachectl", "-t"},
		"haproxy.service": {"haproxy", "-c", "-q", "-f", "/etc/haproxy/haproxy.cfg"},
	} {
		calls := stubTools(t, answer{out: "Syntax OK\n/etc/secret/path.conf\n"})
		got, err := webConfig(context.Background(), webUnit(unit))
		if err != nil || got["config_ok"] != true || len(got) != 1 {
			t.Errorf("%s = %v, %v; want config_ok alone", unit, got, err)
		}
		if len(*calls) != 1 || strings.Join((*calls)[0], " ") != strings.Join(want, " ") {
			t.Errorf("%s ran %q, want %q", unit, *calls, want)
		}
	}
}

func TestAFailedConfigTestIsAValueWithoutItsText(t *testing.T) {
	fail := toolExit(t, 1, "nginx: [emerg] unknown directive \"proxy_passs\" in /etc/nginx/sites-enabled/secret.conf:12")
	stubTools(t, answer{err: fail})
	got, err := webConfig(context.Background(), webUnit("nginx.service"))
	if err != nil || got["config_ok"] != false || len(got) != 1 {
		t.Fatalf("web_config = %v, %v; want config_ok false alone", got, err)
	}
	noneOf(t, got, "secret", "proxy_passs", "/etc/nginx")
}

func TestWebConfigWithoutTheServer(t *testing.T) {
	stubTools(t, answer{err: notInstalled("nginx")})
	if _, err := webConfig(context.Background(), webUnit("nginx.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("nginx not installed = %v, want ErrUnsupported", err)
	}

	// Without the configuration file haproxy -c fails as for a broken one: the view does not ask.
	stubHAProxyConfigured(t, false)
	calls := stubTools(t)
	if _, err := webConfig(context.Background(), webUnit("haproxy.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("haproxy without its file = %v, want ErrUnsupported", err)
	}
	for _, unit := range []string{"caddy.service", "nginx-exporter.service", "lighttpd.service"} {
		if _, err := webConfig(context.Background(), webUnit(unit)); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s = %v, want ErrUnsupported", unit, err)
		}
	}
	if len(*calls) != 0 {
		t.Errorf("ran %q, want nothing", *calls)
	}
}

func TestWebConfigTakesTheContextsEnd(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	stubTools(t, answer{err: errors.New("signal: killed")})
	if _, err := webConfig(ctx, webUnit("nginx.service")); !errors.Is(err, context.Canceled) {
		t.Errorf("canceled = %v, want context.Canceled", err)
	}
}

// nginxDump has the form of nginx -T (checked against nginx 1.30): the files one after the other,
// each after a line naming it, includes not inlined.
func nginxDump(files ...string) string {
	var b strings.Builder
	b.WriteString("# configuration file /etc/nginx/nginx.conf:\nevents {}\nhttp { include /etc/nginx/conf.d/*.conf; }\n\n")
	for i, f := range files {
		fmt.Fprintf(&b, "# configuration file /etc/nginx/conf.d/%d.conf:\n%s\n\n", i, f)
	}
	return b.String()
}

func TestNginxStatusPlaceTakesOnlyAPlaceOnLoopback(t *testing.T) {
	cases := []struct {
		name, conf string
		want       statusPlace
		ok         bool
	}{
		{"loopback", `server { listen 127.0.0.1:8080; location = /nginx_status { stub_status; } }`,
			statusPlace{8080, "127.0.0.1", "/nginx_status"}, true},
		{"IPv6 loopback", `server { listen [::1]:81; location /st { stub_status on; } }`,
			statusPlace{81, "[::1]", "/st"}, true},
		{"localhost", `server { listen localhost:82; location ^~ /basic_status { stub_status; } }`,
			statusPlace{82, "localhost", "/basic_status"}, true},
		{"all addresses with server_name localhost", `server {
			listen 80 default_server; listen [::]:80;
			server_name localhost;
			location /status { stub_status; allow 127.0.0.1; deny all; }
		}`, statusPlace{80, "localhost", "/status"}, true},
		{"no listen means 80", `server { server_name 127.0.0.1; location /s { stub_status; } }`,
			statusPlace{80, "127.0.0.1", "/s"}, true},
		{"quoted and commented", `server { # listen 9999;
			listen "127.0.0.1:8081"; # location /x { stub_status; }
			location "/q" { stub_status; } }`, statusPlace{8081, "127.0.0.1", "/q"}, true},
		{"TLS listen skipped for the next", `server { listen 127.0.0.1:443 ssl; listen 127.0.0.1:8082;
			location /s { stub_status; } }`, statusPlace{8082, "127.0.0.1", "/s"}, true},

		// A request to loopback on all addresses reaches the default server, maybe another one.
		{"all addresses without a local name", `server { listen 80; server_name example.org; location /s { stub_status; } }`,
			statusPlace{}, false},
		{"another address", `server { listen 192.0.2.10:8080; location /s { stub_status; } }`, statusPlace{}, false},
		{"TLS only", `server { listen 127.0.0.1:443 ssl; location /s { stub_status; } }`, statusPlace{}, false},
		{"QUIC only", `server { listen 127.0.0.1:443 quic; location /s { stub_status; } }`, statusPlace{}, false},
		{"unix socket", `server { listen unix:/run/nginx-status.sock; server_name localhost; location /s { stub_status; } }`,
			statusPlace{}, false},
		{"regular expression", `server { listen 127.0.0.1:8080; location ~ ^/st(atus)?$ { stub_status; } }`,
			statusPlace{}, false},
		{"named location", `server { listen 127.0.0.1:8080; location @st { stub_status; } }`, statusPlace{}, false},
		{"path with a query", `server { listen 127.0.0.1:8080; location /s?x=1 { stub_status; } }`, statusPlace{}, false},
		{"commented out", `server { listen 127.0.0.1:8080; location /s { # stub_status;
			return 404; } }`, statusPlace{}, false},
		{"in an if", `server { listen 127.0.0.1:8080; location /s { if ($x) { stub_status; } } }`, statusPlace{}, false},
		{"no stub_status", `server { listen 127.0.0.1:8080; location /s { return 200; } }`, statusPlace{}, false},
	}
	for _, c := range cases {
		got, ok := nginxStatusPlace([]byte(nginxDump(c.conf)))
		if ok != c.ok || got != c.want {
			t.Errorf("%s = %+v, %v; want %+v, %v", c.name, got, ok, c.want, c.ok)
		}
	}
}

func TestNginxStatusPlaceReadsEachFileApart(t *testing.T) {
	// A server of one file does not take the stub_status of another: that would be an include
	// nginx -T does not resolve.
	dump := nginxDump(`server { listen 127.0.0.1:8080;`, `location /s { stub_status; } }`)
	if got, ok := nginxStatusPlace([]byte(dump)); ok {
		t.Errorf("place across files = %+v", got)
	}
	dump = nginxDump(`server { listen 80; server_name example.org; }`,
		`server { listen 127.0.0.1:8090; location /nginx_status { stub_status; } }`)
	if got, ok := nginxStatusPlace([]byte(dump)); !ok || got != (statusPlace{8090, "127.0.0.1", "/nginx_status"}) {
		t.Errorf("place in the second file = %+v, %v", got, ok)
	}
}

// stubStatusPage is the page of stub_status as nginx 1.30 answers it, with its trailing blanks.
const stubStatusPage = "Active connections: 3 \nserver accepts handled requests\n 120 118 4711 \nReading: 0 Writing: 1 Waiting: 2 \n"

func TestParseStubStatus(t *testing.T) {
	got, err := parseStubStatus([]byte(stubStatusPage))
	want := map[string]any{"active": int64(3), "accepts": int64(120), "handled": int64(118), "requests": int64(4711),
		"reading": int64(0), "writing": int64(1), "waiting": int64(2), "dropped": int64(2)}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("stub_status = %v, %v; want %v", got, err, want)
	}
	for _, page := range []string{
		"",
		"<html>404</html>",
		strings.Replace(stubStatusPage, "Waiting", "Idle", 1),
		strings.Replace(stubStatusPage, " 120 118 4711", " 120 118", 1),
		strings.Replace(stubStatusPage, "Active connections: 3", "Active connections: -3", 1),
		stubStatusPage + "extra\n",
	} {
		if _, err := parseStubStatus([]byte(page)); err == nil {
			t.Errorf("page %q read without error", page)
		}
	}
}

// statusServer is a web server on loopback the status views are pointed at; it answers every request
// with status and page and keeps what it was asked.
type statusServer struct {
	mu    sync.Mutex
	asked []string
}

func (s *statusServer) requests() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.asked...)
}

func serveStatus(t *testing.T, status int, page string) (*statusServer, int) {
	t.Helper()
	s := &statusServer{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		s.asked = append(s.asked, r.Method+" "+r.Host+" "+r.URL.RequestURI())
		s.mu.Unlock()
		w.WriteHeader(status)
		_, _ = io.WriteString(w, page)
	}))
	t.Cleanup(srv.Close)
	freshSnapshot(t) // the guard is to see the listener just started
	// The tests stub runTool, through which the guard would ask docker for its published ports.
	oldPubs := publishedPorts
	publishedPorts = func(context.Context) ([]publication, error) { return nil, nil }
	t.Cleanup(func() { publishedPorts = oldPubs })
	port := portOf(t, srv.Listener.Addr().String())
	stubWebEndpoint(t, "127.0.0.1", port)
	return s, port
}

func stubWebEndpoint(t *testing.T, addr string, port int) *Target {
	t.Helper()
	var asked Target
	old := webEndpoint
	webEndpoint = func(_ context.Context, t Target) (endpoint, error) {
		asked = t
		return endpoint{addr: netip.MustParseAddr(addr), port: uint16(port)}, nil
	}
	t.Cleanup(func() { webEndpoint = old })
	return &asked
}

func TestNginxStatusReadsTheCountersOfItsPlace(t *testing.T) {
	srv, port := serveStatus(t, http.StatusOK, stubStatusPage)
	calls := stubTools(t, answer{out: nginxDump(fmt.Sprintf(
		`server { listen %d; server_name localhost; location = /nginx_status { stub_status; } }`, port))})

	got, err := nginxStatus(context.Background(), webUnit("nginx.service"))

	if err != nil || got["requests"] != int64(4711) || got["dropped"] != int64(2) || len(got) != 8 {
		t.Fatalf("nginx_status = %v, %v", got, err)
	}
	if strings.Join((*calls)[0], " ") != "nginx -T" {
		t.Errorf("ran %q, want nginx -T", *calls)
	}
	if want := "GET localhost /nginx_status"; strings.Join(srv.requests(), ",") != want {
		t.Errorf("asked %q, want %q", srv.requests(), want)
	}
}

func TestAnIPv6PlaceIsAskedWithItsAddressInBrackets(t *testing.T) {
	srv, port := serveStatus(t, http.StatusOK, stubStatusPage)
	stubTools(t, answer{out: nginxDump(fmt.Sprintf(`server { listen [::1]:%d; location /s { stub_status; } }`, port))})
	if _, err := nginxStatus(context.Background(), webUnit("nginx.service")); err != nil {
		t.Fatal(err)
	}
	if want := "GET [::1] /s"; strings.Join(srv.requests(), ",") != want {
		t.Errorf("asked %q, want %q", srv.requests(), want)
	}
}

func TestNginxStatusWithoutAPlaceOrAPageOfItsForm(t *testing.T) {
	stubTools(t, answer{out: nginxDump(`server { listen 80; location / { root /srv/www; } }`)})
	if _, err := nginxStatus(context.Background(), webUnit("nginx.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no place = %v, want ErrUnsupported", err)
	}

	_, port := serveStatus(t, http.StatusForbidden, "<html>403 /etc/nginx/secret</html>")
	conf := nginxDump(fmt.Sprintf(`server { listen 127.0.0.1:%d; location /s { stub_status; } }`, port))
	stubTools(t, answer{out: conf})
	_, err := nginxStatus(context.Background(), webUnit("nginx.service"))
	if err == nil || errors.Is(err, ErrUnsupported) || strings.Contains(err.Error(), "secret") {
		t.Errorf("403 = %v, want an error without the page", err)
	}

	_, _ = serveStatus(t, http.StatusOK, strings.Repeat("x", maxStatusPage+1))
	stubTools(t, answer{out: conf})
	if _, err := nginxStatus(context.Background(), webUnit("nginx.service")); err == nil {
		t.Error("a page past the cap read without error")
	}

	stubTools(t, answer{err: toolExit(t, 1, "nginx: [emerg] in /etc/nginx/secret.conf")})
	if _, err := nginxStatus(context.Background(), webUnit("nginx.service")); err == nil || strings.Contains(err.Error(), "secret") {
		t.Errorf("failing nginx -T = %v, want an error without its text", err)
	}

	calls := stubTools(t)
	if _, err := nginxStatus(context.Background(), webUnit("apache2.service")); !errors.Is(err, ErrUnsupported) || len(*calls) != 0 {
		t.Errorf("another unit = %v after %q, want ErrUnsupported without a call", err, *calls)
	}
}

func TestStatusPagesAreAskedOnlyOnTheirPortOnLoopback(t *testing.T) {
	conf := nginxDump(`server { listen 127.0.0.1:8080; location /s { stub_status; } }`)

	// The unit listens elsewhere: its other port would be a site's.
	asked := stubWebEndpoint(t, "127.0.0.1", 8443)
	stubTools(t, answer{out: conf})
	if _, err := nginxStatus(context.Background(), webUnit("nginx.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("another port = %v, want ErrUnsupported", err)
	}
	if asked.PortHint != 8080 || asked.Name != "nginx.service" {
		t.Errorf("resolved %+v, want the port of the place as hint", *asked)
	}

	stubWebEndpoint(t, "192.0.2.10", 8080)
	stubTools(t, answer{out: conf})
	// The view refuses before any request; the guard would refuse such a request too, later.
	_, err := nginxStatus(context.Background(), webUnit("nginx.service"))
	if err == nil || !strings.Contains(err.Error(), "does not listen on loopback") {
		t.Errorf("an address beyond loopback = %v, want the view to refuse it", err)
	}
}

// apacheFiles writes the files of an Apache configuration into a directory and returns their paths,
// the main file first.
func apacheFiles(t *testing.T, files ...string) []string {
	t.Helper()
	dir := t.TempDir()
	var paths []string
	for i, f := range files {
		p := filepath.Join(dir, fmt.Sprintf("%d.conf", i))
		if err := os.WriteFile(p, []byte(f), 0o600); err != nil {
			t.Fatal(err)
		}
		paths = append(paths, p)
	}
	return paths
}

// debianPorts and debianStatus are ports.conf and mods-available/status.conf of Debian's apache2.
const debianPorts = `# If you just change the port or add more ports here, you will likely also
Listen 80

<IfModule ssl_module>
	Listen 443
</IfModule>

<IfModule mod_gnutls.c>
	Listen 443
</IfModule>
`

const debianStatus = `<IfModule mod_status.c>
	# Allow server status reports generated by mod_status,
	# with the URL of http://servername/server-status
	# Uncomment and change the "192.0.2.0/24" to allow access from other hosts.

	<Location /server-status>
		SetHandler server-status
		Require local
		#Require ip 192.0.2.0/24
	</Location>

	ExtendedStatus On
</IfModule>
`

func TestApacheStatusPlaceTakesOnlyAPlaceOnLoopback(t *testing.T) {
	cases := []struct {
		name  string
		files []string
		want  statusPlace
		ok    bool
	}{
		{"Debian", []string{debianPorts, debianStatus, "<VirtualHost *:80>\nServerName www.example.org\n</VirtualHost>\n"},
			statusPlace{80, "localhost", "/server-status"}, true},
		{"loopback listen", []string{"Listen 127.0.0.1:8081\n<Location \"/st\">\n  SetHandler server-status\n</Location>\n"},
			statusPlace{8081, "127.0.0.1", "/st"}, true},
		{"virtual host on loopback", []string{"Listen 80\nListen 8082\n" +
			"<VirtualHost 127.0.0.1:8082>\n<Location /st>\nSetHandler server-status\n</Location>\n</VirtualHost>\n"},
			statusPlace{8082, "127.0.0.1", "/st"}, true},
		{"virtual host named localhost after its location", []string{"Listen 8083 http\n" +
			"<VirtualHost *:8083>\n<Location /st>\nSetHandler server-status\n</Location>\nServerAlias localhost\n</VirtualHost>\n"},
			statusPlace{8083, "localhost", "/st"}, true},
		{"continuation", []string{"Listen \\\n 127.0.0.1:8084\n<Location /st>\nSetHandler \\\n server-status\n</Location>\n"},
			statusPlace{8084, "127.0.0.1", "/st"}, true},

		{"no Listen of its port", []string{"Listen 80\n<VirtualHost 127.0.0.1:8085>\n<Location /st>\n" +
			"SetHandler server-status\n</Location>\n</VirtualHost>\n"}, statusPlace{}, false},
		{"virtual host of another name", []string{"Listen 80\n<VirtualHost *:80>\nServerName www.example.org\n" +
			"<Location /st>\nSetHandler server-status\n</Location>\n</VirtualHost>\n"}, statusPlace{}, false},
		{"HTTPS only", []string{"Listen 443\nListen 127.0.0.1:8443 https\n<Location /st>\nSetHandler server-status\n</Location>\n"},
			statusPlace{}, false},
		{"another address", []string{"Listen 192.0.2.10:80\n<Location /st>\nSetHandler server-status\n</Location>\n"},
			statusPlace{}, false},
		{"commented", []string{"Listen 80\n<Location /st>\n#SetHandler server-status\n</Location>\n"}, statusPlace{}, false},
		{"another handler", []string{"Listen 80\n<Location /st>\nSetHandler server-info\n</Location>\n"}, statusPlace{}, false},
		{"LocationMatch", []string{"Listen 80\n<LocationMatch \"^/st\">\nSetHandler server-status\n</LocationMatch>\n"},
			statusPlace{}, false},
		{"path with a query", []string{"Listen 80\n<Location /st?x>\nSetHandler server-status\n</Location>\n"},
			statusPlace{}, false},
		{"handler outside a location", []string{"Listen 80\nSetHandler server-status\n"}, statusPlace{}, false},
	}
	for _, c := range cases {
		got, ok, err := apacheStatusPlace(apacheFiles(t, c.files...))
		if err != nil || ok != c.ok || got != c.want {
			t.Errorf("%s = %+v, %v, %v; want %+v, %v", c.name, got, ok, err, c.want, c.ok)
		}
	}
}

func TestApacheStatusPlaceErrorsNameNoFile(t *testing.T) {
	dir := t.TempDir()
	_, _, err := apacheStatusPlace([]string{filepath.Join(dir, "secret.conf")})
	if err == nil || strings.Contains(err.Error(), "secret") {
		t.Errorf("unreadable file = %v, want an error without its name", err)
	}
	if err := os.Mkdir(filepath.Join(dir, "d"), 0o700); err != nil {
		t.Fatal(err)
	}
	if _, _, err := apacheStatusPlace([]string{filepath.Join(dir, "d")}); err == nil {
		t.Error("a directory read as a configuration file")
	}
	if _, _, err := apacheStatusPlace(make([]string, maxApacheFiles+1)); err == nil {
		t.Error("more files than the cap read")
	}
}

// dumpIncludes has the form of apachectl -t -D DUMP_INCLUDES (checked against httpd 2.4.68).
func dumpIncludes(files []string) string {
	var b strings.Builder
	b.WriteString("Included configuration files:\n")
	for i, f := range files {
		if i == 0 {
			fmt.Fprintf(&b, "  (*) %s\n", f)
		} else {
			fmt.Fprintf(&b, "    (%d) %s\n", 100+i, f)
		}
	}
	return b.String()
}

func TestApacheIncludesListsTheFiles(t *testing.T) {
	out := "Included configuration files:\n  (*) /etc/apache2/apache2.conf\n    (146) /etc/apache2/mods-enabled/status.conf\r\n" +
		"      (12) /etc/apache2/sites-enabled/my site.conf\nSyntax OK\n"
	want := []string{"/etc/apache2/apache2.conf", "/etc/apache2/mods-enabled/status.conf", "/etc/apache2/sites-enabled/my site.conf"}
	if got := apacheIncludes([]byte(out)); strings.Join(got, "|") != strings.Join(want, "|") {
		t.Errorf("includes = %q, want %q", got, want)
	}
}

// modStatusAuto is a page of mod_status ?auto as httpd 2.4.68 answers it (shortened scoreboard).
const modStatusAuto = "127.0.0.1\nServerVersion: Apache/2.4.68 (Unix)\nServerMPM: event\nTotal Accesses: 12\n" +
	"BusyWorkers: 3\nIdleWorkers: 5\nScoreboard: WW_W____......\n"

func TestParseModStatus(t *testing.T) {
	got, err := parseModStatus([]byte(modStatusAuto))
	if err != nil || got["busy_workers"] != 3 || got["idle_workers"] != 5 || got["slots"] != 14 || len(got) != 4 {
		t.Fatalf("mod_status = %v, %v", got, err)
	}
	if pct := got["busy_pct"].(float64); pct < 21.42 || pct > 21.43 {
		t.Errorf("busy_pct = %v, want 3 of 14", pct)
	}
	for _, page := range []string{
		"",
		"<html><title>Apache Status</title></html>",
		strings.Replace(modStatusAuto, "Scoreboard: WW_W____......\n", "", 1),
		strings.Replace(modStatusAuto, "BusyWorkers: 3", "BusyWorkers: x", 1),
	} {
		if _, err := parseModStatus([]byte(page)); err == nil {
			t.Errorf("page %q read without error", page)
		}
	}
}

func TestApacheStatusReadsTheWorkersOfItsPlace(t *testing.T) {
	srv, port := serveStatus(t, http.StatusOK, modStatusAuto)
	files := apacheFiles(t, fmt.Sprintf("Listen %d\nInclude mods-enabled/*.conf\n", port), debianStatus)
	calls := stubTools(t, answer{out: dumpIncludes(files)})

	got, err := apacheStatus(context.Background(), webUnit("apache2.service"))

	if err != nil || got["busy_workers"] != 3 || got["slots"] != 14 {
		t.Fatalf("apache_status = %v, %v", got, err)
	}
	if strings.Join((*calls)[0], " ") != "apache2ctl -t -D DUMP_INCLUDES" {
		t.Errorf("ran %q", *calls)
	}
	if want := "GET localhost /server-status?auto"; strings.Join(srv.requests(), ",") != want {
		t.Errorf("asked %q, want %q", srv.requests(), want)
	}

	calls = stubTools(t, answer{out: dumpIncludes(files)})
	if _, err := apacheStatus(context.Background(), webUnit("httpd.service")); err != nil {
		t.Errorf("httpd = %v", err)
	}
	if (*calls)[0][0] != "apachectl" {
		t.Errorf("httpd ran %q, want apachectl", *calls)
	}
}

func TestApacheStatusWithoutAPlace(t *testing.T) {
	files := apacheFiles(t, "Listen 80\n")
	stubTools(t, answer{out: dumpIncludes(files)})
	if _, err := apacheStatus(context.Background(), webUnit("apache2.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no place = %v, want ErrUnsupported", err)
	}
	stubTools(t, answer{err: notInstalled("apache2ctl")})
	if _, err := apacheStatus(context.Background(), webUnit("apache2.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("not installed = %v, want ErrUnsupported", err)
	}
	stubTools(t, answer{err: toolExit(t, 1, "AH00526: Syntax error on line 3 of /etc/apache2/secret.conf")})
	if _, err := apacheStatus(context.Background(), webUnit("apache2.service")); err == nil || strings.Contains(err.Error(), "secret") {
		t.Errorf("failing test = %v, want an error without its text", err)
	}
	calls := stubTools(t)
	if _, err := apacheStatus(context.Background(), webUnit("nginx.service")); !errors.Is(err, ErrUnsupported) || len(*calls) != 0 {
		t.Errorf("another unit = %v after %q", err, *calls)
	}
}

func TestTheWebViewsAreRegisteredForUnits(t *testing.T) {
	for _, view := range []string{"web_config", "nginx_status", "apache_status"} {
		v, ok := appViews[view]
		if !ok || v.read == nil || strings.Join(v.kinds, ",") != strings.Join(unitKinds, ",") || v.uses != nil {
			t.Errorf("view %s = %+v, want one for units without a credential", view, v)
		}
	}
}
