// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"os/exec"
	"regexp"
	"slices"
	"strconv"
	"strings"
)

const (
	// maxStatusPage caps the status page a web server answers (stub_status is about 100 bytes,
	// mod_status ?auto about 2 KiB with a scoreboard of thousands of slots).
	maxStatusPage = 64 << 10
	// maxApacheFiles and maxApacheFileBytes cap the configuration files apacheStatus reads.
	maxApacheFiles     = 512
	maxApacheFileBytes = 1 << 20
	// haproxyConfig is the configuration haproxy.service of Debian and RHEL starts with (-f).
	haproxyConfig = "/etc/haproxy/haproxy.cfg"
)

var (
	// webEndpoint finds where the unit of a web server listens; tests point it at their server.
	webEndpoint = resolve
	// haproxyConfigured tells whether HAProxy's configuration is at the place of the packages; tests
	// stand in their own.
	haproxyConfigured = func() bool { _, err := os.Stat(haproxyConfig); return err == nil }
)

// webServer is the web server a unit runs, by the unit names of the Debian and RHEL packages: nginx,
// apache2 (Debian), httpd (RHEL) or haproxy; "" for any other unit.
func webServer(unit string) string {
	name := strings.TrimSuffix(unit, ".service")
	if slices.Contains([]string{"nginx", "apache2", "httpd", "haproxy"}, name) {
		return name
	}
	return ""
}

// apacheCtl is the control script of Apache by its unit: apache2ctl on Debian, apachectl on RHEL.
func apacheCtl(server string) string {
	if server == "apache2" {
		return "apache2ctl"
	}
	return "apachectl"
}

// webConfig runs the configuration test of the web server of the unit and reports whether its
// configuration loads (config_ok), never what the test prints: that names files, lines and
// directives. A failed test is a value: the next reload (certbot's renewal hook, a package update)
// would fail on it while the running server goes on.
//
// The tests read the configuration and start nothing: nginx -t (nginx.org/en/docs/switches.html),
// apachectl -t (httpd.apache.org/docs/2.4/programs/apachectl.html), haproxy -c (Management Guide 3,
// "-c : only performs a check of the configuration files and exits before trying to bind"). nginx -t
// opens the log files the configuration names, as a start would.
func webConfig(ctx context.Context, t Target) (map[string]any, error) {
	server := webServer(t.Name)
	var name string
	var args []string
	switch server {
	case "nginx":
		name, args = "nginx", []string{"-t"}
	case "apache2", "httpd":
		name, args = apacheCtl(server), []string{"-t"}
	case "haproxy":
		// haproxy -c fails alike for a file it cannot open: without the file the test says nothing.
		if !haproxyConfigured() {
			return nil, fmt.Errorf("%w: %s has no configuration at the place of the packages", ErrUnsupported, t.Name)
		}
		name, args = "haproxy", []string{"-c", "-q", "-f", haproxyConfig}
	default:
		return nil, fmt.Errorf("%w: unit %s runs no web server the view knows", ErrUnsupported, t.Name)
	}
	_, err := runTool(ctx, toolTimeout, name, args...)
	var exitErr *exec.ExitError
	switch {
	case err == nil:
		return map[string]any{"config_ok": true}, nil
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: %s is not installed", ErrUnsupported, name)
	case ctx.Err() != nil:
		return nil, ctx.Err()
	case errors.As(err, &exitErr):
		return map[string]any{"config_ok": false}, nil
	}
	return nil, fmt.Errorf("%s: %w", name, err)
}

// statusPlace is where a web server's configuration serves its status page on loopback: the port, the
// Host header to send and the path.
type statusPlace struct {
	port       int
	host, path string
}

// nginxStatus reads the counters of nginx's stub_status from a place its configuration already
// serves it on loopback; it adds none. dropped is accepts minus handled: connections nginx accepted
// and closed at once, at worker_connections.
//
// ngx_http_stub_status_module (nginx.org/en/docs/http/ngx_http_stub_status_module.html): "Active
// connections: N", "server accepts handled requests", the three counters, "Reading: N Writing: N
// Waiting: N"; checked against nginx 1.30.
func nginxStatus(ctx context.Context, t Target) (map[string]any, error) {
	if webServer(t.Name) != "nginx" {
		return nil, fmt.Errorf("%w: unit %s is no nginx", ErrUnsupported, t.Name)
	}
	out, err := runTool(ctx, toolTimeout, "nginx", "-T")
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: nginx is not installed", ErrUnsupported)
	case ctx.Err() != nil:
		return nil, ctx.Err()
	case errors.As(err, &exitErr):
		// nginx -T prints nothing of a configuration that does not load; web_config reports that.
		return nil, errors.New("nginx -T fails: the configuration does not load")
	case err != nil:
		return nil, fmt.Errorf("nginx: %w", err)
	}
	place, ok := nginxStatusPlace(out)
	if !ok {
		return nil, fmt.Errorf("%w: the configuration of nginx serves no stub_status on loopback", ErrUnsupported)
	}
	page, err := askStatusPage(ctx, t, place, "")
	if err != nil {
		return nil, err
	}
	return parseStubStatus(page)
}

// parseStubStatus reads the page of stub_status.
func parseStubStatus(page []byte) (map[string]any, error) {
	bad := errors.New("nginx answers its stub_status place with a page of another form")
	lines := strings.Split(strings.TrimSpace(string(page)), "\n")
	if len(lines) != 4 || strings.TrimSpace(lines[1]) != "server accepts handled requests" {
		return nil, bad
	}
	active, ok := strings.CutPrefix(strings.TrimSpace(lines[0]), "Active connections: ")
	counts := strings.Fields(lines[2])
	rw := strings.Fields(lines[3])
	if !ok || len(counts) != 3 || len(rw) != 6 || rw[0] != "Reading:" || rw[2] != "Writing:" || rw[4] != "Waiting:" {
		return nil, bad
	}
	names := []string{"active", "accepts", "handled", "requests", "reading", "writing", "waiting"}
	values := map[string]any{}
	for i, s := range []string{active, counts[0], counts[1], counts[2], rw[1], rw[3], rw[5]} {
		n, err := strconv.ParseInt(s, 10, 64)
		if err != nil || n < 0 {
			return nil, bad
		}
		values[names[i]] = n
	}
	values["dropped"] = values["accepts"].(int64) - values["handled"].(int64)
	return values, nil
}

// nginxStatusPlace finds a stub_status in the dump of nginx -T: a location of a literal path whose
// server listens on a loopback address, or on all addresses with localhost or 127.0.0.1 among its
// server_name (else a request to loopback would reach another server). The dump holds each file
// apart, after a line "# configuration file <path>:"; a stub_status in a file a server includes from
// another file is not found.
func nginxStatusPlace(dump []byte) (statusPlace, bool) {
	for _, file := range splitNginxDump(dump) {
		if place, ok := nginxFilePlace(nginxTokens(file)); ok {
			return place, true
		}
	}
	return statusPlace{}, false
}

func splitNginxDump(dump []byte) [][]byte {
	var files [][]byte
	var cur []byte
	for line := range bytes.Lines(dump) {
		if bytes.HasPrefix(line, []byte("# configuration file ")) {
			files = append(files, cur)
			cur = nil
			continue
		}
		cur = append(cur, line...)
	}
	return append(files, cur)
}

// nginxTokens splits nginx configuration text into words, quoted strings (without their quotes) and
// the single characters '{', '}' and ';'; it drops comments.
func nginxTokens(text []byte) []string {
	var toks []string
	s := string(text)
	for i := 0; i < len(s); {
		c := s[i]
		switch {
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
			i++
		case c == '#':
			for i < len(s) && s[i] != '\n' {
				i++
			}
		case c == '{' || c == '}' || c == ';':
			toks = append(toks, string(c))
			i++
		case c == '"' || c == '\'':
			var b strings.Builder
			for i++; i < len(s) && s[i] != c; i++ {
				if s[i] == '\\' && i+1 < len(s) {
					i++
				}
				b.WriteByte(s[i])
			}
			toks = append(toks, b.String())
			i++
		default:
			j := i
			for j < len(s) && !strings.ContainsRune(" \t\r\n{};", rune(s[j])) {
				j++
			}
			toks = append(toks, s[i:j])
			i = j
		}
	}
	return toks
}

// nginxServer is what nginxFilePlace keeps of a server block.
type nginxServer struct {
	listens, names []string
	listened       bool
	paths          []string
}

func nginxFilePlace(toks []string) (statusPlace, bool) {
	type frame struct {
		name   string
		server *nginxServer
		path   string
	}
	var stack []frame
	var servers []*nginxServer
	var words []string
	top := func() frame {
		if len(stack) == 0 {
			return frame{}
		}
		return stack[len(stack)-1]
	}
	for _, tok := range toks {
		switch tok {
		case "{":
			f := frame{server: top().server}
			if len(words) > 0 {
				f.name = words[0]
			}
			switch f.name {
			case "server":
				f.server = &nginxServer{}
				servers = append(servers, f.server)
			case "location":
				f.path = literalLocation(words[1:])
			}
			stack = append(stack, f)
			words = nil
		case "}":
			if len(stack) > 0 {
				stack = stack[:len(stack)-1]
			}
			words = nil
		case ";":
			f := top()
			switch {
			case len(words) == 0 || f.server == nil:
			case words[0] == "listen" && f.name == "server" && len(words) > 1:
				f.server.listened = true
				if !slices.Contains(words[2:], "ssl") && !slices.Contains(words[2:], "quic") {
					f.server.listens = append(f.server.listens, words[1])
				}
			case words[0] == "server_name" && f.name == "server":
				f.server.names = append(f.server.names, words[1:]...)
			case words[0] == "stub_status" && f.name == "location" && f.path != "":
				f.server.paths = append(f.server.paths, f.path)
			}
			words = nil
		default:
			words = append(words, tok)
		}
	}
	for _, s := range servers {
		if len(s.paths) == 0 {
			continue
		}
		listens := s.listens
		if !s.listened {
			listens = []string{"80"} // nginx's default listen (as root)
		}
		for _, l := range listens {
			if place, ok := loopbackPlace(l, s.names); ok {
				place.path = s.paths[0]
				return place, true
			}
		}
	}
	return statusPlace{}, false
}

// safePath is a path the views ask: letters, digits and /_.-, from the root.
var safePath = regexp.MustCompile(`^/[A-Za-z0-9/_.-]*$`)

// literalLocation is the path of a location of a literal path ("= /x", "^~ /x" or "/x"), "" for a
// regular expression or a named location.
func literalLocation(args []string) string {
	if len(args) == 2 && (args[0] == "=" || args[0] == "^~") {
		args = args[1:]
	}
	if len(args) != 1 || !safePath.MatchString(args[0]) {
		return ""
	}
	return args[0]
}

// loopbackPlace reads one listen address of nginx ("127.0.0.1:8080", "[::1]:80", "localhost",
// "8080", "*:80", "unix:…") or of Apache: a loopback address is a place as it is; all addresses only
// with a server name localhost or 127.0.0.1, which then goes into the Host header.
func loopbackPlace(listen string, names []string) (statusPlace, bool) {
	if strings.HasPrefix(listen, "unix:") {
		return statusPlace{}, false
	}
	host, portText := listen, "80"
	if _, err := strconv.Atoi(listen); err == nil {
		host, portText = "*", listen
	} else if h, p, err := net.SplitHostPort(listen); err == nil {
		host, portText = h, p
	}
	port, err := strconv.Atoi(portText)
	if err != nil || port < 1 || port > 65535 {
		return statusPlace{}, false
	}
	if host == "localhost" {
		return statusPlace{port: port, host: "localhost"}, true
	}
	if a, err := netip.ParseAddr(strings.Trim(host, "[]")); err == nil && a.IsLoopback() {
		// The Host header takes an IPv6 address in brackets (RFC 9110 7.2, RFC 3986 3.2.2).
		h := a.String()
		if a.Is6() {
			h = "[" + h + "]"
		}
		return statusPlace{port: port, host: h}, true
	}
	if a, err := netip.ParseAddr(host); host == "*" || host == "_default_" || (err == nil && a.IsUnspecified()) {
		for _, n := range names {
			if n == "localhost" || n == "127.0.0.1" {
				return statusPlace{port: port, host: n}, true
			}
		}
	}
	return statusPlace{}, false
}

// apacheStatus reads the workers of Apache's mod_status from a place its configuration already
// serves it on loopback (a <Location> with SetHandler server-status); it adds none. slots is the
// length of the scoreboard, ServerLimit times ThreadsPerChild, which by default is MaxRequestWorkers
// (the page does not carry the limit itself); busy_pct is busy workers against slots.
//
// mod_status (httpd.apache.org/docs/2.4/mod/mod_status.html), the machine readable form ?auto:
// "BusyWorkers: N", "IdleWorkers: N", "Scoreboard: <one character per slot>"; checked against httpd
// 2.4.68, the field names are not in the documentation.
func apacheStatus(ctx context.Context, t Target) (map[string]any, error) {
	server := webServer(t.Name)
	if server != "apache2" && server != "httpd" {
		return nil, fmt.Errorf("%w: unit %s is no Apache", ErrUnsupported, t.Name)
	}
	ctl := apacheCtl(server)
	out, err := runTool(ctx, toolTimeout, ctl, "-t", "-D", "DUMP_INCLUDES")
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: %s is not installed", ErrUnsupported, ctl)
	case ctx.Err() != nil:
		return nil, ctx.Err()
	case errors.As(err, &exitErr):
		return nil, fmt.Errorf("%s -t fails: the configuration does not load", ctl)
	case err != nil:
		return nil, fmt.Errorf("%s: %w", ctl, err)
	}
	place, ok, err := apacheStatusPlace(apacheIncludes(out))
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, fmt.Errorf("%w: the configuration of Apache serves no server-status on loopback", ErrUnsupported)
	}
	page, err := askStatusPage(ctx, t, place, "auto")
	if err != nil {
		return nil, err
	}
	return parseModStatus(page)
}

// includedFile is a line of DUMP_INCLUDES: "  (*) /etc/apache2/apache2.conf" for the main file,
// "    (146) /etc/apache2/mods-enabled/status.conf" for one it includes at line 146 (checked against
// httpd 2.4.68; the form is not documented).
var includedFile = regexp.MustCompile(`^\s*\((?:\*|[0-9]+)\) (/.+)$`)

// apacheIncludes lists the files of Apache's configuration from the output of -D DUMP_INCLUDES.
func apacheIncludes(out []byte) []string {
	var files []string
	for line := range strings.Lines(string(out)) {
		if m := includedFile.FindStringSubmatch(strings.TrimRight(line, "\r\n")); m != nil {
			files = append(files, m[1])
		}
	}
	return files
}

// apacheStatusPlace finds a <Location> of a literal path with SetHandler server-status in the
// files of Apache's configuration. Outside a <VirtualHost> it is served on every Listen, by the
// main server and the virtual hosts that inherit it; inside one on the addresses of the virtual
// host, all addresses only with a ServerName or ServerAlias localhost or 127.0.0.1. Its port must be
// one of a Listen on loopback or all addresses that is not HTTPS (protocol https, or 443 without
// one). <IfModule> and <IfDefine> count as if they held, so a place the configuration switches off
// gives an error of the request, not unsupported.
func apacheStatusPlace(files []string) (statusPlace, bool, error) {
	if len(files) > maxApacheFiles {
		return statusPlace{}, false, fmt.Errorf("the configuration of Apache has more than %d files", maxApacheFiles)
	}
	type vhost struct{ addrs, names []string }
	type location struct {
		path   string
		vhost  *vhost // nil outside a virtual host
		status bool
	}
	var locs []*location
	var listens []string
	for _, name := range files {
		text, err := readCapped(name, maxApacheFileBytes)
		if err != nil {
			return statusPlace{}, false, errors.New("a file of the configuration of Apache cannot be read")
		}
		var vh *vhost
		var cur *location
		for _, line := range apacheLines(text) {
			f := strings.Fields(line)
			switch key := strings.ToLower(f[0]); {
			case key == "<virtualhost":
				vh = &vhost{addrs: apacheArgs(f[1:])}
			case key == "</virtualhost>":
				vh = nil
			case key == "<location":
				cur = nil
				if args := apacheArgs(f[1:]); len(args) == 1 && safePath.MatchString(args[0]) {
					cur = &location{path: args[0], vhost: vh}
					locs = append(locs, cur)
				}
			case key == "</location>":
				cur = nil
			case key == "sethandler" && cur != nil && len(f) == 2:
				cur.status = strings.EqualFold(strings.Trim(f[1], `"`), "server-status")
			case (key == "servername" || key == "serveralias") && vh != nil:
				vh.names = append(vh.names, f[1:]...)
			case key == "listen" && vh == nil && len(f) >= 2 && !apacheHTTPS(f[1:]):
				listens = append(listens, f[1])
			}
		}
	}
	ports := map[int]bool{}
	for _, l := range listens {
		if p, ok := loopbackPlace(l, []string{"localhost"}); ok {
			ports[p.port] = true
		}
	}
	for _, loc := range locs {
		if !loc.status {
			continue
		}
		addrs, names := listens, []string{"localhost"}
		if loc.vhost != nil {
			addrs, names = loc.vhost.addrs, loc.vhost.names
		}
		for _, a := range addrs {
			if p, ok := loopbackPlace(a, names); ok && ports[p.port] {
				p.path = loc.path
				return p, true, nil
			}
		}
	}
	return statusPlace{}, false, nil
}

// apacheHTTPS tells whether the arguments of a Listen ([addr:]port [protocol]) name HTTPS.
func apacheHTTPS(args []string) bool {
	if len(args) > 1 {
		return strings.EqualFold(args[1], "https")
	}
	_, port, err := net.SplitHostPort(args[0])
	if err != nil {
		port = args[0]
	}
	return port == "443"
}

// apacheLines returns the directives of an Apache configuration file, one per line: continuations
// ("\" at the end) joined, comments and empty lines dropped.
func apacheLines(text []byte) []string {
	var lines []string
	var cur strings.Builder
	for raw := range strings.Lines(string(text)) {
		line := strings.TrimSpace(raw)
		if strings.HasSuffix(line, "\\") {
			cur.WriteString(strings.TrimSuffix(line, "\\") + " ")
			continue
		}
		cur.WriteString(line)
		full := strings.TrimSpace(cur.String())
		cur.Reset()
		if full != "" && !strings.HasPrefix(full, "#") {
			lines = append(lines, full)
		}
	}
	return lines
}

// apacheArgs strips the closing '>' and the quotes of a section's arguments.
func apacheArgs(f []string) []string {
	var args []string
	for _, a := range f {
		a = strings.Trim(strings.TrimSuffix(a, ">"), `"`)
		if a != "" {
			args = append(args, a)
		}
	}
	return args
}

// parseModStatus reads the page of mod_status ?auto.
func parseModStatus(page []byte) (map[string]any, error) {
	bad := errors.New("Apache answers its server-status place with a page of another form")
	fields := map[string]string{}
	for line := range strings.Lines(string(page)) {
		if k, v, ok := strings.Cut(strings.TrimRight(line, "\r\n"), ": "); ok {
			fields[k] = v
		}
	}
	busy, err1 := strconv.Atoi(fields["BusyWorkers"])
	idle, err2 := strconv.Atoi(fields["IdleWorkers"])
	slots := len(fields["Scoreboard"])
	if err1 != nil || err2 != nil || busy < 0 || idle < 0 || slots == 0 {
		return nil, bad
	}
	return map[string]any{
		"busy_workers": busy, "idle_workers": idle, "slots": slots,
		"busy_pct": float64(busy) * 100 / float64(slots),
	}, nil
}

// askStatusPage GETs a status page of the unit at place, on loopback through the guard; the unit must
// listen on its port.
func askStatusPage(ctx context.Context, t Target, place statusPlace, query string) ([]byte, error) {
	t.PortHint = place.port
	ep, err := webEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	if int(ep.port) != place.port {
		return nil, fmt.Errorf("%w: unit %s does not listen on the port of its status page", ErrUnsupported, t.Name)
	}
	if !ep.addr.IsLoopback() {
		return nil, fmt.Errorf("unit %s does not listen on loopback on the port of its status page", t.Name)
	}
	u := url.URL{Scheme: "http", Host: netip.AddrPortFrom(ep.addr, ep.port).String(), Path: place.path, RawQuery: query}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, errors.New("the request for the status page cannot be built")
	}
	req.Host = place.host
	resp, err := NewGuard(ep.extra...).HTTPClient(nil).Do(req)
	if err != nil {
		return nil, netErr(ctx, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unit %s answers its status page with HTTP %d", t.Name, resp.StatusCode)
	}
	page, err := io.ReadAll(io.LimitReader(resp.Body, maxStatusPage+1))
	if err != nil {
		return nil, netErr(ctx, err)
	}
	if len(page) > maxStatusPage {
		return nil, fmt.Errorf("unit %s answers its status page with more than %d bytes", t.Name, maxStatusPage)
	}
	return page, nil
}
